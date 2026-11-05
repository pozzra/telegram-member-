import os
import sys
import subprocess
import uvicorn

def launch_bot_if_configured():
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

    if token:
        bot_file = os.path.join(os.path.dirname(__file__), "bot.py")
        if os.path.exists(bot_file):
            print(f"[INFO] Starting Telegram License Bot in background with token {token[:10]}...")
            try:
                subprocess.Popen([sys.executable, bot_file])
            except Exception as e:
                print(f"[WARN] Failed to start bot: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")

    print("=" * 60)
    print("  Telegram Adder Pro - Web Edition")
    print(f"  Local URL:   http://127.0.0.1:{port}")
    print(f"  Network URL: http://0.0.0.0:{port}")
    print("=" * 60)

    # Automatically launch bot in background if BOT_TOKEN is present
    launch_bot_if_configured()

    uvicorn.run("app:app", host=host, port=port, reload=False)

