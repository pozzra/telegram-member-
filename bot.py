#!/usr/bin/env python3
"""
Telegram License Bot for Telegram Adder Web Pro
================================================
Admin: @kun_amra

HOW IT WORKS:
  1. User opens the web tool → copies their Machine ID (e.g. MID-A3F9C2B1-XK7Q2M)
  2. User DMs this bot and sends their Machine ID
  3. Bot forwards the request to admin (@kun_amra) with one-click license duration buttons
  4. Admin clicks the duration they want → bot generates a key and sends it to the user
  5. User pastes the key in the web tool → tool is activated

ADMIN INLINE BUTTONS:
  [⚡ 1 Day] [📅 3 Days] [🗓 7 Days] [📆 30 Days] [🏆 90 Days] [♾️ Lifetime] [❌ Reject]

ADMIN COMMANDS:
  /genkey <MachineID> <days>   — Manually generate & send a key (0 = lifetime)
  /listkeys                    — Show last 10 license keys
  /revoke <LicenseKey>         — Revoke a key
  /info                        — Bot status & stats
  /pending                     — Show all pending user requests

SETUP:
  1. Create a bot via @BotFather → copy the token
  2. Set BOT_TOKEN in .env or as environment variable
  3. Run: python bot.py
  4. Send /start to the bot AS ADMIN → bot registers your chat ID automatically
  5. Share the bot link with your users!
"""

import os
import sys
import json
import asyncio
import re
import time
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Fix Windows console UTF-8 output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import httpx
import socket

# ─── Single-Instance Process Lock ─────────────────────────
_bot_lock_socket = None

def acquire_single_instance_lock(port: int = 29876) -> bool:
    """Ensure only one bot instance runs on this machine to prevent duplicate messages."""
    global _bot_lock_socket
    try:
        _bot_lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _bot_lock_socket.bind(("127.0.0.1", port))
        _bot_lock_socket.listen(1)
        return True
    except socket.error:
        return False

# ─── Path setup ───────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

# Load .env if present
_env_file = ROOT_DIR / ".env"
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

import license_manager

# ─── Logging ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("LicenseBot")

# ─── Config ───────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_USERNAME = "kun_amra"

DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
BOT_DATA_FILE = DATA_DIR / "bot_data.json"

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ─── State ────────────────────────────────────────────────
# bot_data.json schema:
# {
#   "admin_chat_id": "123456789",
#   "pending": {
#     "MID-XXXX-YYYY": {
#       "user_chat_id": "987654321",
#       "user_name": "John",
#       "username": "johndoe",
#       "timestamp": 1700000000
#     }
#   }
# }

def load_bot_data() -> dict:
    if BOT_DATA_FILE.exists():
        try:
            return json.loads(BOT_DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"admin_chat_id": os.environ.get("ADMIN_CHAT_ID", "").strip(), "pending": {}}


def save_bot_data(data: dict):
    BOT_DATA_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


bot_state = load_bot_data()

# ─── Telegram API helpers ─────────────────────────────────
async def tg(client: httpx.AsyncClient, method: str, **params):
    """POST to Telegram Bot API."""
    try:
        resp = await client.post(f"{API_BASE}/{method}", json=params, timeout=20)
        return resp.json()
    except Exception as exc:
        log.error(f"tg.{method} error: {exc}")
        return {"ok": False, "description": str(exc)}


async def send(client, chat_id, text, markup=None, parse_mode="HTML"):
    kwargs = dict(chat_id=chat_id, text=text, parse_mode=parse_mode)
    if markup:
        kwargs["reply_markup"] = markup
    return await tg(client, "sendMessage", **kwargs)


async def edit(client, chat_id, msg_id, text, markup=None, parse_mode="HTML"):
    kwargs = dict(chat_id=chat_id, message_id=msg_id, text=text, parse_mode=parse_mode)
    if markup:
        kwargs["reply_markup"] = markup
    return await tg(client, "editMessageText", **kwargs)


async def answer_cbq(client, cbq_id, text="", alert=False):
    return await tg(client, "answerCallbackQuery",
                    callback_query_id=cbq_id, text=text, show_alert=alert)


