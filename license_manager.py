import sqlite3
import os
import secrets
import string
import argparse
import hashlib
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil

# In Vercel serverless environment, local repo files are read-only. We use /tmp
IS_VERCEL = bool(os.environ.get("VERCEL"))
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path("/tmp/data") if IS_VERCEL else (BASE_DIR / "data")
DB_PATH = DATA_DIR / "licenses.db"
LICENSE_SECRET = os.environ.get("LICENSE_SECRET", "TGADDER_KUN_AMRA_2026_SECURE_SALT")

# ==========================================
# Central license server (Render backend)
# ==========================================
# Revocations are pushed here by the Telegram bot and pulled by every other
# instance (Vercel frontend, local bot, Render itself) so a key revoked in
# the bot is instantly invalid everywhere. Render owns the authoritative list.
LICENSE_API_BASE = os.environ.get("LICENSE_API_BASE", "https://telegram-adder-web.onrender.com").strip().rstrip("/")
ADMIN_MASTER_KEY = os.environ.get("ADMIN_MASTER_KEY", "kun_amra_admin_2026")
REVOKED_SYNC_TTL = float(os.environ.get("REVOKED_SYNC_TTL", "30"))
REVOKED_SYNC_TIMEOUT = float(os.environ.get("REVOKED_SYNC_TIMEOUT", "3"))

# Keys that were previously issued and then revoked in the Telegram bot.
# On startup (Vercel /tmp and Render) these are pre-added to the local
# blacklist so the hosted site rejects them immediately, even if the central
# server is unreachable. Comma-separated.
AUTO_REVOKE_SEED_KEYS = [
    k.strip().upper()
    for k in os.environ.get("AUTO_REVOKE_SEED_KEYS", "").split(",")
    if k.strip()
]

_revoked_sync_lock = threading.Lock()
_revoked_sync_cache = {"ts": 0.0, "keys": None, "failed": False}
_revoked_sync_inflight = False
_push_enabled = True  # disabled while the server applies a bulk push to avoid self-calls

def get_now_utc():
    return datetime.now(timezone.utc)

