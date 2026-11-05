import os
import json
import asyncio
import psutil
import httpx
from typing import Optional, List, Dict, Any
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, Depends, Header, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import license_manager
import telegram_engine

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# Vercel serverless does not support WebSockets or long-lived background tasks.
IS_VERCEL = bool(os.environ.get("VERCEL"))

DEFAULT_API_ID = int(os.environ.get("TELEGRAM_API_ID", "2040") or 2040)
DEFAULT_API_HASH = os.environ.get(
    "TELEGRAM_API_HASH", "b18441a1ff607e10a989891a5462e627"
)

app = FastAPI(title="Telegram Adder Web Pro", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (CSS, JS) — available in deployment bundle on Vercel.
# Only /tmp is read-only; static/ and templates/ are readable.
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Connected WebSocket clients for real-time live progress and logs
CONNECTED_SOCKETS: List[WebSocket] = []


async def broadcast_event(data: Dict[str, Any]):
    dead_sockets = []
    for ws in CONNECTED_SOCKETS:
        try:
            await ws.send_json(data)
        except Exception:
            dead_sockets.append(ws)
    for ws in dead_sockets:
        if ws in CONNECTED_SOCKETS:
            CONNECTED_SOCKETS.remove(ws)


def engine_event_callback(event_data: Dict[str, Any]):
    # Bridge sync callback into async loop
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(broadcast_event(event_data))
    except Exception:
        pass


# ==========================================
# License Security Dependency
# ==========================================
def require_active_license(
    x_license_key: Optional[str] = Header(None, alias="X-License-Key"),
    x_machine_id: Optional[str] = Header(None, alias="X-Machine-Id"),
):
    if not x_license_key or not x_license_key.strip():
        raise HTTPException(
            status_code=403,
            detail="Tool Activation Required: Please activate a valid license key before adding Telegram accounts or using tools."
        )
    valid, message, details = license_manager.verify_license(x_license_key.strip(), machine_id=x_machine_id)
    if not valid:
        raise HTTPException(status_code=403, detail=f"License Error: {message}")
    if details is None:
        details = {}
    details["machine_id"] = (x_machine_id or details.get("bound_device") or "").strip()
    return details


# ==========================================
# Pydantic Request Models
# ==========================================
class LicenseActivateRequest(BaseModel):
    license_key: str
    machine_id: Optional[str] = None

class AdminCreateKeyRequest(BaseModel):
    admin_key: str
    days: Optional[int] = None
    tier: str = "VIP"
    max_accounts: int = 50
    note: str = ""
    custom_key: Optional[str] = None

class RequestCodeRequest(BaseModel):
    phone: str
    api_id: int
    api_hash: str

class StartQrLoginRequest(BaseModel):
    api_id: int = DEFAULT_API_ID
    api_hash: str = DEFAULT_API_HASH

class SubmitQr2FaRequest(BaseModel):
    qr_id: str
    password: str

class VerifyCodeRequest(BaseModel):
    phone: str
    code: Optional[str] = ""
    password: Optional[str] = None
    phone_code_hash: Optional[str] = None
    api_id: Optional[int] = None
    api_hash: Optional[str] = None
    password_stage: bool = False

class ToggleAccountRequest(BaseModel):
    phone: str
    enabled: bool

class ScrapeRequest(BaseModel):
    source_group: str
    account_phone: Optional[str] = None
    accounts_override: Optional[List[Dict[str, Any]]] = None

class StartAddRequest(BaseModel):
    target_group: str
    members: List[str]
    delay: float = 3.0
    max_per_account: int = 30
    accounts_override: Optional[List[Dict[str, Any]]] = None

class InviteOneRequest(BaseModel):
    target_group: str
    member: str
    account: Dict[str, Any]
    accounts_override: Optional[List[Dict[str, Any]]] = None


# ==========================================
# Web Page Route
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"admin_username": "kun_amra"}
    )


# ==========================================
# License API Routes
# ==========================================
@app.api_route("/api/license/activate", methods=["GET", "POST", "OPTIONS", "HEAD"])
async def activate_license(
    request: Request,
    req: Optional[LicenseActivateRequest] = None,
):
    if request.method in ["OPTIONS", "HEAD"]:
        return JSONResponse(content={"ok": True})
    key = None
    mid = None

    if req and req.license_key:
        key = req.license_key
        mid = req.machine_id
    elif request.method == "POST":
        try:
            body = await request.json()
            key = body.get("license_key")
            mid = body.get("machine_id")
        except Exception:
            pass

    if not key:
        key = request.query_params.get("license_key") or request.headers.get("X-License-Key")
    if not mid:
        mid = request.query_params.get("machine_id") or request.headers.get("X-Machine-Id")

    if not key or not str(key).strip():
        return JSONResponse(status_code=400, content={"success": False, "message": "License key is missing or empty."})

    # Clean key: remove any spaces e.g. 'TGADD - 5KMC - ...' -> 'TGADD-5KMC-...'
    clean_key = str(key).replace(" ", "").strip().upper()
    clean_mid = str(mid).replace(" ", "").strip().upper() if mid else None

    valid, message, details = license_manager.verify_license(clean_key, machine_id=clean_mid, bind_if_unbound=True)
    if not valid:
        return JSONResponse(status_code=400, content={"success": False, "message": message})
    return {"success": True, "message": message, "license": details}


