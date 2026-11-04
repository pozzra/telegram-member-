import sys
from pathlib import Path

# Add project root to sys.path so modules (license_manager, telegram_engine, app) are importable
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Import the FastAPI instance
from app import app

# Alias for Vercel Python runtime (some builders look for `application`)
application = app