def get_connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    # In Vercel, if DB in /tmp does not exist yet, copy initial seed DB from bundle if present
    bundled_db = BASE_DIR / "data" / "licenses.db"
    if IS_VERCEL and not DB_PATH.exists() and bundled_db.exists():
        try:
            shutil.copy2(bundled_db, DB_PATH)
        except Exception:
            pass

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS licenses (
                key_code TEXT PRIMARY KEY,
                tier TEXT NOT NULL DEFAULT 'VIP',
                max_accounts INTEGER NOT NULL DEFAULT 50,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                bound_device TEXT,
                note TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                config_key TEXT PRIMARY KEY,
                config_value TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS revoked_keys (
                key_code TEXT PRIMARY KEY,
                revoked_at TEXT NOT NULL
            )
        """)

    # The revoked list must survive ephemeral filesystems (Vercel /tmp).
    # Restore anything from revoked_keys.json into the DB, then seed the
    # keys that were revoked in the bot before syncing existed.
    _migrate_revoked_file_to_db(conn)
    for seed in AUTO_REVOKE_SEED_KEYS:
        conn.execute(
            "INSERT OR IGNORE INTO revoked_keys (key_code, revoked_at) VALUES (?, ?)",
            (seed, get_now_utc().isoformat()),
        )
        # Also make sure any locally-stored copy of the key is marked inactive.
        conn.execute("UPDATE licenses SET is_active = 0 WHERE key_code = ?", (seed,))
    conn.commit()

    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM licenses")
    count = cursor.fetchone()[0]

    now = get_now_utc().isoformat()
    expires_30d = (get_now_utc() + timedelta(days=30)).isoformat()
    expires_3d = (get_now_utc() + timedelta(days=3)).isoformat()

    # Seed essential default & active keys using INSERT OR IGNORE so they exist on any new server/host
    conn.execute(
        "INSERT OR IGNORE INTO licenses (key_code, tier, max_accounts, is_active, created_at, expires_at, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("TGADD-VIP-LIFETIME-ACCESS", "VIP (Unlimited)", 100, 1, now, None, "Default Admin Lifetime Key")
    )
    conn.execute(
        "INSERT OR IGNORE INTO licenses (key_code, tier, max_accounts, is_active, created_at, expires_at, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("TGADD-TRIAL-30DAYS-PASS", "PRO", 25, 1, now, expires_30d, "30-Day Pro Trial Key")
    )
    conn.execute(
        "INSERT OR IGNORE INTO licenses (key_code, tier, max_accounts, is_active, created_at, expires_at, bound_device, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("TGADD-HEZ1-S41K-ZQJL", "Basic (Trial)", 25, 1, now, expires_3d, "MID-18E2B85D-1B81Z6", "Bot-issued key")
    )
    conn.commit()
    conn.close()

def _format_random_key(prefix="TGADD"):
    chars = string.ascii_uppercase + string.digits
    parts = [''.join(secrets.choice(chars) for _ in range(4)) for _ in range(3)]
    return f"{prefix}-{parts[0]}-{parts[1]}-{parts[2]}"

def generate_signed_key(machine_id: str, days: int = None, prefix: str = "TGADD") -> str:
    """
    Generates an algorithmically verifiable license key mathematically bound to machine_id.
    Format: TGADD-XXXX-YYYY-ZZZZ
    - XXXX: First 4 hex chars of machine ID
    - YYYY: Duration encoding (e.g. D001, D003, D007, D030, D090, LIFE)
    - ZZZZ: HMAC-SHA256 signature
    This allows any server (Render, Vercel, Local) to verify keys without shared DB.
    """
    if not machine_id:
        return _format_random_key(prefix)
    
    clean_mid = machine_id.replace("MID-", "").replace("-", "").strip().upper()
    p1 = clean_mid[:4].ljust(4, "0")
    
    if days is None or days == 0:
        p2 = "LIFE"
    elif days < 1000:
        p2 = f"D{days:03d}"
    else:
        p2 = "D999"
        
    raw = f"{p1}-{p2}-{LICENSE_SECRET}"
    sig = hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()[:4]
    return f"{prefix}-{p1}-{p2}-{sig}"

def verify_signed_key(key_code: str, machine_id: str = None):
    """
    Verifies if key_code is a valid cryptographically signed key for machine_id.
    Returns (valid: bool, reason: str, details: dict or None)
    """
    parts = key_code.strip().upper().split("-")
    if len(parts) != 4 or parts[0] != "TGADD":
        return False, "Invalid format", None
        
    p1, p2, sig = parts[1], parts[2], parts[3]
    raw = f"{p1}-{p2}-{LICENSE_SECRET}"
    expected_sig = hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()[:4]
    
    if sig != expected_sig:
        return False, "Invalid signature", None
        
    if machine_id:
        clean_mid = machine_id.replace("MID-", "").replace("-", "").strip().upper()
        if p1 != clean_mid[:4].ljust(4, "0"):
            return False, f"Machine ID Mismatch: Key is locked to machine prefix {p1}, but current machine is {clean_mid[:4]}.", None
            
    days = 0 if p2 == "LIFE" else int(p2[1:]) if (p2.startswith("D") and p2[1:].isdigit()) else 0
    return True, "Valid signed key", {
        "days": days,
        "is_lifetime": (p2 == "LIFE" or days == 0),
        "machine_prefix": p1
    }

def create_license(days=None, tier="VIP", max_accounts=50, note="", custom_key=None, bound_device=None):
    init_db()
    conn = get_connection()
    if custom_key:
        key_code = custom_key.strip().upper()
    elif bound_device:
        # Use signed key formula so it verifies anywhere without DB sync issues
        key_code = generate_signed_key(bound_device, days)
    else:
        key_code = _format_random_key()

    now_dt = get_now_utc()
    now_str = now_dt.isoformat()
    expires_str = (now_dt + timedelta(days=days)).isoformat() if (days is not None and days > 0) else None

    with conn:
        replaced_keys = []
        if bound_device:
            norm_device = bound_device.strip().upper()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT key_code FROM licenses WHERE (bound_device = ? OR note LIKE ?) AND is_active = 1 AND key_code NOT LIKE 'TGADD-VIP-%' AND key_code != ?",
                (norm_device, f"%{norm_device}%", key_code)
            )
            rows = cursor.fetchall()
            replaced_keys = [r[0] for r in rows]
            if replaced_keys:
                conn.execute(
                    "UPDATE licenses SET is_active = 0 WHERE (bound_device = ? OR note LIKE ?) AND key_code NOT LIKE 'TGADD-VIP-%' AND key_code != ?",
                    (norm_device, f"%{norm_device}%", key_code)
                )

        conn.execute(
            """INSERT OR REPLACE INTO licenses (key_code, tier, max_accounts, is_active, created_at, expires_at, bound_device, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (key_code, tier, max_accounts, 1, now_str, expires_str, bound_device, note)
        )
    conn.close()
    return {
        "key_code": key_code,
        "tier": tier,
        "max_accounts": max_accounts,
        "is_active": True,
        "created_at": now_str,
        "expires_at": expires_str if expires_str else "Lifetime",
        "bound_device": bound_device,
        "replaced_keys": replaced_keys,
        "note": note
    }

REVOKED_KEYS_FILE = DATA_DIR / "revoked_keys.json"

def _migrate_revoked_file_to_db(conn):
    """One-way import of the legacy JSON blacklist into the SQLite table."""
    legacy = set()
    try:
        if REVOKED_KEYS_FILE.exists():
            with open(REVOKED_KEYS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    legacy = {str(k).upper().strip() for k in data if k}
    except Exception:
        legacy = set()

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT key_code FROM revoked_keys")
        existing = {r[0].upper() for r in cursor.fetchall()}
    except Exception:
        existing = set()

    missing = legacy - existing
    if missing:
        now = get_now_utc().isoformat()
        conn.executemany(
            "INSERT OR IGNORE INTO revoked_keys (key_code, revoked_at) VALUES (?, ?)",
            [(k, now) for k in sorted(missing)],
        )
    return missing

def _db_revoked_keys(conn) -> set:
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT key_code FROM revoked_keys")
        return {r[0].upper().strip() for r in cursor.fetchall()}
    except Exception:
        return set()

def _read_revoked_file() -> set:
    try:
        if REVOKED_KEYS_FILE.exists():
            with open(REVOKED_KEYS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(str(k).upper().strip() for k in data if k)
    except Exception:
        # Truncated/corrupt file (e.g. a 0-byte write) — treat as empty.
        pass
    return set()

def _write_revoked_file(keys: set):
    """Atomic write so a crash mid-write cannot truncate the blacklist."""
    tmp = REVOKED_KEYS_FILE.with_suffix(".json.tmp")
    try:
        REVOKED_KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(sorted(list(keys)), f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, REVOKED_KEYS_FILE)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass

def _is_local_api_base() -> bool:
    """
    True when this process IS the central server and must not call itself
    over HTTP (Render backend, or an explicitly blanked LICENSE_API_BASE).
    """
    base = (LICENSE_API_BASE or "").strip().lower()
    if not base:
        return True
    # Render sets these automatically; the backend there owns the DB directly.
    if os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_ID"):
        return True
    return False

def fetch_central_revoked_keys() -> set:
    """Fetch the authoritative revoked-key list from the Render backend."""
    if _is_local_api_base():
        return set()
    try:
        import httpx
        resp = httpx.get(
            f"{LICENSE_API_BASE}/api/license/admin/revoked",
            headers={"X-Admin-Key": ADMIN_MASTER_KEY},
            timeout=REVOKED_SYNC_TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            raw = data.get("revoked", []) if isinstance(data, dict) else []
            return set(str(k).upper().strip() for k in raw if k)
    except Exception:
        pass
    return set()

def sync_revoked_from_central(force: bool = False) -> set:
    """
    Merge the central revoked list into the local one.

    Returns the merged local set. Falls back to the local file when the
    central server is unreachable, so verification never hard-fails offline.
    """
    global _revoked_sync_inflight

    local = _read_revoked_file()

    if _is_local_api_base():
        _revoked_sync_cache["keys"] = local
        _revoked_sync_cache["ts"] = time.time()
        return local

    with _revoked_sync_lock:
        now = time.time()
        cached = _revoked_sync_cache.get("keys")
        if not force and cached is not None and (now - _revoked_sync_cache.get("ts", 0)) < REVOKED_SYNC_TTL:
            return local | cached

        if _revoked_sync_inflight:
            return local | (cached or set())

        _revoked_sync_inflight = True
        try:
            remote = fetch_central_revoked_keys()
            if remote:
                local = local | remote
                _write_revoked_file(local)
            _revoked_sync_cache["keys"] = remote
            _revoked_sync_cache["ts"] = now
            _revoked_sync_cache["failed"] = not remote
        finally:
            _revoked_sync_inflight = False

    return local

def get_revoked_keys() -> set:
    """Revoked set from the SQLite table, merged with the central list when possible."""
    local = _read_revoked_db_keys()
    if _is_local_api_base():
        return local
    try:
        return sync_revoked_from_central() | local
    except Exception:
        return local

def _read_revoked_db_keys() -> set:
    """Read the revoked list from SQLite (persistent) plus the legacy file."""
    local = _read_revoked_file()
    try:
        conn = get_connection()
        try:
            local |= _db_revoked_keys(conn)
        finally:
            conn.close()
    except Exception:
        pass
    return local

def _invalidate_sync_cache():
    _revoked_sync_cache["ts"] = 0.0
    _revoked_sync_cache["keys"] = None

def save_revoked_key(key_code: str):
    if not key_code:
        return
    clean = str(key_code).upper().strip()
    revoked = _read_revoked_file()
    revoked.add(clean)
    _write_revoked_file(revoked)
    try:
        conn = get_connection()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO revoked_keys (key_code, revoked_at) VALUES (?, ?)",
                (clean, get_now_utc().isoformat()),
            )
        conn.close()
    except Exception:
        pass
    _invalidate_sync_cache()
    # Push to the central server so every hosted instance sees it.
    push_revocation_to_central(clean)

def unrevoke_key(key_code: str):
    if not key_code:
        return
    clean = str(key_code).upper().strip()
    revoked = _read_revoked_file()
    revoked.discard(clean)
    _write_revoked_file(revoked)
    try:
        conn = get_connection()
        with conn:
            conn.execute("DELETE FROM revoked_keys WHERE key_code = ?", (clean,))
        conn.close()
    except Exception:
        pass
    _invalidate_sync_cache()
    # Push the re-activation to the central server as well.
    push_revocation_to_central(clean, revoke=False)

def push_revocation_to_central(key_code: str, revoke: bool = True):
    """
    Tell the Render backend to revoke (or reactivate) a key.
    Fire-and-forget: failures leave the local state intact and are retried
    on the next verification sync.
    """
    if _is_local_api_base() or not key_code or not _push_enabled:
        return
    try:
        import httpx
        httpx.post(
            f"{LICENSE_API_BASE}/api/license/admin/revoke",
            headers={
                "Content-Type": "application/json",
                "X-Admin-Key": ADMIN_MASTER_KEY,
            },
            json={"key_code": key_code, "revoke": revoke, "admin_key": ADMIN_MASTER_KEY},
            timeout=REVOKED_SYNC_TIMEOUT,
        )
    except Exception:
        pass

def push_local_revocations_to_central():
    """
    Push every locally-revoked key to the central server. Used at bot startup
    so revocations made before the sync feature existed also propagate.
    """
    if _is_local_api_base():
        return 0
    keys = sorted(_read_revoked_file())
    if not keys:
        return 0
    try:
        import httpx
        httpx.post(
            f"{LICENSE_API_BASE}/api/license/admin/revoke-bulk",
            headers={
                "Content-Type": "application/json",
                "X-Admin-Key": ADMIN_MASTER_KEY,
            },
            json={"keys": keys, "revoke": True, "admin_key": ADMIN_MASTER_KEY},
            timeout=max(REVOKED_SYNC_TIMEOUT * 2, 8),
        )
    except Exception:
        pass
    return len(keys)

def _authoritative_server_base() -> str:
    """
    The live site whose license verdict is authoritative.

    Vercel is the primary hosted deployment (always up, always serves the
    dashboard), so it is checked first. Render is the fallback when configured.
    """
    candidates = []
    vercel_url = os.environ.get("VERCEL_LICENSE_URL", "").strip().rstrip("/")
    if vercel_url:
        candidates.append(vercel_url)
    if LICENSE_API_BASE and not _is_local_api_base():
        candidates.append(LICENSE_API_BASE.rstrip("/"))
    return candidates[0] if candidates else ""

def check_key_on_authoritative_server(key_code: str, machine_id: str = None) -> bool:
    """
    Ask the live hosted site whether this key is still active.

    The bot's local DB is NOT authoritative: the hosted site may have already
    auto-seeded the key, so a locally-revoked key can still verify there. This
    consults the live site's own verdict so revocations stick even when the
    central push failed. Runs concurrently and never blocks on a slow server.
    """
    base = _authoritative_server_base()
    if not base or not key_code:
        return True

    result = {"active": True}

    def _probe():
        try:
            import httpx
            headers = {"X-License-Key": key_code, "X-Machine-Id": machine_id or ""}
            resp = httpx.get(f"{base}/api/license/status", headers=headers, timeout=REVOKED_SYNC_TIMEOUT)
            if resp.status_code == 200 and isinstance(resp.json(), dict):
                result["active"] = bool(resp.json().get("is_active"))
        except Exception:
            pass

    worker = threading.Thread(target=_probe, daemon=True)
    worker.start()
    worker.join(timeout=max(REVOKED_SYNC_TIMEOUT + 1, 4))
    return result["active"]

def verify_license(key_code: str, machine_id: str = None, bind_if_unbound: bool = False):
    if not key_code:
        return False, "License key is missing or empty.", None
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    clean_key = key_code.strip().upper()
    clean_machine = machine_id.strip().upper() if machine_id else None

    # Check revoked blacklist FIRST (prevents revoked signed keys from auto-reactivating!).
    # Merge the central (Render) list so a key revoked in the Telegram bot is
    # honoured here too. Cached by TTL; falls back to the local DB offline.
    try:
        revoked_set = sync_revoked_from_central() | _read_revoked_db_keys()
    except Exception:
        revoked_set = _read_revoked_db_keys()
    if clean_key in revoked_set:
        conn.close()
        return False, "This license key has been deactivated or revoked by Admin @kun_amra.", None

    cursor.execute("SELECT * FROM licenses WHERE key_code = ?", (clean_key,))
    row = cursor.fetchone()

    # If key is NOT in database, try verifying as a mathematically signed key!
    if not row:
        valid_signed, signed_msg, signed_info = verify_signed_key(clean_key, clean_machine)
        if valid_signed and signed_info:
            now_dt = get_now_utc()
            now_str = now_dt.isoformat()
            days = signed_info.get("days", 0)
            expires_str = (now_dt + timedelta(days=days)).isoformat() if days > 0 else None
            tier = "VIP" if days == 0 else "PRO" if days >= 30 else "Basic (Trial)"
            max_accounts = 100 if days == 0 else 50 if days >= 30 else 25

            # Save to local database automatically
            with conn:
                conn.execute(
                    """INSERT OR REPLACE INTO licenses (key_code, tier, max_accounts, is_active, created_at, expires_at, bound_device, note)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (clean_key, tier, max_accounts, 1, now_str, expires_str, clean_machine, "Auto-verified signed key")
                )
            # Authoritative check: the hosted site may have revoked this key
            # even though it verifies mathematically here.
            if not check_key_on_authoritative_server(clean_key, clean_machine):
                conn.execute("UPDATE licenses SET is_active = 0 WHERE key_code = ?", (clean_key,))
                conn.close()
                return False, "This license key has been deactivated or revoked by Admin @kun_amra.", None
            conn.close()
            return True, "License key is valid and active.", {
                "key_code": clean_key,
                "tier": tier,
                "max_accounts": max_accounts,
                "is_active": True,
                "created_at": now_str,
                "expires_at": expires_str or "Lifetime",
                "bound_device": clean_machine,
                "note": "Auto-verified signed key"
            }
        else:
            conn.close()
            error_reason = signed_msg if "Mismatch" in (signed_msg or "") else "Invalid license key. Please check your key or contact admin @kun_amra."
            return False, error_reason, None

    if not row["is_active"]:
        conn.close()
        return False, "This license key has been deactivated or revoked.", None

    if row["expires_at"]:
        try:
            expires_dt = datetime.fromisoformat(row["expires_at"])
            if get_now_utc() > expires_dt:
                conn.close()
                return False, f"License expired on {expires_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}.", None
        except Exception:
            pass

    # Machine ID Hardware Lock Check
    is_vip_key = row["key_code"].upper().startswith("TGADD-VIP-")
    bound_device = (row["bound_device"] or "").strip().upper()
    client_machine = (machine_id or "").strip().upper() if machine_id else None

    if is_vip_key:
        # VIP/master keys are NEVER bound to a machine - they work on any machine
        # Clear any accidental binding that may have been set
        if bound_device:
            with conn:
                conn.execute("UPDATE licenses SET bound_device = NULL WHERE key_code = ?", (row["key_code"],))
            bound_device = ""
    elif bound_device:
        if client_machine and bound_device != client_machine:
            conn.close()
            return False, f"Machine ID Mismatch: This license key is locked to another machine ({bound_device}). It cannot be used on this machine ({client_machine})!", None
    elif client_machine and bind_if_unbound:
        # First time activation: lock this key to the current machine ID
        with conn:
            conn.execute("UPDATE licenses SET bound_device = ? WHERE key_code = ?", (client_machine, row["key_code"]))
        bound_device = client_machine

    conn.close()

    # Authoritative check: a key revoked in the Telegram bot must not keep
    # working here just because this instance auto-seeded it into its own DB.
    if not check_key_on_authoritative_server(clean_key, clean_machine):
        with conn:
            conn.execute("UPDATE licenses SET is_active = 0 WHERE key_code = ?", (clean_key,))
        conn.close()
        return False, "This license key has been deactivated or revoked by Admin @kun_amra.", None

    details = {
        "key_code": row["key_code"],
        "tier": row["tier"],
        "max_accounts": row["max_accounts"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "expires_at": row["expires_at"] or "Lifetime",
        "bound_device": bound_device,
        "note": row["note"] or ""
    }
    return True, "License key is valid and active.", details

def list_licenses():
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM licenses ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def revoke_license(key_code: str):
    init_db()
    clean = key_code.strip().upper()
    save_revoked_key(clean)
    conn = get_connection()
    with conn:
        conn.execute("UPDATE licenses SET is_active = 0 WHERE key_code = ?", (clean,))
    conn.close()
    return True

def delete_license(key_code: str):
    init_db()
    clean = key_code.strip().upper()
    save_revoked_key(clean)
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM licenses WHERE key_code = ?", (clean,))
    conn.close()
    return True

def delete_all_licenses():
    """Permanently delete all non-VIP licenses and add to blacklist."""
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key_code FROM licenses WHERE key_code NOT LIKE 'TGADD-VIP-%'")
    rows = cursor.fetchall()
    keys = [r["key_code"] for r in rows]
    deleted_count = len(keys)

    # Write the whole blacklist locally in one pass, then push once per key.
    revoked = _read_revoked_file()
    revoked |= {str(k).upper().strip() for k in keys}
    _write_revoked_file(revoked)

    with conn:
        conn.execute("DELETE FROM licenses WHERE key_code NOT LIKE 'TGADD-VIP-%'")
    conn.close()

    for k in keys:
        push_revocation_to_central(k, revoke=True)

    return deleted_count

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Telegram Adder License Management CLI")
    parser.add_argument("--generate", action="store_true", help="Generate a new license key")
    parser.add_argument("--days", type=int, default=None, help="Duration in days (leave empty for lifetime)")
    parser.add_argument("--tier", type=str, default="VIP", help="License tier (e.g. VIP, PRO, Basic)")
    parser.add_argument("--max-accounts", type=int, default=50, help="Max Telegram accounts allowed")
    parser.add_argument("--note", type=str, default="", help="Note or customer name")
    parser.add_argument("--custom-key", type=str, default=None, help="Custom key string")
    parser.add_argument("--list", action="store_true", help="List all license keys")
    parser.add_argument("--revoked", action="store_true", help="List revoked keys (merged with central server)")
    parser.add_argument("--sync", action="store_true", help="Force-sync revoked list from the central server")
    parser.add_argument("--verify", type=str, default=None, help="Verify a license key")
    parser.add_argument("--revoke", type=str, default=None, help="Revoke a license key")
    parser.add_argument("--unrevoke", type=str, default=None, help="Re-activate a revoked license key")

    args = parser.parse_args()

    init_db()

    if args.sync:
        merged = sync_revoked_from_central(force=True)
        print(f"\nSynced revoked keys from {LICENSE_API_BASE or '(local)'}: {len(merged)} key(s)")
        for k in sorted(merged):
            print(f"  - {k}")
        print()
    elif args.revoked:
        merged = get_revoked_keys()
        print(f"\nRevoked keys: {len(merged)}")
        for k in sorted(merged):
            print(f"  - {k}")
        print()
    elif args.unrevoke:
        unrevoke_key(args.unrevoke)
        print(f"License key {args.unrevoke} re-activated (and pushed to central server).")
    elif args.generate:
        lic = create_license(days=args.days, tier=args.tier, max_accounts=args.max_accounts, note=args.note, custom_key=args.custom_key)
        print("\n=== NEW LICENSE GENERATED ===")
        print(f"Key Code     : {lic['key_code']}")
        print(f"Tier         : {lic['tier']}")
        print(f"Max Accounts : {lic['max_accounts']}")
        print(f"Expires At   : {lic['expires_at']}")
        print(f"Note         : {lic['note']}")
        print("==============================\n")
    elif args.list:
        keys = list_licenses()
        print(f"\nTotal licenses in database: {len(keys)}")
        print("-" * 75)
        for k in keys:
            status = "ACTIVE" if k["is_active"] else "REVOKED"
            exp = k["expires_at"] or "Lifetime"
            print(f"[{status}] {k['key_code']} | Tier: {k['tier']} | Max: {k['max_accounts']} | Expires: {exp} | {k.get('note', '')}")
        print("-" * 75 + "\n")
    elif args.verify:
        valid, msg, det = verify_license(args.verify)
        print(f"Status: {'VALID' if valid else 'INVALID'}")
        print(f"Message: {msg}")
        if det:
            print(f"Details: {det}")
    elif args.revoke:
        revoke_license(args.revoke)
        print(f"License key {args.revoke} revoked.")
    else:
        parser.print_help()
