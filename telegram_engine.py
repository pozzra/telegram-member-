import os
import json
import asyncio
import logging
import re
import threading
import time
import shutil
import io
import base64
import secrets
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

import qrcode
from telethon import TelegramClient
from telethon.errors import (
    ApiIdInvalidError,
    AuthKeyInvalidError,
    AuthKeyUnregisteredError,
    AuthRestartError,
    ChatAdminRequiredError,
    FloodWaitError,
    InputUserDeactivatedError,
    PasswordHashInvalidError,
    PeerFloodError,
    PhoneCodeEmptyError,
    PhoneCodeExpiredError,
    PhoneCodeHashEmptyError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    PhoneNumberUnoccupiedError,
    SendCodeUnavailableError,
    SessionExpiredError,
    SessionPasswordNeededError,
    UserAlreadyParticipantError,
    UserBannedInChannelError,
    UserChannelsTooMuchError,
    UserKickedError,
    UserNotMutualContactError,
    UserPrivacyRestrictedError,
    UserNotParticipantError,
)
from telethon.tl.functions.channels import GetParticipantRequest, InviteToChannelRequest, JoinChannelRequest
from telethon.tl.functions.messages import CheckChatInviteRequest, ImportChatInviteRequest
from telethon.tl.functions.contacts import ResolvePhoneRequest
from telethon.tl import types as tl_types

logger = logging.getLogger("telegram_engine")

# Default country code used when a phone number is entered in local format.
DEFAULT_COUNTRY_CODE = re.sub(r"\D", "", os.environ.get("DEFAULT_COUNTRY_CODE", "855")) or "855"
DEFAULT_API_ID = int(os.environ.get("TELEGRAM_API_ID", "2040") or 2040)
DEFAULT_API_HASH = os.environ.get("TELEGRAM_API_HASH", "b18441a1ff607e10a989891a5462e627")

IS_VERCEL = bool(os.environ.get("VERCEL"))
BASE_DIR = Path(__file__).resolve().parent

if IS_VERCEL:
    DATA_DIR = Path("/tmp/data")
    SESSIONS_DIR = Path("/tmp/sessions")
else:
    DATA_DIR = BASE_DIR / "data"
    SESSIONS_DIR = BASE_DIR / "sessions"

ACCOUNTS_FILE = DATA_DIR / "accounts.json"
PENDING_LOGINS_FILE = DATA_DIR / "pending_logins.json"

try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    bundled_accounts = BASE_DIR / "data" / "accounts.json"
    if IS_VERCEL and not ACCOUNTS_FILE.exists() and bundled_accounts.exists():
        try:
            shutil.copy2(bundled_accounts, ACCOUNTS_FILE)
        except Exception:
            pass
except Exception:
    pass

# Pending OTP logins. The client object itself only lives in this process, but
# the important fields (phone_code_hash, api credentials) are also persisted to
# disk so a server restart or a second worker does not lose the login flow.
PENDING_LOGINS: Dict[str, Dict[str, Any]] = {}
_PENDING_LOGINS_LOCK = threading.RLock()
_LOGIN_LOCKS: Dict[str, asyncio.Lock] = {}

# Temporary in-memory pending QR login sessions
PENDING_QR_LOGINS: Dict[str, Dict[str, Any]] = {}

# A Telegram login code is normally valid for a few minutes. Keep the pending
# state a little longer so a slightly delayed code can still be submitted.
PENDING_LOGIN_TTL_SECONDS = 20 * 60


def _get_login_lock(phone: str) -> asyncio.Lock:
    lock = _LOGIN_LOCKS.get(phone)
    if lock is None:
        lock = asyncio.Lock()
        _LOGIN_LOCKS[phone] = lock
    return lock


def _serializable_pending_logins() -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for phone, entry in PENDING_LOGINS.items():
        result[phone] = {k: v for k, v in entry.items() if k != "client"}
    return result