# ─── Keyboard builders ────────────────────────────────────
def _duration_keyboard(machine_id: str) -> dict:
    """Inline keyboard for admin: choose license duration."""
    m = machine_id  # max ~25 chars; callback_data limit = 64 bytes
    return {
        "inline_keyboard": [
            [
                {"text": "⚡ 1 Day",    "callback_data": f"gk|{m}|1"},
                {"text": "📅 3 Days",   "callback_data": f"gk|{m}|3"},
                {"text": "🗓 7 Days",   "callback_data": f"gk|{m}|7"},
            ],
            [
                {"text": "📆 30 Days",  "callback_data": f"gk|{m}|30"},
                {"text": "🏆 90 Days",  "callback_data": f"gk|{m}|90"},
                {"text": "♾️ Lifetime", "callback_data": f"gk|{m}|0"},
            ],
            [
                {"text": "❌ Reject",   "callback_data": f"rj|{m}"},
            ],
        ]
    }


# ─── Helpers ──────────────────────────────────────────────
MID_RE = re.compile(r"\bMID-[A-Z0-9]{6,12}-[A-Z0-9]{4,10}\b", re.IGNORECASE)

def _tier_and_max(days: int) -> tuple[str, int]:
    if days == 0 or days >= 90:
        return "VIP (Unlimited)", 100
    if days >= 30:
        return "PRO", 50
    if days >= 7:
        return "Standard", 30
    return "Basic (Trial)", 25


