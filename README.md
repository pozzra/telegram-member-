# Telegram Adder Pro – Web Edition & License Bot

A full-stack asynchronous Python web application ported from `TelegramAdder.py` (Desktop GUI) to a web interface. Features multi-account load balancing, Telegram member scraping, mass inviting, Vercel serverless hosting support, and an automated Telegram license bot.

---

## Table of Contents

1. [System Architecture](#system-architecture)
2. [Automated Telegram License Bot](#automated-telegram-license-bot)
3. [Live License Expiration Countdown](#live-license-expiration-countdown)
4. [Hosting on Vercel](#hosting-on-vercel)
5. [Running Locally](#running-locally)
6. [Telegram Account Login Troubleshooting](#telegram-account-login-troubleshooting)
7. [Default Demo Keys](#default-demo-keys)

---

## 1. System Architecture

```
+--------------------------+      +--------------------------+      +--------------------------+
|   Telegram Web App       |      |  Telegram License Bot    |      |     Admin (@kun_amra)    |
|   (FastAPI / Vercel)     |      |     (bot.py)             |      |                          |
+--------------------------+      +--------------------------+      +--------------------------+
         |                               |                                |
         | 1. Shows Machine ID (MID-...) |                                |
         | 2. User clicks "Request"      |                                |
         |                               | 3. Alerts admin with buttons   |
         |                               |    [1d] [3d] [7d] [30d] [90d]  |
         |                               |    [Lifetime] [Reject]         |
         |                               |                                |
         |                               | 4. Bot generates license key   |
         |                               | 5. Sends key to user chat      |
         |                               |                                |
         | 4. User activates key         |                                |
         | 5. Live countdown timer       |                                |
         +-------------------------------+--------------------------------+
```

### License Flow

| Step | Actor | Action |
|------|-------|--------|
| 1 | User | App displays unique Machine ID (`MID-...`) |
| 2 | User | Requests a license key |
| 3 | Admin | Receives notification with duration buttons (1 Day – Lifetime) |
| 4 | Bot | Generates license key and sends it directly to the user |
| 5 | User | Activates the key in the web app; live countdown begins |

---

## 2. Automated Telegram License Bot (`bot.py`)

### Setup

1. Open [@BotFather](https://t.me/BotFather) on Telegram and create a bot (or use an existing one).
2. Copy your **Bot Token**.
3. Create a `.env` file from `.env.example`:

   ```bash
   copy .env.example .env
   ```

4. Add your token:

   ```env
   BOT_TOKEN=1234567890:ABCdefGhiJklMnoPqrStuVwxYz
   ```

5. Start the bot:

   ```bash
   python bot.py
   ```

   *(Or double-click `run_bot.bat` on Windows)*

6. Open your bot on Telegram and send `/start` as admin (`@kun_amra`). The bot will register you as the admin.

### How Admin Approves Keys

When a user sends their **Machine ID** (e.g. `MID-A3F9C2B1-XK7Q2M`) to the bot:

- The admin receives an instant notification with inline buttons:
  - `[1 Day]`
  - `[3 Days]`
  - `[7 Days]`
  - `[30 Days]`
  - `[90 Days]`
  - `[Lifetime]`
  - `[Reject]`
- Clicking a button automatically creates the key in the database and sends it directly to the user's chat.

### Admin Bot Commands

| Command | Description |
|---------|-------------|
| `/genkey <MachineID> <days>` | Manually generate a key (use `0` for lifetime) |
| `/listkeys` | View the 10 most recent license keys |
| `/revoke <KEY>` | Revoke or deactivate an active key |
| `/pending` | View pending Machine ID requests |
| `/info` | Check bot health, total keys, and admin chat ID |

---

## 3. Live License Expiration Countdown

When a user activates a time-limited license:

- The web app header displays a **live real-time countdown** (e.g. `Basic (Trial) – 23h 59m 45s`).
- Colors change dynamically based on urgency:
  - **Green**: Active with plenty of time remaining
  - **Amber**: Less than 24 hours remaining
  - **Red Flashing**: Less than 2 hours remaining
  - **"License EXPIRED"**: Time has run out; tools lock automatically
- Lifetime keys display `Lifetime`.

---

## 4. Free Server Hosting Options

### Option A: Render.com (Recommended Free Cloud Hosting - Supports WebSockets & Persistent Tasks)

Render gives you 750 hours/month of **Free Web Service** with real Python support, WebSockets, and background workers.

1. Go to [render.com](https://render.com) and sign in with GitHub.
2. Click **New +** → **Blueprint** (or **Web Service**).
3. Connect your GitHub repository (`https://github.com/pozzra/telegram-member-`).
4. Render will automatically detect [`render.yaml`](file:///c:/Users/PC/Desktop/telegram%20adder%20web/render.yaml) and configure:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app:app --host 0.0.0.0 --port $PORT`
5. Click **Apply / Deploy**. Your app will be live at `https://your-service-name.onrender.com` for free!

---

### Option B: Free Instant Public HTTPS URL (From Your PC)

If you run the app locally on your PC, you can expose it to the internet with a free HTTPS URL in one click:

1. Double-click [`run_web.bat`](file:///c:/Users/PC/Desktop/telegram%20adder%20web/run_web.bat) to start the local server.
2. Double-click [`run_free_online_tunnel.bat`](file:///c:/Users/PC/Desktop/telegram%20adder%20web/run_free_online_tunnel.bat).
3. It creates a secure public HTTPS link (e.g., `https://random-name.loca.lt`) instantly for free!

---

### Option C: Hosting on Vercel

The project is pre-configured for **Vercel** serverless hosting in [`vercel.json`](file:///c:/Users/PC/Desktop/telegram%20adder%20web/vercel.json):

| File | Purpose |
|------|---------|
| `vercel.json` | Routes all traffic and static assets to `@vercel/python` |
| `api/index.py` | Serverless ASGI entrypoint that imports the FastAPI `app` |
| `telegram_engine.py` / `license_manager.py` | Auto-detect `VERCEL` env var; use `/tmp/data` and `/tmp/sessions` |

### Deploy to Vercel

#### Method A: Vercel CLI

```bash
npm install -g vercel
vercel
```

#### Method B: GitHub + Vercel Dashboard

1. Push this project folder to a GitHub repository.
2. Go to [vercel.com](https://vercel.com) and click **"Add New Project"**.
3. Select your GitHub repository.
4. Click **Deploy**. Vercel installs `requirements.txt` and launches the app.

### Required Environment Variables

Set these in the Vercel Dashboard (**Settings → Environment Variables**):

| Variable | Example | Notes |
|----------|---------|-------|
| `VERCEL` | `1` | Set automatically by Vercel |
| `TELEGRAM_API_ID` | `12345678` | Your own API ID from [my.telegram.org/apps](https://my.telegram.org/apps) |
| `TELEGRAM_API_HASH` | `0123456789abcdef...` | Your own API hash from [my.telegram.org/apps](https://my.telegram.org/apps) |
| `DEFAULT_COUNTRY_CODE` | `855` | Default country code for local phone numbers |
| `BOT_TOKEN` | `1234567890:ABC...` | Only needed if running `bot.py` separately |
| `ADMIN_CHAT_ID` | `12345678` | Telegram admin chat ID for the license bot |
| `LICENSE_API_BASE` | `https://telegram-adder-web.onrender.com` | Central license server used to sync revocations. Leave empty on the Render backend itself. |

### Revocation Sync (Bot ↔ Hosted Site)

License keys are cryptographically signed, so a key can be verified offline. That
means a key revoked in the Telegram bot would otherwise keep working on the
hosted site. To prevent this, revocations are synced through the Render backend:

- **Bot → Render:** `/revoke`, the inline **🔒 Revoke** button, **🗑 Delete**, and
  **/deleteall** all push the revocation to `LICENSE_API_BASE` immediately. On bot
  startup the bot also pushes its full local revoked list, so keys revoked before
  this feature existed propagate on the next restart.
- **Render → Bot/Vercel:** every license verification merges the central revoked
  list (cached for `REVOKED_SYNC_TTL` seconds, default 30). If the central server
  is unreachable, the local revoked file is used so verification never hard-fails.
- **Manual sync:** send `/sync` to the bot to force-pull the revoked list.

> Render must be running for cross-instance revocation to propagate. If it is
> down, the bot keeps revoking locally and catches up automatically on restart.

### Limitations on Vercel Serverless

1. **No WebSockets** – The live progress/logs WebSocket (`/ws/events`) is disabled. Member addition progress will not stream in real time.
2. **Ephemeral storage** – `/tmp` is temporary. Account sessions (`sessions/*.session`), `data/accounts.json`, and `data/pending_logins.json` do **not** persist across serverless invocations. For reliable long-running account management, run on a VPS or local machine instead.
3. **Short-lived connections** – Each HTTP request runs in a fresh environment. Telegram clients connect, perform their action (send code / verify / scrape), and disconnect within the same request.
4. **No background jobs** – Member scraping/adding cannot run as a background task on serverless.

> **Recommendation:** Use Vercel for the dashboard/UI and license activation. For account-heavy operations (adding many members, long-term session management), run on a local PC or VPS using `run_web.bat` / `python start_server.py`.

---

## 5. Running Locally

### Start the Web Server

```bash
python start_server.py
```

*(Or double-click `run_web.bat` on Windows)*

Opens at: **http://127.0.0.1:8000**

### Start the License Bot

```bash
python bot.py
```

*(Or double-click `run_bot.bat` on Windows)*

### Important

Open the dashboard from **http://127.0.0.1:8000**. Do not open `templates/index.html` directly with VS Code Live Server (port 5500) — the page is served without Jinja rendering, and cross-origin API calls may be blocked by the browser. The account login flow is designed to run through the FastAPI server on port 8000.

---

## 6. Telegram Account Login Troubleshooting

| Issue | Solution |
|-------|----------|
| **Phone format** | Use international format (e.g. `+85512345678`). Local numbers starting with `0` are converted using `DEFAULT_COUNTRY_CODE` (default `855`). |
| **Code not received** | The code may arrive inside Telegram (from the official "Telegram" service chat) or by SMS. If it does not arrive within a minute, click **Resend Code** in the login dialog. |
| **2FA enabled** | Enter the Telegram cloud password after confirming the code. The dialog detects this automatically. |
| **Flood wait / rate limit** | Telegram is rate-limiting login attempts. Wait for the time shown in the error (often 5 minutes to several hours). Repeatedly clicking "Request code" makes the wait longer. |
| **Shared API credentials** | Use your own API ID and API Hash from [my.telegram.org/apps](https://my.telegram.org/apps) for the most reliable login. Built-in fallback credentials are shared and more likely to hit limits. |
| **No Telegram account** | The phone number must already have a Telegram account. Third-party apps cannot create new accounts. |
| **QR login** | Easiest option when already signed in on your phone: Telegram Settings → Devices → Link Desktop Device → scan the QR. The dashboard refreshes an expired QR automatically. |
| **Vercel storage** | Serverless `/tmp` storage is temporary. For reliable account sessions, run on a normal PC/VPS or use QR/phone login on the same running instance. |

---

## 7. Default Demo Keys (For Testing)

| License Key | Tier | Expiration | Note |
|-------------|------|------------|------|
| `TGADD-VIP-LIFETIME-ACCESS` | VIP (Unlimited) | Lifetime | Master Admin Key |
| `TGADD-TRIAL-30DAYS-PASS` | PRO (50 Accounts) | 30 Days | Trial Pass |

---
