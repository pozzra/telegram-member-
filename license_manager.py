import sqlite3
import os
import secrets
import string
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil

# In Vercel serverless environment, local repo files are read-only. We use /tmp
IS_VERCEL = bool(os.environ.get("VERCEL"))
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path("/tmp/data") if IS_VERCEL else (BASE_DIR / "data")
DB_PATH = DATA_DIR / "licenses.db"

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

def create_license(days=None, tier="VIP", max_accounts=50, note="", custom_key=None, bound_device=None):
    init_db()
    conn = get_connection()
    key_code = custom_key.strip().upper() if custom_key else _format_random_key()
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
            """INSERT INTO licenses (key_code, tier, max_accounts, is_active, created_at, expires_at, bound_device, note)
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

def verify_license(key_code: str, machine_id: str = None, bind_if_unbound: bool = False):
    if not key_code:
        return False, "License key is missing or empty.", None
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM licenses WHERE key_code = ?", (key_code.strip().upper(),))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return False, "Invalid license key. Please check your key or contact admin @kun_amra.", None

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
    conn = get_connection()
    with conn:
        conn.execute("UPDATE licenses SET is_active = 0 WHERE key_code = ?", (key_code.strip(),))
    conn.close()
    return True

def delete_license(key_code: str):
    init_db()
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM licenses WHERE key_code = ?", (key_code.strip(),))
    conn.close()
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Telegram Adder License Management CLI")
    parser.add_argument("--generate", action="store_true", help="Generate a new license key")
    parser.add_argument("--days", type=int, default=None, help="Duration in days (leave empty for lifetime)")
    parser.add_argument("--tier", type=str, default="VIP", help="License tier (e.g. VIP, PRO, Basic)")
    parser.add_argument("--max-accounts", type=int, default=50, help="Max Telegram accounts allowed")
    parser.add_argument("--note", type=str, default="", help="Note or customer name")
    parser.add_argument("--custom-key", type=str, default=None, help="Custom key string")
    parser.add_argument("--list", action="store_true", help="List all license keys")
    parser.add_argument("--verify", type=str, default=None, help="Verify a license key")
    parser.add_argument("--revoke", type=str, default=None, help="Revoke a license key")

    args = parser.parse_args()

    init_db()

    if args.generate:
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