@app.api_route("/api/license/status", methods=["GET", "POST", "OPTIONS", "HEAD"])
async def license_status(
    request: Request,
    x_license_key: Optional[str] = Header(None, alias="X-License-Key"),
    x_machine_id: Optional[str] = Header(None, alias="X-Machine-Id"),
):
    if request.method in ["OPTIONS", "HEAD"]:
        return JSONResponse(content={"ok": True})
    key = x_license_key or request.query_params.get("license_key")
    mid = x_machine_id or request.query_params.get("machine_id")
    if not key:
        return {"is_active": False, "message": "No license key provided."}
    clean_key = str(key).replace(" ", "").strip().upper()
    clean_mid = str(mid).replace(" ", "").strip().upper() if mid else None
    valid, message, details = license_manager.verify_license(clean_key, machine_id=clean_mid)
    return {"is_active": valid, "message": message, "license": details}


@app.post("/api/license/admin/generate")
async def admin_generate_key(req: AdminCreateKeyRequest):
    # Master key for admin kun_amra
    if req.admin_key.strip() != "kun_amra_admin_2026":
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid Admin Master Key.")
    
    key_info = license_manager.create_license(
        days=req.days,
        tier=req.tier,
        max_accounts=req.max_accounts,
        note=req.note,
        custom_key=req.custom_key
    )
    return {"success": True, "generated": key_info}


@app.get("/api/license/admin/list")
async def admin_list_keys(admin_key: str):
    if admin_key.strip() != "kun_amra_admin_2026":
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {"success": True, "licenses": license_manager.list_licenses()}


@app.post("/api/license/admin/revoke")
async def admin_revoke_key(request: Request):
    body = await request.json()
    admin_key = body.get("admin_key", "")
    if admin_key != "kun_amra_admin_2026":
        raise HTTPException(status_code=401, detail="Unauthorized")
    key_code = body.get("key_code", "")
    license_manager.revoke_license(key_code)
    return {"success": True, "message": f"Key {key_code} revoked and blacklisted."}


@app.post("/api/license/admin/delete-all")
async def admin_delete_all(request: Request):
    body = await request.json()
    admin_key = body.get("admin_key", "")
    if admin_key != "kun_amra_admin_2026":
        raise HTTPException(status_code=401, detail="Unauthorized")
    count = license_manager.delete_all_licenses()
    return {"success": True, "deleted": count}


# ==========================================
# System Stats Monitor (CPU / RAM / Disk)
# ==========================================
@app.get("/api/system/stats")
async def system_stats():
    try:
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("C:\\" if os.name == "nt" else "/")
        return {
            "cpu_percent": cpu,
            "ram_used_gb": round(mem.used / (1024**3), 2),
            "ram_total_gb": round(mem.total / (1024**3), 2),
            "ram_percent": mem.percent,
            "disk_free_gb": round(disk.free / (1024**3), 2),
            "disk_total_gb": round(disk.total / (1024**3), 2),
            "disk_percent": disk.percent,
        }
    except Exception as exc:
        return {"error": str(exc)}


# ==========================================
# Telegram Account Management (License Protected per Machine ID)
# ==========================================
@app.get("/api/accounts")
async def get_accounts(license: Dict[str, Any] = Depends(require_active_license)):
    mid = license.get("machine_id")
    accounts = telegram_engine.load_accounts(mid)
    return {
        "success": True,
        "accounts": accounts,
        "max_accounts": license.get("max_accounts", 50),
        "total": len(accounts),
        "active_count": sum(1 for a in accounts if a.get("enabled", True)),
    }


@app.post("/api/accounts/request-code")
async def request_code(req: RequestCodeRequest, license: Dict[str, Any] = Depends(require_active_license)):
    mid = license.get("machine_id")
    accounts = telegram_engine.load_accounts(mid)
    max_acc = license.get("max_accounts", 50)
    norm = telegram_engine.normalize_phone(req.phone)
    existing_phones = {telegram_engine.normalize_phone(a.get("phone_number", "")) for a in accounts}
    if norm not in existing_phones and len(accounts) >= max_acc:
        raise HTTPException(
            status_code=400,
            detail=f"Account limit reached! Your license allows maximum {max_acc} accounts."
        )

    ok, msg, data = await telegram_engine.request_telegram_code(req.phone, req.api_id, req.api_hash, machine_id=mid)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "data": data}


