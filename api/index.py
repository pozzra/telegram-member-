import sys
import os
import json
from pathlib import Path
from typing import Any

# Add project root to sys.path so modules (license_manager, telegram_engine, app) are importable
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Import the FastAPI instance with error handling so a failed import
# returns a useful message instead of a generic 500 FUNCTION_INVOCATION_FAILED.
_import_error: str | None = None
app = None

try:
    from app import app  # noqa: F401
except Exception as exc:  # noqa: BLE001
    _import_error = str(exc)

    # Fallback ASGI app that reports the import error.
    async def app(scope: Any, receive: Any, send: Any) -> None:  # type: ignore[misc]
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                    break
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    break
            return

        body = json.dumps({
            "error": "Function import failed",
            "detail": _import_error,
            "hint": "Check Vercel function logs and ensure all requirements.txt dependencies are installed.",
        }).encode("utf-8")

        await send({
            "type": "http.response.start",
            "status": 500,
            "headers": [
                [b"content-type", b"application/json"],
                [b"content-length", str(len(body)).encode()],
            ],
        })
        await send({
            "type": "http.response.body",
            "body": body,
        })


# Alias for Vercel Python runtime (some builders look for `application`)
application = app