def _fmt_expires(expires_str: str) -> str:
    if expires_str in ("Lifetime", None, ""):
        return "♾️ Lifetime — Never expires"
    try:
        dt = datetime.fromisoformat(expires_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = dt - now
        if delta.total_seconds() <= 0:
            return f"⚠️ EXPIRED ({dt.strftime('%Y-%m-%d %H:%M UTC')})"
        days = delta.days
        hours, rem = divmod(delta.seconds, 3600)
        mins = rem // 60
        human = ""
        if days > 0:
            human = f"{days}d {hours}h {mins}m"
        else:
            human = f"{hours}h {mins}m"
        return f"⏳ {human} remaining  ({dt.strftime('%Y-%m-%d %H:%M UTC')})"
    except Exception:
        return expires_str


# ─── Command/Message Handlers ─────────────────────────────
async def on_start(client, msg: dict):
    chat_id = str(msg["chat"]["id"])
    user = msg.get("from", {})
    username = (user.get("username") or "").lower()
    fname = user.get("first_name", "")
    lname = user.get("last_name", "")
    name = f"{fname} {lname}".strip() or username or "User"

    admin_env_id = os.environ.get("ADMIN_CHAT_ID", "").strip()
    is_admin = (admin_env_id and chat_id == admin_env_id) or (username == ADMIN_USERNAME.lower())

    # Check if /start was clicked with a Machine ID parameter (e.g. /start MID_A3F9C2B1_XK7Q2M)
    raw_text = (msg.get("text") or "").strip()
    parts = raw_text.split()
    if len(parts) > 1:
        param = parts[1].replace("_", "-")
        match = MID_RE.search(param)
        if match:
            await on_machine_id(client, msg, match.group(0).upper())
            return

    # Auto-register admin if no Machine ID was requested
    if is_admin:
        state = load_bot_data()
        state["admin_chat_id"] = chat_id
        save_bot_data(state)
        bot_state.update(state)
        pending_count = len(state.get("pending", {}))
        total_keys = len(license_manager.list_licenses())
        await send(client, chat_id,
            f"👑 <b>Admin Registered!</b>\n\n"
            f"Welcome, <b>@{ADMIN_USERNAME}</b> (ID: <code>{chat_id}</code>)! 🎉\n\n"
            f"<b>System Status:</b>\n"
            f"• 🔑 Total license keys: <b>{total_keys}</b>\n"
            f"• ⏳ Pending requests: <b>{pending_count}</b>\n\n"
            f"<b>Admin Commands:</b>\n"
            f"/genkey &lt;MID&gt; &lt;days&gt; — Generate key (0=lifetime)\n"
            f"/listkeys — Show recent license keys\n"
            f"/revoke &lt;KEY&gt; — Revoke a key\n"
            f"/pending — View pending requests\n"
            f"/info — Bot status\n\n"
            f"Users who submit their Machine ID will appear here with 1-click approval buttons. ✅"
        )
        return

    await send(client, chat_id,
        f"🤖 <b>Telegram Adder Pro — License Bot</b>\n\n"
        f"Hello, <b>{name}</b>! 👋\n\n"
        f"<b>How to get your license key:</b>\n\n"
        f"<b>Step 1.</b> Open the Telegram Adder Web tool\n"
        f"<b>Step 2.</b> Click <b>'Activate License'</b>\n"
        f"<b>Step 3.</b> Copy your <b>Machine ID</b> (e.g. <code>MID-XXXXXXXX-YYYYYY</code>)\n"
        f"<b>Step 4.</b> Send it here in this chat\n"
        f"<b>Step 5.</b> Admin will approve and send your license key here! 🔑\n\n"
        f"📞 Direct admin: @{ADMIN_USERNAME}"
    )


async def on_machine_id(client, msg: dict, machine_id: str):
    chat_id = str(msg["chat"]["id"])
    user = msg.get("from", {})
    username = user.get("username", "") or ""
    fname = user.get("first_name", "") or ""
    lname = user.get("last_name", "") or ""
    name = f"{fname} {lname}".strip() or username or "Unknown User"
    now_ts = int(time.time())

    # Always reload fresh state from disk
    state = load_bot_data()
    pending = state.setdefault("pending", {})

    # 1. Debounce: if this machine ID was requested in the last 3 minutes (180s), do not duplicate!
    already = pending.get(machine_id)
    if already:
        last_ts = int(already.get("timestamp") or 0)
        if (now_ts - last_ts) < 180:
            await send(client, chat_id,
                f"⏳ <b>Request already received!</b>\n\n"
                f"Your request for <code>{machine_id}</code> is already waiting for admin review.\n"
                f"Please wait a moment — Admin has already received your request! 🔔\n\n"
                f"Contact: @{ADMIN_USERNAME}"
            )
            return

    # 2. Check if this machine already has an active valid license
    existing_licenses = license_manager.list_licenses()
    active_for_mid = next(
        (lic for lic in existing_licenses if lic.get("bound_device") == machine_id and lic.get("is_active")),
        None
    )
    if active_for_mid:
        key = active_for_mid["key_code"]
        exp = active_for_mid.get("expires_at") or "Lifetime"
        await send(client, chat_id,
            f"ℹ️ <b>Machine Already Licensed!</b>\n\n"
            f"Machine ID <code>{machine_id}</code> already has an active license:\n"
            f"🔑 <code>{key}</code>\n"
            f"⏳ Expires: <b>{exp}</b>\n\n"
            f"You can enter this key directly into your web dashboard!"
        )
        return

    # Store pending request
    pending[machine_id] = {
        "user_chat_id": chat_id,
        "user_name": name,
        "username": username,
        "timestamp": now_ts,
    }
    save_bot_data(state)
    bot_state.update(state)

    # Confirm receipt to user (exactly 1 confirmation)
    await send(client, chat_id,
        f"✅ <b>Machine ID Received!</b>\n\n"
        f"🖥️ Your Machine ID:\n<code>{machine_id}</code>\n\n"
        f"Your request has been forwarded to Admin @{ADMIN_USERNAME}.\n"
        f"You will receive your license key here as soon as approved! 🔑"
    )

    # Notify admin (exactly 1 notification)
    admin_id = state.get("admin_chat_id", "") or bot_state.get("admin_chat_id", "")
    if not admin_id:
        log.warning("Admin chat_id not registered! Admin must send /start to the bot.")
        return

    user_link = f"@{username}" if username else f"<code>{chat_id}</code>"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    await send(client, admin_id,
        f"🔔 <b>New License Request</b> (1)\n\n"
        f"👤 User: <b>{name}</b> ({user_link})\n"
        f"🖥️ Machine ID: <code>{machine_id}</code>\n"
        f"🕐 Requested: {ts}\n\n"
        f"<b>⬇️ Select license duration to generate & send:</b>",
        markup=_duration_keyboard(machine_id)
    )
    log.info(f"License request from {name} ({chat_id}) for {machine_id}")


async def on_genkey_callback(client, cbq: dict, machine_id: str, days: int):
    cbq_id = cbq["id"]
    admin_id = str(cbq["from"]["id"])
    msg = cbq.get("message", {})
    msg_id = msg.get("message_id")

    pending = bot_state.get("pending", {})
    req = pending.get(machine_id)
    user_chat_id = req["user_chat_id"] if req else None
    user_name = req.get("user_name", "User") if req else "User"
    username = req.get("username", "") if req else ""

    # Generate license & automatically revoke old keys for this Machine ID
    tier, max_acc = _tier_and_max(days)
    duration_label = f"{days} day(s)" if days > 0 else "Unlimited (Lifetime)"
    duration_emoji = {0: "♾️", 1: "⚡", 3: "📅", 7: "🗓", 30: "📆", 90: "🏆"}.get(days, "📅")

    lic = license_manager.create_license(
        days=days if days > 0 else None,
        tier=tier,
        max_accounts=max_acc,
        bound_device=machine_id,
        note=f"Bot-issued | {user_name} | MID:{machine_id}"
    )
    key_code = lic["key_code"]
    expires_str = lic["expires_at"]
    expiry_display = _fmt_expires(expires_str)

    old_replaced_msg = ""
    if lic.get("replaced_keys"):
        old_replaced_msg = f"\n🔄 <i>Replaced & revoked {len(lic['replaced_keys'])} old key(s) for this machine.</i>\n"

    # Send key to user if user chat is known
    if user_chat_id:
        await send(client, user_chat_id,
            f"🎉 <b>Your License Key is Ready!</b>\n\n"
            f"🔑 <b>Key:</b> <code>{key_code}</code>\n"
            f"🖥️ <b>Machine ID:</b> <code>{machine_id}</code>\n"
            f"⏱ <b>Duration:</b> {duration_emoji} {duration_label}\n"
            f"📅 <b>Expires:</b> {expiry_display}\n"
            f"📋 <b>Tier:</b> {tier} | Max Accounts: {max_acc}\n\n"
            f"<b>How to activate:</b>\n"
            f"1️⃣ Open the Telegram Adder Web tool\n"
            f"2️⃣ Click <b>'Activate License'</b>\n"
            f"3️⃣ Paste the key above and click Activate\n\n"
            f"✅ Enjoy using Telegram Adder Web Pro! 🚀\n"
            f"Support: @{ADMIN_USERNAME}"
        )
        user_status = f"\n✅ Key automatically delivered to <b>{user_name}</b> in Telegram!"
        pending.pop(machine_id, None)
        save_bot_data(bot_state)
    else:
        user_status = "\nℹ️ No pending user found for this Machine ID.\nSend key manually to the user."

    # Answer admin callback + update message matching exact format
    await answer_cbq(client, cbq_id, f"✅ Key {key_code} generated!")
    if msg_id:
        await edit(client, admin_id, msg_id,
            f"✅ <b>License Key Generated</b>\n\n"
            f"🔑 Key: <code>{key_code}</code>\n"
            f"🖥️ Machine ID: <code>{machine_id}</code>\n"
            f"⏱ Duration: {duration_label}\n"
            f"📅 {expiry_display}\n"
            f"📋 Tier: {tier} | Max Accounts: {max_acc}\n"
            f"{old_replaced_msg}"
            f"{user_status}"
        )
    log.info(f"Key {key_code} issued for {machine_id} ({days}d)")


async def on_reject_callback(client, cbq: dict, machine_id: str):
    cbq_id = cbq["id"]
    admin_id = str(cbq["from"]["id"])
    msg = cbq.get("message", {})
    msg_id = msg.get("message_id")

    req = bot_state.get("pending", {}).get(machine_id)
    if not req:
        await answer_cbq(client, cbq_id, "Request not found.", alert=True)
        return

    user_chat_id = req["user_chat_id"]
    user_name = req.get("user_name", "User")

    await send(client, user_chat_id,
        f"❌ <b>License Request Declined</b>\n\n"
        f"Your request for Machine ID <code>{machine_id}</code> was declined.\n\n"
        f"For assistance, contact admin: @{ADMIN_USERNAME}"
    )

    await answer_cbq(client, cbq_id, f"❌ Request for {user_name} rejected.")
    if msg_id:
        await edit(client, admin_id, msg_id,
            f"❌ <b>Request Rejected</b>\n\n"
            f"🖥️ Machine ID: <code>{machine_id}</code>\n"
            f"👤 User: {user_name}"
        )
    bot_state["pending"].pop(machine_id, None)
    save_bot_data(bot_state)


async def on_genkey_cmd(client, msg: dict):
    """Command: /genkey [MachineID] [days]"""
    chat_id = str(msg["chat"]["id"])
    admin_id = bot_state.get("admin_chat_id", "")
    is_admin = (chat_id == admin_id)

    parts = (msg.get("text", "")).split()

    # 1. Regular user running /genkey
    if not is_admin:
        if len(parts) > 1:
            match = MID_RE.search(parts[1])
            if match:
                await on_machine_id(client, msg, match.group(0).upper())
                return
        await send(client, chat_id,
            "🖥️ <b>Request License Key</b>\n\n"
            "Please send your <b>Machine ID</b> (from the web app activation screen):\n"
            "Example: <code>MID-EC79B3B7-NREQIV</code>\n\n"
            "Admin will approve and send your license key here. 🔑"
        )
        return

    # 2. Admin typed just: /genkey
    if len(parts) == 1:
        pending = bot_state.get("pending", {})
        if pending:
            buttons = []
            for mid, req in list(pending.items())[:6]:
                u = req.get("username") or req.get("user_name") or mid[:14]
                buttons.append([{"text": f"👤 {u} ({mid})", "callback_data": f"selmid|{mid}"}])
            await send(client, chat_id,
                "📋 <b>Select a Pending Machine ID:</b>\n\n"
                "Or generate manually with:\n"
                "<code>/genkey &lt;MachineID&gt; &lt;days&gt;</code>\n"
                "<i>(days: 1, 3, 7, 30, 90, or 0/unlimited)</i>",
                markup={"inline_keyboard": buttons}
            )
        else:
            await send(client, chat_id,
                "📋 <b>Generate License Key:</b>\n\n"
                "Usage: <code>/genkey &lt;MachineID&gt; &lt;days&gt;</code>\n\n"
                "<b>Examples:</b>\n"
                "• <code>/genkey MID-EC79B3B7-NREQIV 1</code> — 1 day\n"
                "• <code>/genkey MID-EC79B3B7-NREQIV 3</code> — 3 days\n"
                "• <code>/genkey MID-EC79B3B7-NREQIV 30</code> — 30 days\n"
                "• <code>/genkey MID-EC79B3B7-NREQIV unlimited</code> — Lifetime\n\n"
                "<i>Tip: You can also type <code>/genkey &lt;MachineID&gt;</code> to choose duration with buttons!</i>"
            )
        return

    # 3. Admin typed: /genkey <MachineID> (without days)
    if len(parts) == 2:
        mid_match = MID_RE.search(parts[1])
        machine_id = mid_match.group(0).upper() if mid_match else parts[1].upper()
        await send(client, chat_id,
            f"🖥️ <b>Machine ID:</b> <code>{machine_id}</code>\n\n"
            f"<b>⬇️ Select license duration to generate:</b>",
            markup=_duration_keyboard(machine_id)
        )
        return

    # 4. Admin typed: /genkey <MachineID> <days>
    mid_match = MID_RE.search(parts[1])
    machine_id = mid_match.group(0).upper() if mid_match else parts[1].upper()
    days_arg = parts[2].lower()

    if days_arg in ("0", "unlimited", "lifetime", "all", "inf", "forever"):
        days = 0
    else:
        try:
            days = int(days_arg)
        except ValueError:
            await send(client, chat_id, "❌ <b>Days</b> must be a number (e.g. 1, 3, 7, 30) or <code>unlimited</code>.")
            return

    tier, max_acc = _tier_and_max(days)
    duration_label = f"{days} day(s)" if days > 0 else "Unlimited (Lifetime)"

    lic = license_manager.create_license(
        days=days if days > 0 else None,
        tier=tier,
        max_accounts=max_acc,
        bound_device=machine_id,
        note=f"Admin-manual | MID:{machine_id}"
    )
    key_code = lic["key_code"]
    expires_str = lic["expires_at"]
    expiry_display = _fmt_expires(expires_str)

    old_replaced_msg = ""
    if lic.get("replaced_keys"):
        old_replaced_msg = f"\n🔄 <i>Replaced & revoked {len(lic['replaced_keys'])} old key(s) for this machine.</i>\n"

    req = bot_state.get("pending", {}).get(machine_id)
    if req:
        status_note = f"\n✅ Key automatically sent to <b>{req.get('user_name', 'user')}</b> in Telegram!"
        await send(client, req["user_chat_id"],
            f"🎉 <b>Your License Key is Ready!</b>\n\n"
            f"🔑 <b>Key:</b> <code>{key_code}</code>\n"
            f"🖥️ <b>Machine ID:</b> <code>{machine_id}</code>\n"
            f"⏱ <b>Duration:</b> {duration_label}\n"
            f"📅 <b>Expires:</b> {expiry_display}\n"
            f"📋 <b>Tier:</b> {tier} | Max Accounts: {max_acc}\n\n"
            f"Activate it in the Telegram Adder Web tool. 🚀\n"
            f"Support: @{ADMIN_USERNAME}"
        )
        bot_state["pending"].pop(machine_id, None)
        save_bot_data(bot_state)
    else:
        status_note = "\nℹ️ No pending user found for this Machine ID.\nSend key manually to the user."

    result = (
        f"✅ <b>License Key Generated</b>\n\n"
        f"🔑 Key: <code>{key_code}</code>\n"
        f"🖥️ Machine ID: <code>{machine_id}</code>\n"
        f"⏱ Duration: {duration_label}\n"
        f"📅 {expiry_display}\n"
        f"📋 Tier: {tier} | Max Accounts: {max_acc}\n"
        f"{old_replaced_msg}"
        f"{status_note}"
    )

    await send(client, chat_id, result)


async def on_listkeys_cmd(client, msg: dict):
    chat_id = str(msg["chat"]["id"])
    if chat_id != bot_state.get("admin_chat_id"):
        await send(client, chat_id, "❌ Admin only.")
        return

    keys = license_manager.list_licenses()
    if not keys:
        await send(client, chat_id, "📭 No license keys in database.")
        return

    lines = ["<b>🔑 Recent License Keys (last 10):</b>\n"]
    for k in keys[:10]:
        status = "✅" if k["is_active"] else "❌"
        exp = _fmt_expires(k.get("expires_at") or "")
        lines.append(f"{status} <code>{k['key_code']}</code>\n   Tier: {k['tier']} | {exp}")

    await send(client, chat_id, "\n".join(lines))


async def on_revoke_cmd(client, msg: dict):
    chat_id = str(msg["chat"]["id"])
    if chat_id != bot_state.get("admin_chat_id"):
        await send(client, chat_id, "❌ Admin only.")
        return

    parts = (msg.get("text", "")).split()
    if len(parts) < 2:
        await send(client, chat_id, "Usage: /revoke &lt;LICENSE_KEY&gt;")
        return

    key_code = parts[1].strip().upper()
    license_manager.revoke_license(key_code)
    await send(client, chat_id, f"🔒 License key <code>{key_code}</code> has been revoked.")


async def on_pending_cmd(client, msg: dict):
    chat_id = str(msg["chat"]["id"])
    if chat_id != bot_state.get("admin_chat_id"):
        await send(client, chat_id, "❌ Admin only.")
        return

    pending = bot_state.get("pending", {})
    if not pending:
        await send(client, chat_id, "✅ No pending license requests.")
        return

    lines = [f"<b>⏳ Pending Requests ({len(pending)}):</b>\n"]
    for mid, req in list(pending.items()):
        ts = datetime.fromtimestamp(req.get("timestamp", 0), tz=timezone.utc)
        age = datetime.now(timezone.utc) - ts
        age_str = f"{age.seconds // 3600}h {(age.seconds % 3600) // 60}m ago" if age.days == 0 else f"{age.days}d ago"
        u = f"@{req['username']}" if req.get("username") else req.get("user_chat_id", "?")
        lines.append(f"🖥️ <code>{mid}</code>\n   👤 {req.get('user_name', '?')} ({u}) · {age_str}")

    await send(client, chat_id, "\n".join(lines))


async def on_info_cmd(client, msg: dict):
    chat_id = str(msg["chat"]["id"])
    admin_id = bot_state.get("admin_chat_id", "")
    pending_count = len(bot_state.get("pending", {}))
    total_keys = len(license_manager.list_licenses())

    await send(client, chat_id,
        f"ℹ️ <b>Bot Status</b>\n\n"
        f"👑 Admin: @{ADMIN_USERNAME}\n"
        f"🆔 Admin Chat ID: <code>{admin_id or 'Not registered'}</code>\n"
        f"⏳ Pending Requests: <b>{pending_count}</b>\n"
        f"🔑 Total License Keys: <b>{total_keys}</b>\n"
        f"✅ Bot Status: Running"
    )


# ─── Update router ────────────────────────────────────────
async def process_update(client: httpx.AsyncClient, update: dict):
    try:
        # ── Callback query (inline button press) ──────────
        if "callback_query" in update:
            cbq = update["callback_query"]
            data = cbq.get("data", "")
            parts = data.split("|")
            if parts[0] == "gk" and len(parts) == 3:
                await on_genkey_callback(client, cbq, parts[1], int(parts[2]))
            elif parts[0] == "rj" and len(parts) == 2:
                await on_reject_callback(client, cbq, parts[1])
            elif parts[0] == "selmid" and len(parts) == 2:
                mid = parts[1]
                await answer_cbq(client, cbq["id"])
                await edit(client, cbq["from"]["id"], cbq["message"]["message_id"],
                           f"🖥️ <b>Machine ID:</b> <code>{mid}</code>\n\n<b>⬇️ Select license duration to generate:</b>",
                           markup=_duration_keyboard(mid))
            return

        # ── Regular message ────────────────────────────────
        msg = update.get("message")
        if not msg:
            return
        text = (msg.get("text") or "").strip()
        if not text:
            return

        cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""

        if cmd == "/start":
            await on_start(client, msg)
        elif cmd == "/genkey":
            await on_genkey_cmd(client, msg)
        elif cmd == "/listkeys":
            await on_listkeys_cmd(client, msg)
        elif cmd == "/revoke":
            await on_revoke_cmd(client, msg)
        elif cmd == "/pending":
            await on_pending_cmd(client, msg)
        elif cmd == "/info":
            await on_info_cmd(client, msg)
        else:
            # Scan for Machine ID in any message
            match = MID_RE.search(text)
            if match:
                await on_machine_id(client, msg, match.group(0).upper())
            else:
                chat_id = str(msg["chat"]["id"])
                await send(client, chat_id,
                    f"💡 To request a license key, send your <b>Machine ID</b>.\n"
                    f"It looks like: <code>MID-XXXXXXXX-YYYYYY</code>\n\n"
                    f"Use /start for instructions."
                )

    except Exception as exc:
        log.error(f"Error handling update: {exc}", exc_info=True)


# ─── Long-polling loop ────────────────────────────────────
async def run_bot():
    if not BOT_TOKEN:
        log.error("=" * 55)
        log.error("BOT_TOKEN is not set!")
        log.error("Create a .env file with: BOT_TOKEN=your_token_here")
        log.error("Or set the BOT_TOKEN environment variable.")
        log.error("=" * 55)
        return

    log.info("=" * 55)
    log.info(f"  Telegram Adder License Bot — @{ADMIN_USERNAME}")
    log.info("=" * 55)

    offset = 0
    async with httpx.AsyncClient(timeout=35) as client:
        # Verify token
        me_resp = await tg(client, "getMe")
        if not me_resp.get("ok"):
            log.error(f"Invalid bot token: {me_resp.get('description')}")
            return

        bot_username = me_resp["result"]["username"]
        log.info(f"Bot connected: @{bot_username}")
        log.info(f"Admin registered: {bool(bot_state.get('admin_chat_id'))}")
        log.info(f"Pending requests: {len(bot_state.get('pending', {}))}")
        log.info(f"Bot URL: https://t.me/{bot_username}")
        log.info("Listening for updates... (Ctrl+C to stop)")

        while True:
            try:
                resp = await tg(client, "getUpdates",
                                offset=offset, timeout=25,
                                allowed_updates=["message", "callback_query"])
                if not resp.get("ok"):
                    await asyncio.sleep(3)
                    continue

                for upd in resp.get("result", []):
                    offset = upd["update_id"] + 1
                    await process_update(client, upd)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error(f"Polling error: {exc}")
                await asyncio.sleep(5)


if __name__ == "__main__":
    if not acquire_single_instance_lock():
        print("[WARN] Another instance of License Bot is already running on this machine.")
        print("[INFO] Exiting duplicate bot process to prevent duplicate admin requests.")
        sys.exit(0)

    license_manager.init_db()
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        log.info("Bot stopped gracefully.")

