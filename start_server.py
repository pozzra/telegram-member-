import os
import sys
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")

    print("=" * 60)
    print("  Telegram Adder Pro - Web Edition")
    print(f"  Local URL:   http://127.0.0.1:{port}")
    print(f"  Network URL: http://0.0.0.0:{port}")
    print("=" * 60)

    uvicorn.run("app:app", host=host, port=port, reload=True)

