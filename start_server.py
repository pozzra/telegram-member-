import os
import sys
import time
import threading
import subprocess
import uvicorn

DEFAULT_BOT_TOKEN = "9039008476:AAFWUTnldWvfiC9CYYTquNEj5SV7GRtlGiI"

def get_bot_token() -> str:
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        env_file = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_file):
            try:
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip().startswith("BOT_TOKEN="):
                            token = line.strip().split("=", 1)[1].strip()
                            break
            except Exception:
                pass
    return token or DEFAULT_BOT_TOKEN

def bot_supervisor_worker():
    """Supervisor thread: keeps Telegram bot running 24/7. Auto-restarts if it ever exits."""
    token = get_bot_token()
    bot_file = os.path.join(os.path.dirname(__file__), "bot.py")
    if not os.path.exists(bot_file):
        print("[SUPERVISOR] bot.py not found, skipping bot supervisor.")
        return

    env = os.environ.copy()
    env["BOT_TOKEN"] = token
    env["ADMIN_CHAT_ID"] = os.environ.get("ADMIN_CHAT_ID", "1208908312")
    env["ADMIN_USERNAME"] = os.environ.get("ADMIN_USERNAME", "kun_amra")

    print(f"[SUPERVISOR] Bot supervisor active for token {token[:10]}... (auto-restart enabled)")
    while True:
        try:
            proc = subprocess.Popen([sys.executable, bot_file], env=env)
            proc.wait()
            print(f"[SUPERVISOR] Bot process exited with code {proc.returncode}. Auto-restarting in 3 seconds...")
        except Exception as e:
            print(f"[SUPERVISOR] Error launching bot process: {e}. Retrying in 5 seconds...")
        time.sleep(3)

def launch_bot_supervisor():
    t = threading.Thread(target=bot_supervisor_worker, daemon=True, name="BotSupervisor")
    t.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")

    print("=" * 60)
    print("  Telegram Adder Pro - Web Edition")
    print(f"  Local URL:   http://127.0.0.1:{port}")
    print(f"  Network URL: http://0.0.0.0:{port}")
    print("=" * 60)

    # Automatically launch resilient bot supervisor in background
    launch_bot_supervisor()

    uvicorn.run("app:app", host=host, port=port, reload=False)