@app.post("/api/accounts/verify-code")
async def verify_code(req: VerifyCodeRequest, license: Dict[str, Any] = Depends(require_active_license)):
    mid = license.get("machine_id")
    ok, msg, data = await telegram_engine.verify_telegram_code(
        req.phone,
        req.code,
        req.password,
        phone_code_hash=req.phone_code_hash,
        api_id=req.api_id,
        api_hash=req.api_hash,
        password_stage=req.password_stage,
        machine_id=mid,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "data": data}


@app.post("/api/accounts/qr-login/start")
async def qr_login_start(req: StartQrLoginRequest, license: Dict[str, Any] = Depends(require_active_license)):
    mid = license.get("machine_id")
    accounts = telegram_engine.load_accounts(mid)
    max_acc = license.get("max_accounts", 50)
    if len(accounts) >= max_acc:
        raise HTTPException(
            status_code=400,
            detail=f"Account limit reached! Your license allows maximum {max_acc} accounts."
        )
    ok, msg, data = await telegram_engine.start_qr_login(req.api_id, req.api_hash, machine_id=mid)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "data": data}


@app.get("/api/accounts/qr-login/status/{qr_id}")
async def qr_login_status(qr_id: str, license: Dict[str, Any] = Depends(require_active_license)):
    status_data = telegram_engine.get_qr_login_status(qr_id)
    return {"success": True, "data": status_data}


@app.post("/api/accounts/qr-login/2fa")
async def qr_login_2fa(req: SubmitQr2FaRequest, license: Dict[str, Any] = Depends(require_active_license)):
    mid = license.get("machine_id")
    ok, msg, data = await telegram_engine.submit_qr_2fa(req.qr_id, req.password, machine_id=mid)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "data": data}


@app.post("/api/accounts/qr-login/close/{qr_id}")
async def qr_login_close(qr_id: str, license: Dict[str, Any] = Depends(require_active_license)):
    cancelled = await telegram_engine.cancel_qr_login(qr_id)
    return {"success": True, "cancelled": cancelled}


@app.post("/api/accounts/toggle")
async def toggle_account(req: ToggleAccountRequest, license: Dict[str, Any] = Depends(require_active_license)):
    mid = license.get("machine_id")
    telegram_engine.toggle_account_status(req.phone, req.enabled, machine_id=mid)
    return {"success": True, "phone": req.phone, "enabled": req.enabled}


@app.delete("/api/accounts/{phone}")
async def delete_account_route(phone: str, license: Dict[str, Any] = Depends(require_active_license)):
    mid = license.get("machine_id")
    telegram_engine.delete_account(phone, machine_id=mid)
    return {"success": True, "message": f"Account {phone} removed."}


@app.post("/api/accounts/clear-spam")
async def clear_spam_flag(request: Request, license: Dict[str, Any] = Depends(require_active_license)):
    """Clear the spam_flagged badge from an account."""
    mid = license.get("machine_id")
    body = await request.json()
    phone = body.get("phone", "").strip()
    if not phone:
        raise HTTPException(status_code=400, detail="phone is required")
    telegram_engine.add_or_update_account({"phone_number": phone, "spam_flagged": False}, machine_id=mid)
    return {"success": True, "message": f"Spam flag cleared for {phone}"}


@app.post("/api/accounts/sync-cache")
async def sync_accounts_cache(request: Request, license: Dict[str, Any] = Depends(require_active_license)):
    """Restore accounts file from client localStorage cache if server accounts file was missing."""
    mid = license.get("machine_id")
    try:
        body = await request.json()
        cached = body.get("accounts", [])
        if isinstance(cached, list) and cached:
            existing = telegram_engine.load_accounts(mid)
            if not existing:
                telegram_engine.save_accounts(cached, mid)
    except Exception:
        pass
    return {"success": True}


@app.post("/api/accounts/clear-all")
async def clear_all_accounts(license: Dict[str, Any] = Depends(require_active_license)):
    mid = license.get("machine_id")
    accounts = telegram_engine.load_accounts(mid)
    for acc in accounts:
        telegram_engine.delete_account(acc.get("phone_number", ""), machine_id=mid)
    return {"success": True, "message": "All accounts cleared."}