def save_pending_logins() -> None:
    """Persist non-client login state so it survives a web server restart."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp_file = PENDING_LOGINS_FILE.with_suffix(".json.tmp")
        with _PENDING_LOGINS_LOCK:
            with open(tmp_file, "w", encoding="utf-8") as fh:
                json.dump(_serializable_pending_logins(), fh, indent=2, ensure_ascii=False)
            os.replace(tmp_file, PENDING_LOGINS_FILE)
    except Exception:
        logger.exception("Could not persist pending Telegram login state")


def load_pending_logins() -> None:
    """Load pending login state saved by a previous process (best effort)."""
    if not PENDING_LOGINS_FILE.exists():
        return
    try:
        with open(PENDING_LOGINS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return
        now = time.time()
        with _PENDING_LOGINS_LOCK:
            for phone, entry in data.items():
                if not isinstance(entry, dict):
                    continue
                created_at = float(entry.get("created_at") or 0)
                if created_at and (now - created_at) > PENDING_LOGIN_TTL_SECONDS:
                    continue
                entry["phone"] = phone
                PENDING_LOGINS.setdefault(phone, entry)
    except Exception:
        logger.exception("Could not load pending Telegram login state")


load_pending_logins()


async def _disconnect_client(client: Optional[TelegramClient]) -> None:
    if client is None:
        return
    try:
        if client.is_connected():
            await client.disconnect()
    except Exception:
        pass


async def _drop_pending_login(phone: str) -> None:
    entry = PENDING_LOGINS.pop(phone, None)
    if entry:
        await _disconnect_client(entry.get("client"))
        save_pending_logins()


def _code_delivery_text(sent_code: Any) -> str:
    """Return a human friendly description of how Telegram delivered the code."""
    delivery = getattr(sent_code, "type", None)
    if isinstance(delivery, (tl_types.auth.SentCodeTypeApp,)):
        return "Telegram sent the code to your Telegram app. Open Telegram and check the service chat from Telegram."
    if isinstance(delivery, tl_types.auth.SentCodeTypeSms):
        return "Telegram sent the code by SMS."
    if isinstance(delivery, tl_types.auth.SentCodeTypeCall):
        return "Telegram will call your phone with the code."
    if isinstance(delivery, (tl_types.auth.SentCodeTypeFlashCall, tl_types.auth.SentCodeTypeMissedCall)):
        return "Telegram will call your phone. Check the incoming call for the code."
    if isinstance(delivery, tl_types.auth.SentCodeTypeEmailCode):
        return "Telegram wants to send the code to your login email. Check your email inbox (and spam folder)."
    if isinstance(delivery, tl_types.auth.SentCodeTypeSetUpEmailRequired):
        return "Telegram requires a login email for this account. Add/verify an email in Telegram, or use QR login."
    if isinstance(delivery, tl_types.auth.SentCodeTypeFragmentSms):
        return "Telegram sent the code via Fragment SMS."
    if isinstance(delivery, tl_types.auth.SentCodeTypeFirebaseSms):
        return "Telegram sent the code by SMS."
    return "Telegram sent the login code. Check your Telegram app and SMS messages."

def generate_qr_base64(data: str) -> str:
    """Generate high-contrast QR code image as Base64 string."""
    qr = qrcode.QRCode(box_size=7, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")

# Active Adding Job state
CURRENT_JOB: Dict[str, Any] = {
    "is_running": False,
    "should_stop": False,
    "progress": 0,
    "status_message": "Ready",
    "added_count": 0,
    "skipped_count": 0,
    "total_count": 0,
    "logs": [],
    "worker_breakdown": {},
}


def normalize_phone(raw_phone: str) -> str:
    """Normalize a phone number to international +digits format.

    The dashboard is primarily used with Cambodian numbers, so a local number
    such as 017271771 becomes +85517271771. Numbers that already include a
    country code are kept as-is. Users can always enter +<country><number> to
    avoid any guessing.
    """
    if raw_phone is None:
        return ""
    cleaned = re.sub(r"[^\d+]", "", str(raw_phone).strip())
    if not cleaned:
        return ""

    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    elif not cleaned.startswith("+"):
        digits = re.sub(r"\D", "", cleaned)
        if digits.startswith("0"):
            # Local format (e.g. 017271771) -> +85517271771
            cleaned = "+" + DEFAULT_COUNTRY_CODE + digits[1:]
        elif digits.startswith(DEFAULT_COUNTRY_CODE) and len(digits) > len(DEFAULT_COUNTRY_CODE) + 5:
            # Country code entered without the leading + (e.g. 85517271771)
            cleaned = "+" + digits
        elif len(digits) <= 10:
            # Short local number without a leading zero (e.g. 17271771)
            cleaned = "+" + DEFAULT_COUNTRY_CODE + digits
        else:
            cleaned = "+" + digits

    digits_only = re.sub(r"\D", "", cleaned)
    if len(digits_only) < 7 or len(digits_only) > 15:
        return ""
    return "+" + digits_only


def is_phone_number(text: str) -> bool:
    candidate = text.strip()
    return candidate.startswith("+") or (candidate.isdigit() and len(candidate) >= 7)


def get_accounts_file(machine_id: Optional[str] = None) -> Path:
    if machine_id and machine_id.strip():
        safe_mid = re.sub(r"[^\w]", "_", machine_id.strip().upper())
        return DATA_DIR / f"accounts_{safe_mid}.json"
    return ACCOUNTS_FILE


def get_session_path(phone: str, machine_id: Optional[str] = None) -> str:
    safe_phone = re.sub(r"[^\w]", "_", normalize_phone(phone))
    if machine_id and machine_id.strip():
        safe_mid = re.sub(r"[^\w]", "_", machine_id.strip().upper())
        user_sess_dir = SESSIONS_DIR / safe_mid
        user_sess_dir.mkdir(parents=True, exist_ok=True)
        return str(user_sess_dir / safe_phone)
    return str(SESSIONS_DIR / safe_phone)


def load_accounts(machine_id: Optional[str] = None) -> List[Dict[str, Any]]:
    acc_file = get_accounts_file(machine_id)
    if not acc_file.exists():
        return []
    try:
        with open(acc_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_accounts(accounts: List[Dict[str, Any]], machine_id: Optional[str] = None):
    acc_file = get_accounts_file(machine_id)
    with open(acc_file, "w", encoding="utf-8") as f:
        json.dump(accounts, f, indent=2, ensure_ascii=False)


def add_or_update_account(acc_data: Dict[str, Any], machine_id: Optional[str] = None):
    accounts = load_accounts(machine_id)
    norm = normalize_phone(acc_data.get("phone_number", ""))
    updated = False
    for i, a in enumerate(accounts):
        if normalize_phone(a.get("phone_number", "")) == norm:
            accounts[i] = acc_data
            updated = True
            break
    if not updated:
        accounts.append(acc_data)
    save_accounts(accounts, machine_id)
    return accounts


def delete_account(phone: str, machine_id: Optional[str] = None) -> bool:
    norm = normalize_phone(phone)
    accounts = load_accounts(machine_id)
    filtered = [a for a in accounts if normalize_phone(a.get("phone_number", "")) != norm]
    save_accounts(filtered, machine_id)
    # Remove session files
    sess_file = Path(get_session_path(norm, machine_id) + ".session")
    if sess_file.exists():
        try:
            sess_file.unlink()
        except Exception:
            pass
    return True


def toggle_account_status(phone: str, enabled: bool, machine_id: Optional[str] = None) -> bool:
    norm = normalize_phone(phone)
    accounts = load_accounts(machine_id)
    for a in accounts:
        if normalize_phone(a.get("phone_number", "")) == norm:
            a["enabled"] = enabled
            break
    save_accounts(accounts, machine_id)
    return True


def _format_wait(seconds: Any) -> str:
    try:
        seconds = int(seconds)
    except Exception:
        return "a few minutes"
    if seconds >= 3600:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"
    if seconds >= 60:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds}s"


def _extract_login_code(raw_code: str) -> str:
    """Extract a numeric Telegram code from a pasted message, if possible."""
    raw = (raw_code or "").strip()
    if not raw:
        return ""
    # Telegram Desktop/mobile messages look like:
    # "Login code: 12345. Do not give this code to anyone..."
    match = re.search(r"(?<!\d)(\d{4,7})(?!\d)", raw)
    if match:
        return match.group(1)
    # Codes typed with spaces or dashes, e.g. "1 2 3 4 5" or "123-45"
    compact = re.sub(r"\s+", "", raw)
    if re.fullmatch(r"[\d-]+", compact):
        return re.sub(r"\D", "", compact)
    # Some Telegram regions use a word/phrase code; pass it through unchanged.
    return compact


def _account_from_user(me: Any, api_id: int, api_hash: str, phone: str) -> Dict[str, Any]:
    return {
        "api_id": api_id,
        "api_hash": api_hash,
        "phone_number": phone,
        "user_id": me.id,
        "first_name": me.first_name or "",
        "last_name": me.last_name or "",
        "username": me.username or "",
        "is_premium": bool(getattr(me, "premium", False)),
        "enabled": True,
    }


async def request_telegram_code(phone: str, api_id: int, api_hash: str, machine_id: Optional[str] = None):
    norm = normalize_phone(phone)
    if not norm:
        return False, "Please enter a valid phone number with country code, e.g. +85517271771.", None
    try:
        api_id = int(api_id)
    except Exception:
        return False, "API ID must be a number. Get it from https://my.telegram.org/apps", None
    api_hash = (api_hash or "").strip()
    if not api_id or not api_hash:
        return False, "API ID and API Hash are required. Get them from https://my.telegram.org/apps", None

    async with _get_login_lock(norm):
        # If the user clicks "resend", close the previous pending client first.
        await _drop_pending_login(norm)

        client = TelegramClient(get_session_path(norm, machine_id), api_id, api_hash)
        try:
            await client.connect()

            if await client.is_user_authorized():
                me = await client.get_me()
                if me:
                    acc = _account_from_user(me, api_id, api_hash, norm)
                    add_or_update_account(acc, machine_id)
                    return True, "Account is already authorized and connected!", {
                        "already_authorized": True,
                        "account": acc,
                    }

            sent_code = await client.send_code_request(norm)
            phone_code_hash = getattr(sent_code, "phone_code_hash", "") or ""
            delivery = _code_delivery_text(sent_code)

            PENDING_LOGINS[norm] = {
                "phone": norm,
                "client": client,
                "phone_code_hash": phone_code_hash,
                "api_id": api_id,
                "api_hash": api_hash,
                "machine_id": machine_id,
                "created_at": time.time(),
                "needs_password": False,
                "delivery": delivery,
            }
            save_pending_logins()

            return True, f"{delivery} Phone: {norm}", {
                "phone": norm,
                "phone_code_hash": phone_code_hash,
                "needs_code": True,
                "delivery": delivery,
            }
        except ApiIdInvalidError:
            return False, "Invalid API ID / API Hash. Create your own app at https://my.telegram.org/apps and use those values.", None
        except PhoneNumberInvalidError:
            return False, "Telegram rejected that phone number. Enter the full international format, e.g. +85517271771.", None
        except PhoneNumberUnoccupiedError:
            return False, "This phone number does not have a Telegram account. Create a Telegram account first.", None
        except SendCodeUnavailableError:
            return False, "Telegram could not send the login code right now. Please wait a little and try again, or use QR login.", None
        except FloodWaitError as exc:
            return False, f"Telegram flood wait: please wait {_format_wait(getattr(exc, 'seconds', 0))} before requesting another code.", None
        except Exception as exc:
            logger.exception("Failed to request Telegram code for %s", norm)
            return False, f"Could not request the login code: {exc}", None
        finally:
            # The session file is enough to continue the login later. Keeping
            # the socket open caused stale clients and locks on Windows.
            await _disconnect_client(client)


async def verify_telegram_code(
    phone: str,
    code: str,
    password: Optional[str] = None,
    phone_code_hash: Optional[str] = None,
    api_id: Optional[int] = None,
    api_hash: Optional[str] = None,
    password_stage: bool = False,
    machine_id: Optional[str] = None,
):
    norm = normalize_phone(phone)
    if not norm:
        return False, "Invalid phone number. Please start again and enter the full international number.", None

    password = (password or "").strip()
    code_text = _extract_login_code(code)

    async with _get_login_lock(norm):
        pending = PENDING_LOGINS.get(norm)
        eff_machine_id = machine_id or (pending.get("machine_id") if pending else None)

        # A server restart or a second worker may lose the in-memory entry.
        # Rebuild it from the values the browser already received.
        if not pending and phone_code_hash and api_id and api_hash:
            try:
                pending = {
                    "phone": norm,
                    "phone_code_hash": phone_code_hash,
                    "api_id": int(api_id),
                    "api_hash": str(api_hash),
                    "machine_id": eff_machine_id,
                    "created_at": time.time(),
                    "needs_password": bool(password_stage),
                }
                PENDING_LOGINS[norm] = pending
                save_pending_logins()
            except Exception:
                pending = None

        if not pending:
            accounts = load_accounts(eff_machine_id)
            existing = next((a for a in accounts if normalize_phone(a.get("phone_number", "")) == norm), None)
            if existing:
                return True, "Account is already authorized.", {"account": existing}
            return False, "Login session expired. Click 'Resend Code' to request a new code.", {"can_resend": True}

        created_at = float(pending.get("created_at") or 0)
        if created_at and (time.time() - created_at) > PENDING_LOGIN_TTL_SECONDS:
            await _drop_pending_login(norm)
            return False, "Login session expired. Click 'Resend Code' to request a new code.", {"can_resend": True}

        try:
            pending_api_id = int(pending.get("api_id") or api_id or DEFAULT_API_ID)
            pending_api_hash = str(pending.get("api_hash") or api_hash or DEFAULT_API_HASH)
            needs_password = bool(pending.get("needs_password") or password_stage)

            client: TelegramClient = pending.get("client")
            if client is None:
                client = TelegramClient(get_session_path(norm, eff_machine_id), pending_api_id, pending_api_hash)
                pending["client"] = client
            if not client.is_connected():
                await client.connect()

            # Somebody may have completed the login from another request.
            me = await client.get_me()
            if me:
                account_entry = _account_from_user(me, pending_api_id, pending_api_hash, norm)
                add_or_update_account(account_entry, eff_machine_id)
                await _drop_pending_login(norm)
                return True, f"Successfully signed in as {me.first_name or ''} (@{me.username or me.id})!", {
                    "account": account_entry,
                }

            if needs_password or (not code_text and password):
                if not password:
                    pending["needs_password"] = True
                    save_pending_logins()
                    return True, "Two-step verification (2FA) is enabled on this account. Enter your Telegram cloud password.", {
                        "needs_password": True,
                        "phone": norm,
                    }
                try:
                    await client.sign_in(password=password)
                except PasswordHashInvalidError:
                    pending["needs_password"] = True
                    save_pending_logins()
                    return False, "Incorrect 2FA password. Please check your Telegram cloud password and try again.", {
                        "needs_password": True,
                    }
            else:
                if not code_text:
                    return False, "Please enter the login code Telegram sent you.", None

                hash_value = pending.get("phone_code_hash") or phone_code_hash or None
                try:
                    await client.sign_in(phone=norm, code=code_text, phone_code_hash=hash_value)
                except SessionPasswordNeededError:
                    pending["needs_password"] = True
                    save_pending_logins()
                    if not password:
                        return True, "Two-step verification (2FA) is enabled on this account. Enter your Telegram cloud password.", {
                            "needs_password": True,
                            "phone": norm,
                        }
                    try:
                        await client.sign_in(password=password)
                    except PasswordHashInvalidError:
                        return False, "Incorrect 2FA password. Please check your Telegram cloud password and try again.", {
                            "needs_password": True,
                        }
                except PhoneCodeInvalidError:
                    return False, "The login code is incorrect. Check the latest code from Telegram, or click 'Resend Code' to get a new one.", {
                        "can_resend": True,
                    }
                except PhoneCodeExpiredError:
                    await _drop_pending_login(norm)
                    return False, "The login code expired. Click 'Resend Code' to get a new one.", {"can_resend": True}
                except (PhoneCodeEmptyError, PhoneCodeHashEmptyError):
                    await _drop_pending_login(norm)
                    return False, "The login session expired. Click 'Resend Code' to get a new one.", {"can_resend": True}

            me = await client.get_me()
            if not me:
                return False, "Telegram did not return the account profile. Please click 'Resend Code' and try again.", {
                    "can_resend": True,
                }

            account_entry = _account_from_user(me, pending_api_id, pending_api_hash, norm)
            add_or_update_account(account_entry, eff_machine_id)
            await _drop_pending_login(norm)
            return True, f"Successfully signed in as {me.first_name or ''} (@{me.username or me.id})!", {
                "account": account_entry,
            }

        except PhoneNumberUnoccupiedError:
            await _drop_pending_login(norm)
            return False, "This phone number is not registered with Telegram. Create a Telegram account first.", None
        except ApiIdInvalidError:
            return False, "Invalid API ID / API Hash. Create your own app at https://my.telegram.org/apps.", None
        except (AuthKeyUnregisteredError, AuthKeyInvalidError, SessionExpiredError):
            await _drop_pending_login(norm)
            try:
                session_file = Path(get_session_path(norm) + ".session")
                if session_file.exists():
                    session_file.unlink()
            except Exception:
                pass
            return False, "The Telegram login session is no longer valid. Click 'Resend Code' and try again.", {
                "can_resend": True,
            }
        except FloodWaitError as exc:
            return False, f"Telegram flood wait: please wait {_format_wait(getattr(exc, 'seconds', 0))} before trying again.", None
        except Exception as exc:
            logger.exception("Telegram sign-in failed for %s", norm)
            return False, f"Sign in failed: {exc}", None
        finally:
            current = PENDING_LOGINS.get(norm)
            await _disconnect_client((current or pending).get("client"))


# ==========================================
# QR Code Auto-Login & Telegram Confirm
# ==========================================
def _remove_temp_session(entry: Dict[str, Any]) -> None:
    temp_session = entry.get("temp_session")
    if not temp_session:
        return
    try:
        session_file = Path(str(temp_session) + ".session")
        if session_file.exists():
            session_file.unlink()
    except Exception:
        pass


async def _prune_qr_logins(max_age_seconds: int = 180) -> None:
    """Close stale QR clients and remove their temporary SQLite session files."""
    now = time.time()
    for qr_id, entry in list(PENDING_QR_LOGINS.items()):
        created_at = float(entry.get("created_at") or 0)
        status = entry.get("status")
        too_old = created_at and (now - created_at) > max_age_seconds
        finished = status in ("expired", "error", "success") and created_at and (now - created_at) > 45
        if too_old or finished:
            PENDING_QR_LOGINS.pop(qr_id, None)
            await _disconnect_client(entry.get("client"))
            _remove_temp_session(entry)


def _move_qr_session(entry: Dict[str, Any], phone: str) -> None:
    """Move the temporary QR session to the permanent per-account session path."""
    temp_session = entry.get("temp_session")
    if not temp_session:
        return
    old_session = Path(str(temp_session) + ".session")
    mid = entry.get("machine_id")
    target_path = Path(get_session_path(phone, mid) + ".session")
    if not old_session.exists():
        return
    try:
        if target_path.exists():
            target_path.unlink()
        old_session.rename(target_path)
    except Exception:
        try:
            shutil.copy2(old_session, target_path)
            old_session.unlink()
        except Exception:
            logger.exception("Could not move QR session file to %s", target_path)


async def start_qr_login(api_id: int = DEFAULT_API_ID, api_hash: str = DEFAULT_API_HASH, machine_id: Optional[str] = None):
    try:
        api_id = int(api_id or DEFAULT_API_ID)
    except Exception:
        return False, "API ID must be a number.", None
    api_hash = (api_hash or DEFAULT_API_HASH).strip()

    await _prune_qr_logins()

    qr_id = secrets.token_hex(8)
    temp_session = SESSIONS_DIR / f"temp_qr_{qr_id}"
    client = TelegramClient(str(temp_session), api_id, api_hash)

    try:
        await client.connect()
        qr = await client.qr_login()
        b64 = generate_qr_base64(qr.url)
        entry = {
            "qr_id": qr_id,
            "client": client,
            "qr": qr,
            "api_id": api_id,
            "api_hash": api_hash,
            "machine_id": machine_id,
            "temp_session": temp_session,
            "status": "waiting",
            "url": qr.url,
            "qr_image": f"data:image/png;base64,{b64}",
            "expires_at": qr.expires.isoformat(),
            "created_at": time.time(),
            "error": None,
            "account": None,
        }
        PENDING_QR_LOGINS[qr_id] = entry
        asyncio.create_task(_watch_qr_login(qr_id))
        return True, "QR login initiated. Open Telegram on your phone and confirm the login.", {
            "qr_id": qr_id,
            "url": qr.url,
            "qr_image": f"data:image/png;base64,{b64}",
            "expires_at": qr.expires.isoformat(),
        }
    except ApiIdInvalidError:
        await _disconnect_client(client)
        _remove_temp_session({"temp_session": temp_session})
        return False, "Invalid API ID / API Hash. Create your own app at https://my.telegram.org/apps.", None
    except Exception as exc:
        await _disconnect_client(client)
        _remove_temp_session({"temp_session": temp_session})
        logger.exception("Failed to start QR login")
        return False, f"Failed to initiate QR login: {exc}", None


async def _watch_qr_login(qr_id: str):
    entry = PENDING_QR_LOGINS.get(qr_id)
    if not entry:
        return
    client: TelegramClient = entry["client"]
    qr = entry["qr"]

    try:
        user = await qr.wait()
        phone = normalize_phone(user.phone) if getattr(user, "phone", None) else f"+{user.id}"

        # Disconnect first so Windows releases the SQLite session file, then
        # move the temporary session into the permanent account slot.
        await _disconnect_client(client)
        _move_qr_session(entry, phone)
        entry["temp_session"] = None

        account_entry = _account_from_user(user, int(entry["api_id"]), entry["api_hash"], phone)
        add_or_update_account(account_entry, entry.get("machine_id"))

        entry["status"] = "success"
        entry["account"] = account_entry
        entry["phone"] = phone
    except SessionPasswordNeededError:
        entry["status"] = "needs_2fa"
        entry["error"] = "Two-Step Verification (2FA) is enabled on this account."
    except (asyncio.TimeoutError, TimeoutError):
        entry["status"] = "expired"
        entry["error"] = "QR code expired. Generating a new QR code..."
        await _disconnect_client(client)
        _remove_temp_session(entry)
        entry["temp_session"] = None
    except Exception as exc:
        entry["status"] = "error"
        entry["error"] = str(exc)
        await _disconnect_client(client)
        _remove_temp_session(entry)
        entry["temp_session"] = None
        logger.exception("QR login failed for %s", qr_id)


def get_qr_login_status(qr_id: str) -> Dict[str, Any]:
    entry = PENDING_QR_LOGINS.get(qr_id)
    if not entry:
        return {"status": "not_found", "error": "Session not found or expired."}
    return {
        "status": entry.get("status", "waiting"),
        "error": entry.get("error"),
        "account": entry.get("account"),
        "phone": entry.get("phone"),
        "expires_at": entry.get("expires_at"),
        "url": entry.get("url"),
    }


async def submit_qr_2fa(qr_id: str, password: str, machine_id: Optional[str] = None):
    entry = PENDING_QR_LOGINS.get(qr_id)
    if not entry:
        return False, "QR Login session expired or not found. Please refresh and try again.", None
    if entry["status"] != "needs_2fa":
        return False, f"Cannot submit 2FA: session is in {entry['status']} state.", None

    if machine_id:
        entry["machine_id"] = machine_id

    client: TelegramClient = entry["client"]
    try:
        await client.sign_in(password=(password or "").strip())
        me = await client.get_me()
        if not me:
            return False, "Telegram did not return the account profile. Please refresh the QR code and try again.", None

        phone = normalize_phone(me.phone) if getattr(me, "phone", None) else f"+{me.id}"
        await _disconnect_client(client)
        _move_qr_session(entry, phone)
        entry["temp_session"] = None

        account_entry = _account_from_user(me, int(entry["api_id"]), entry["api_hash"], phone)
        add_or_update_account(account_entry, entry.get("machine_id"))

        entry["status"] = "success"
        entry["account"] = account_entry
        entry["phone"] = phone
        return True, "Successfully signed in with 2FA password!", {"account": account_entry}
    except PasswordHashInvalidError:
        return False, "Incorrect 2FA password. Please check your Telegram cloud password.", {"needs_2fa": True}
    except Exception as exc:
        logger.exception("QR 2FA verification failed for %s", qr_id)
        return False, f"2FA verification failed: {exc}", None


async def cancel_qr_login(qr_id: str) -> bool:
    """Stop a QR login when the user closes the modal."""
    entry = PENDING_QR_LOGINS.pop(qr_id, None)
    if not entry:
        return False
    await _disconnect_client(entry.get("client"))
    _remove_temp_session(entry)
    return True


def parse_group_identifier(raw: str):
    """Normalize any format of group link or username into (type, identifier)."""
    raw = (raw or "").strip()
    # Invite link format (+ or joinchat/)
    m_inv = re.search(r'(?:t\.me|telegram\.me)/(?:\+|joinchat/)([a-zA-Z0-9_-]+)', raw)
    if m_inv:
        return 'invite', m_inv.group(1)
    if raw.startswith('+'):
        return 'invite', raw[1:].strip()

    # Public link format e.g. https://t.me/groupname or t.me/groupname/
    m_pub = re.search(r'(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/([a-zA-Z0-9_]{3,})/?', raw)
    if m_pub:
        return 'public', m_pub.group(1)

    clean = raw.lstrip('@').strip().rstrip('/')
    return 'public', clean


async def resolve_group_entity(client: TelegramClient, raw_input: str):
    """Resolve public username, group URL, or private invite link into a Telegram chat/channel entity."""
    kind, ident = parse_group_identifier(raw_input)
    if kind == 'invite':
        # Private invite link: try joining via ImportChatInviteRequest first
        try:
            updates = await client(ImportChatInviteRequest(hash=ident))
            if getattr(updates, 'chats', None):
                return updates.chats[0]
        except UserAlreadyParticipantError:
            pass
        except Exception:
            pass

        # If already joined or import didn't return chat, check invite details
        try:
            invite_info = await client(CheckChatInviteRequest(hash=ident))
            if getattr(invite_info, 'chat', None):
                return invite_info.chat
        except Exception:
            pass

        # Try get_entity with +
        try:
            return await client.get_entity(f"https://t.me/+{ident}")
        except Exception:
            pass

        # Search dialogs as fallback
        async for dialog in client.iter_dialogs(limit=100):
            if dialog.is_group or dialog.is_channel:
                return dialog.entity

        raise ValueError(f"Could not resolve private invite link: https://t.me/+{ident}")
    else:
        # Public group / username or ID
        if ident.isdigit() or (ident.startswith('-') and ident[1:].isdigit()):
            ident = int(ident)
        target = await client.get_entity(ident)
        try:
            await client(JoinChannelRequest(target))
        except Exception:
            pass
        return target


async def fetch_group_members(source_group_link: str, account_phone: Optional[str] = None, machine_id: Optional[str] = None):
    accounts = load_accounts(machine_id)
    active_accounts = [a for a in accounts if a.get("enabled", True)]
    if not active_accounts:
        return False, "No active Telegram accounts connected. Please add or enable an account first.", None

    chosen_acc = None
    if account_phone:
        norm = normalize_phone(account_phone)
        chosen_acc = next((a for a in active_accounts if normalize_phone(a.get("phone_number", "")) == norm), None)
    if not chosen_acc:
        chosen_acc = active_accounts[0]

    phone = chosen_acc["phone_number"]
    api_id = int(chosen_acc["api_id"])
    api_hash = chosen_acc["api_hash"]
    session_path = get_session_path(phone, machine_id)

    client = TelegramClient(session_path, api_id, api_hash)
    await client.connect()

    if not await client.is_user_authorized():
        await client.disconnect()
        return False, f"Account {phone} is not authorized. Please re-login.", None

    try:
        target = await resolve_group_entity(client, source_group_link)
    except Exception as exc:
        await client.disconnect()
        return False, f"Could not find or join group '{source_group_link}': {str(exc)}", None

    members = []
    seen = set()
    deleted_count = 0
    bot_count = 0
    scraped_from = "participants"

    # Strategy 1: Standard participants list (Fast, gets up to 5000 users)
    try:
        participants = await client.get_participants(target, limit=5000)
        for user in participants:
            first = getattr(user, "first_name", "") or ""
            last = getattr(user, "last_name", "") or ""
            full_name = f"{first} {last}".strip().casefold()

            if getattr(user, "deleted", False) or "deleted account" in full_name:
                deleted_count += 1
                continue
            if getattr(user, "bot", False):
                bot_count += 1
                continue
            if getattr(user, "is_self", False):
                continue

            identifier = None
            if getattr(user, "username", None):
                identifier = f"@{user.username}"
            elif getattr(user, "phone", None):
                identifier = f"+{user.phone}"
            else:
                identifier = str(user.id)

            key = identifier.casefold()
            if key not in seen:
                seen.add(key)
                members.append(identifier)
    except (ChatAdminRequiredError, Exception):
        # Admin hides members or restricted - fallback to Strategy 2!
        participants = []

    # Strategy 2: If participants list was hidden by Admin or empty, scrape from recent chat messages!
    if not members:
        scraped_from = "messages"
        try:
            async for msg in client.iter_messages(target, limit=1000):
                sender = getattr(msg, "sender", None)
                if not sender:
                    continue
                first = getattr(sender, "first_name", "") or ""
                last = getattr(sender, "last_name", "") or ""
                full_name = f"{first} {last}".strip().casefold()

                if getattr(sender, "deleted", False) or "deleted account" in full_name:
                    deleted_count += 1
                    continue
                if getattr(sender, "bot", False):
                    bot_count += 1
                    continue
                if getattr(sender, "is_self", False):
                    continue

                identifier = None
                if getattr(sender, "username", None):
                    identifier = f"@{sender.username}"
                elif getattr(sender, "phone", None):
                    identifier = f"+{sender.phone}"
                else:
                    identifier = str(sender.id)

                key = identifier.casefold()
                if key not in seen:
                    seen.add(key)
                    members.append(identifier)
        except Exception:
            pass

    await client.disconnect()

    if not members:
        return False, f"Could not find any members in {source_group_link}. The group might be completely private, empty, or a channel without chat history.", None

    notice_msg = f"Successfully scraped {len(members)} active members!"
    if scraped_from == "messages":
        notice_msg = f"Scraped {len(members)} active members from chat history (Admin hides full member list in this group)!"

    return True, notice_msg, {
        "members": members,
        "total": len(members),
        "deleted_count": deleted_count,
        "bot_count": bot_count,
        "source": source_group_link,
        "method": scraped_from
    }


def stop_adding_job():
    global CURRENT_JOB
    if CURRENT_JOB["is_running"]:
        CURRENT_JOB["should_stop"] = True
        return True
    return False


async def run_adding_flow(
    target_group_link: str,
    members: List[str],
    delay_seconds: float = 3.0,
    max_per_account: int = 30,
    log_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    machine_id: Optional[str] = None,
):
    global CURRENT_JOB

    CURRENT_JOB["is_running"] = True
    CURRENT_JOB["should_stop"] = False
    CURRENT_JOB["progress"] = 0
    CURRENT_JOB["status_message"] = "Starting adding members..."
    CURRENT_JOB["added_count"] = 0
    CURRENT_JOB["skipped_count"] = 0
    CURRENT_JOB["total_count"] = len(members)
    CURRENT_JOB["logs"] = []
    CURRENT_JOB["worker_breakdown"] = {}

    def log(msg: str, level: str = "info"):
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "msg": msg,
            "level": level,
        }
        CURRENT_JOB["logs"].append(entry)
        if len(CURRENT_JOB["logs"]) > 200:
            CURRENT_JOB["logs"].pop(0)
        if log_callback:
            try:
                log_callback({"type": "log", "data": entry, "job": CURRENT_JOB})
            except Exception:
                pass

    log(f"Initializing Telegram Adder for {len(members)} candidates -> {target_group_link}")

    accounts = load_accounts(machine_id)
    active_accounts = [a for a in accounts if a.get("enabled", True)]
    if not active_accounts:
        log("No enabled Telegram accounts found! Aborting.", "error")
        CURRENT_JOB["is_running"] = False
        CURRENT_JOB["status_message"] = "Error: No active accounts"
        return

    workers = []
    for acc in active_accounts:
        phone = acc["phone_number"]
        api_id = int(acc["api_id"])
        api_hash = acc["api_hash"]
        session_path = get_session_path(phone, machine_id)
        try:
            client = TelegramClient(session_path, api_id, api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                log(f"Account {phone} is not authorized; skipping.", "warning")
                await client.disconnect()
                continue

            me = await client.get_me()
            is_premium = bool(getattr(me, "premium", False))
            acc["is_premium"] = is_premium

            workers.append({
                "account": acc,
                "phone": phone,
                "client": client,
                "target_group": None,
                "invites_done": 0,
                "status": "ready",
                "is_premium": is_premium,
            })
            CURRENT_JOB["worker_breakdown"][phone] = {
                "invites_done": 0,
                "is_premium": is_premium,
                "status": "ready",
            }
        except Exception as exc:
            log(f"Failed to connect account {phone}: {exc}", "error")

    if not workers:
        log("No valid accounts could be connected. Aborting.", "error")
        CURRENT_JOB["is_running"] = False
        CURRENT_JOB["status_message"] = "No accounts ready"
        return

    log(f"Connected {len(workers)} accounts. Connecting to target group {target_group_link}...")

    # Join target group for each worker
    valid_workers = []
    for w in workers:
        try:
            target = await resolve_group_entity(w["client"], target_group_link)
            w["target_group"] = target
            valid_workers.append(w)
        except Exception as exc:
            log(f"Account {w['phone']} cannot access target group: {exc}", "warning")

    if not valid_workers:
        log("None of the accounts could access target group. Aborting.", "error")
        for w in workers:
            try:
                await w["client"].disconnect()
            except Exception:
                pass
        CURRENT_JOB["is_running"] = False
        CURRENT_JOB["status_message"] = "Target group inaccessible"
        return

    total_members = len(members)
    worker_idx = 0
    added_count = 0
    skipped_count = 0

    try:
        for idx, member in enumerate(members):
            if CURRENT_JOB["should_stop"]:
                log("Process stopped by user.", "warning")
                CURRENT_JOB["status_message"] = "Stopped by user"
                break

            # Available healthy workers:
            # Regular accounts: invites_done < max_per_account
            # Telegram Premium accounts: NO LIMIT (Unlimited invites)!
            available = [
                w for w in valid_workers
                if w["status"] == "ready" and (w.get("is_premium") or w["invites_done"] < max_per_account)
            ]

            if not available:
                log("All accounts reached invite limits or were restricted.", "warning")
                CURRENT_JOB["status_message"] = "All accounts limited"
                break

            # Round-robin rotation (ចែកគ្នាធ្វើការ មិនជាន់គ្នា)
            worker = available[worker_idx % len(available)]
            worker_idx += 1
            client = worker["client"]
            target_group = worker["target_group"]
            phone = worker["phone"]

            progress_val = int(((idx + 1) / total_members) * 100)
            CURRENT_JOB["progress"] = progress_val
            prem_tag = " ⭐ Premium" if worker.get("is_premium") else ""
            status_text = f"[{phone}{prem_tag}] Inviting {member} ({idx + 1}/{total_members})..."
            CURRENT_JOB["status_message"] = status_text

            if log_callback:
                try:
                    log_callback({
                        "type": "progress",
                        "progress": progress_val,
                        "current": idx + 1,
                        "total": total_members,
                        "added": added_count,
                        "skipped": skipped_count,
                        "status": status_text,
                    })
                except Exception:
                    pass

            # Resolve member
            try:
                if is_phone_number(member):
                    res = await client(ResolvePhoneRequest(phone=normalize_phone(member)))
                    users = [u for u in getattr(res, "users", []) if not getattr(u, "bot", False) and not getattr(u, "deleted", False)]
                    if not users:
                        skipped_count += 1
                        CURRENT_JOB["skipped_count"] = skipped_count
                        log(f"Phone {member} not found or restricted.", "warning")
                        continue
                    user = users[0]
                else:
                    user = await client.get_entity(member.strip())
            except Exception as exc:
                skipped_count += 1
                CURRENT_JOB["skipped_count"] = skipped_count
                log(f"Could not resolve {member}: {exc}", "warning")
                continue

            # Skip deleted accounts
            user_full = f"{getattr(user, 'first_name', '') or ''} {getattr(user, 'last_name', '') or ''}".strip().casefold()
            if getattr(user, "deleted", False) or "deleted account" in user_full:
                skipped_count += 1
                CURRENT_JOB["skipped_count"] = skipped_count
                log(f"{member} is a deleted account; skipping.", "warning")
                continue

            # Check if already participant
            try:
                await client(GetParticipantRequest(target_group, user.id))
                skipped_count += 1
                CURRENT_JOB["skipped_count"] = skipped_count
                log(f"{member} is already in the target group; skipping.", "info")
                continue
            except UserNotParticipantError:
                pass
            except Exception:
                pass

            # Invite user
            retries = 2
            while retries > 0:
                try:
                    await client(InviteToChannelRequest(target_group, [user]))
                    added_count += 1
                    worker["invites_done"] += 1
                    CURRENT_JOB["added_count"] = added_count
                    CURRENT_JOB["worker_breakdown"][phone]["invites_done"] = worker["invites_done"]
                    log(f"Successfully invited {member} via {phone}{prem_tag} (Total: {added_count})", "success")
                    await asyncio.sleep(delay_seconds)
                    break
                except PeerFloodError:
                    worker["status"] = "limited"
                    CURRENT_JOB["worker_breakdown"][phone]["status"] = "limited"
                    log(f"Account {phone} hit PeerFlood limit. Rotating to next account...", "warning")
                    # Try alternate account immediately
                    alt_available = [
                        w for w in valid_workers
                        if w["status"] == "ready" and (w.get("is_premium") or w["invites_done"] < max_per_account)
                    ]
                    if alt_available:
                        worker_idx += 1
                        alt = alt_available[worker_idx % len(alt_available)]
                        try:
                            await alt["client"](InviteToChannelRequest(alt["target_group"], [user]))
                            added_count += 1
                            alt["invites_done"] += 1
                            CURRENT_JOB["added_count"] = added_count
                            CURRENT_JOB["worker_breakdown"][alt["phone"]]["invites_done"] = alt["invites_done"]
                            log(f"Successfully invited {member} via failover {alt['phone']}", "success")
                            await asyncio.sleep(delay_seconds)
                        except Exception as e:
                            skipped_count += 1
                            CURRENT_JOB["skipped_count"] = skipped_count
                            log(f"Failover invite failed for {member}: {e}", "warning")
                    else:
                        skipped_count += 1
                        CURRENT_JOB["skipped_count"] = skipped_count
                    break
                except FloodWaitError as exc:
                    if exc.seconds <= 12:
                        log(f"Account {phone} flood wait: sleeping {exc.seconds}s...", "warning")
                        await asyncio.sleep(exc.seconds)
                        retries -= 1
                    else:
                        worker["status"] = "flood_wait"
                        CURRENT_JOB["worker_breakdown"][phone]["status"] = f"flood_wait ({exc.seconds}s)"
                        log(f"Account {phone} flood wait {exc.seconds}s. Switching worker.", "warning")
                        skipped_count += 1
                        CURRENT_JOB["skipped_count"] = skipped_count
                        break
                except UserAlreadyParticipantError:
                    skipped_count += 1
                    CURRENT_JOB["skipped_count"] = skipped_count
                    log(f"{member} is already a member.", "info")
                    break
                except (
                    UserPrivacyRestrictedError,
                    UserNotMutualContactError,
                    UserChannelsTooMuchError,
                    UserKickedError,
                    UserBannedInChannelError,
                    InputUserDeactivatedError,
                ) as exc:
                    skipped_count += 1
                    CURRENT_JOB["skipped_count"] = skipped_count
                    log(f"Cannot invite {member} (Privacy or restricted): {exc}", "warning")
                    break
                except ChatAdminRequiredError:
                    worker["status"] = "no_admin"
                    CURRENT_JOB["worker_breakdown"][phone]["status"] = "no_admin"
                    log(f"Account {phone} requires admin permission to invite.", "error")
                    skipped_count += 1
                    CURRENT_JOB["skipped_count"] = skipped_count
                    break
                except Exception as exc:
                    skipped_count += 1
                    CURRENT_JOB["skipped_count"] = skipped_count
                    log(f"Failed to invite {member}: {exc}", "error")
                    break

        CURRENT_JOB["progress"] = 100
        status_final = "Completed" if not CURRENT_JOB["should_stop"] else "Stopped"
        CURRENT_JOB["status_message"] = f"Finished! Total Added: {added_count}, Skipped: {skipped_count}"
        log(f"Adding finished! Added: {added_count}, Skipped/Failed: {skipped_count}", "success")

        if log_callback:
            try:
                log_callback({
                    "type": "finished",
                    "added": added_count,
                    "skipped": skipped_count,
                    "breakdown": CURRENT_JOB["worker_breakdown"],
                })
            except Exception:
                pass

    finally:
        for w in workers:
            try:
                await w["client"].disconnect()
            except Exception:
                pass
        CURRENT_JOB["is_running"] = False