# ==========================================
# Telegram Member Scraper & Adder (License Protected)
# ==========================================
@app.post("/api/members/scrape")
async def scrape_members(req: ScrapeRequest, license: Dict[str, Any] = Depends(require_active_license)):
    mid = license.get("machine_id")
    if not req.source_group.strip():
        raise HTTPException(status_code=400, detail="Source group link or username is required.")
    if req.accounts_override and isinstance(req.accounts_override, list):
        for acc in req.accounts_override:
            if isinstance(acc, dict) and acc.get("phone_number"):
                telegram_engine.add_or_update_account(acc, machine_id=mid)
    ok, msg, data = await telegram_engine.fetch_group_members(req.source_group, req.account_phone, machine_id=mid)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "data": data}


@app.post("/api/members/start-add")
async def start_add_members(req: StartAddRequest, license: Dict[str, Any] = Depends(require_active_license)):
    mid = license.get("machine_id")
    if telegram_engine.CURRENT_JOB["is_running"]:
        raise HTTPException(status_code=400, detail="An adding job is already running! Please stop it first.")

    if not req.target_group.strip():
        raise HTTPException(status_code=400, detail="Target group link is required.")

    clean_members = [m.strip() for m in req.members if m.strip()]
    if not clean_members:
        raise HTTPException(status_code=400, detail="Member list cannot be empty.")

    if req.accounts_override and isinstance(req.accounts_override, list):
        for acc in req.accounts_override:
            if isinstance(acc, dict) and acc.get("phone_number"):
                telegram_engine.add_or_update_account(acc, machine_id=mid)

    # Start background task with live event streaming
    asyncio.create_task(
        telegram_engine.run_adding_flow(
            target_group_link=req.target_group,
            members=clean_members,
            delay_seconds=req.delay,
            max_per_account=req.max_per_account,
            log_callback=engine_event_callback,
            machine_id=mid,
        )
    )

    return {"success": True, "message": f"Started adding {len(clean_members)} members to {req.target_group}"}


@app.post("/api/members/invite-one")
async def invite_one_route(req: InviteOneRequest, license: Dict[str, Any] = Depends(require_active_license)):
    mid = license.get("machine_id")
    if not req.target_group.strip():
        raise HTTPException(status_code=400, detail="Target group is required.")
    if not req.member.strip():
        raise HTTPException(status_code=400, detail="Member candidate is required.")
    
    # Sync accounts override if provided
    if req.accounts_override and isinstance(req.accounts_override, list):
        for acc in req.accounts_override:
            if isinstance(acc, dict) and acc.get("phone_number"):
                telegram_engine.add_or_update_account(acc, machine_id=mid)

    result = await telegram_engine.invite_single_member(
        target_group_link=req.target_group.strip(),
        member=req.member.strip(),
        account=req.account,
        machine_id=mid
    )
    return result


@app.post("/api/members/stop-add")
async def stop_add_members(license: Dict[str, Any] = Depends(require_active_license)):
    stopped = telegram_engine.stop_adding_job()
    return {"success": True, "message": "Stop signal sent." if stopped else "No active job running."}


@app.get("/api/members/status")
async def get_job_status(license: Dict[str, Any] = Depends(require_active_license)):
    return {"success": True, "job": telegram_engine.CURRENT_JOB}


# ==========================================
# Health Check & Keep-Alive (Prevents Render Free sleep)
# ==========================================
@app.get("/api/health")
async def health_check():
    return {"status": "ok", "vercel": IS_VERCEL}


async def render_keep_alive_task():
    """Keeps Render cloud server awake 24/7 by self-pinging every 9 minutes."""
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "").strip()
    if not render_url:
        return
    ping_url = f"{render_url.rstrip('/')}/api/health"
    await asyncio.sleep(60)
    async with httpx.AsyncClient(timeout=20) as client:
        while True:
            try:
                await client.get(ping_url)
            except Exception:
                pass
            await asyncio.sleep(540)  # Ping every 9 minutes


@app.on_event("startup")
async def on_app_startup():
    asyncio.create_task(render_keep_alive_task())


# ==========================================
# Real-Time WebSocket for Live Progress & Logs
# (Skipped on Vercel — serverless does not support WebSockets)
# ==========================================
if not IS_VERCEL:
    @app.websocket("/ws/events")
    async def websocket_events(websocket: WebSocket):
        await websocket.accept()
        CONNECTED_SOCKETS.append(websocket)
        # Send initial current job status immediately
        try:
            await websocket.send_json({
                "type": "init",
                "job": telegram_engine.CURRENT_JOB
            })
            while True:
                # Keep socket alive
                await websocket.receive_text()
        except WebSocketDisconnect:
            if websocket in CONNECTED_SOCKETS:
                CONNECTED_SOCKETS.remove(websocket)
        except Exception:
            if websocket in CONNECTED_SOCKETS:
                CONNECTED_SOCKETS.remove(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
