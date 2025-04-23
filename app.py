# app.py
from fastapi import FastAPI, BackgroundTasks, Depends, HTTPException, Request, Header, status, APIRouter
from fastapi.responses import HTMLResponse, FileResponse, Response, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import os
import json
from database.base import Base
from models.schemas import ScanRequest, ScanResult
from database.db_manager import  engine, get_all_scans, save_agent_report, get_db_connection, SessionLocal, get_db
from models.users import User
from services.scan_service import start_scan_task, get_scan_details
from utils.report_generator import generate_scan_report
from config import TEMPLATES_DIR, STATIC_DIR, initialize_directories, setup_logging
from passlib.hash import bcrypt
from utils.settings import router as settings_router
# Auth Routers
from auth.google import router as google_auth
from auth.local import router as local_auth
from auth.dependencies import require_authentication


from models.agent_report import AgentReport, Package  # Adjust as needed
from fastapi.responses import JSONResponse
from utils.agent_router import router as AgentRouter

# Logger setup
logger = setup_logging()

app = FastAPI(title="OpenVulnScan", version="0.1.0")

# Initialize directories and DB
initialize_directories()

    

# Static and templates
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Middleware
from fastapi import FastAPI, Request
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.authentication import AuthenticationMiddleware

from starlette.authentication import (
    AuthenticationBackend, AuthCredentials, SimpleUser, UnauthenticatedUser
)

# Example dummy backend – replace with your real auth logic
class BasicAuthBackend(AuthenticationBackend):
    async def authenticate(self, conn):
        user = conn.session.get("user")
        if user:
            return AuthCredentials(["authenticated"]), SimpleUser(user)
        return AuthCredentials([]), UnauthenticatedUser()
app.add_middleware(AuthenticationMiddleware, backend=BasicAuthBackend())
app.add_middleware(SessionMiddleware, secret_key="super-secret-key",) # change in Prod

# Public routes (no login required)
app.include_router(google_auth)
app.include_router(local_auth)
app.include_router(settings_router)
app.include_router(AgentRouter)
# Create default admin
@app.on_event("startup")
def create_default_admin():
    # Automatically create all tables on app startup
    Base.metadata.create_all(bind=engine)
    from sqlalchemy import inspect
    inspector = inspect(engine)
    print("Existing tables:", inspector.get_table_names())
    db: Session = SessionLocal()
    admin_email = "admin@openvulnscan.local"
    default_password = "admin123"  # Change this in production

    if not db.query(User).filter_by(email=admin_email).first():
        hashed_pw = bcrypt.hash(default_password)
        admin = User(email=admin_email, hashed_password=hashed_pw, is_admin=True)
        db.add(admin)
        db.commit()
        print(f"Default admin user created: {admin_email}")
    else:
        print("Admin user already exists.")
    db.close()


# Protected router
protected_router = APIRouter(dependencies=[Depends(require_authentication)])

@protected_router.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    logger.info("Accessing main page")
    scans = get_all_scans()
    return templates.TemplateResponse("index.html", {"request": request, "scans": scans})

@protected_router.post("/scan", response_model=ScanResult, tags=['scan'])
def start_scan(req: ScanRequest, background_tasks: BackgroundTasks):
    logger.info(f"Starting new scan for targets: {req.targets}")
    result = start_scan_task(req, background_tasks)
    logger.info(f"Scan initiated with ID: {result.id}")
    return result

@protected_router.get("/scan/{scan_id}", response_class=HTMLResponse,tags=['scan'])
def get_scan(scan_id: str, request: Request):
    logger.info(f"Viewing scan results for scan ID: {scan_id}")
    scan_data = get_scan_details(scan_id)
    if not scan_data:
        return HTMLResponse(f"<h1>Scan ID {scan_id} not found</h1>", status_code=404)
    return templates.TemplateResponse("scan_result.html", {
        "request": request,
        "scan_id": scan_id,
        **scan_data
    })

@protected_router.get("/scan/{scan_id}/pdf", response_class=FileResponse, tags=['scan','report'])
def get_scan_pdf(scan_id: str):
    logger.info(f"Generating PDF report for scan ID: {scan_id}")
    pdf_file_path = generate_scan_report(scan_id)
    if not os.path.exists(pdf_file_path):
        raise HTTPException(status_code=404, detail="PDF report not found")
    return FileResponse(pdf_file_path, filename=f"scan_{scan_id}_report.pdf", media_type="application/pdf")

@protected_router.get("/api/report/{agent_id}", tags=["agent","report"])
def get_agent_report(agent_id: int, db: Session = Depends(get_db)):
    report = db.query(AgentReport).filter(AgentReport.id == agent_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    result = {
        "hostname": report.hostname,
        "timestamp": str(report.timestamp),
        "packages": []
    }

    for pkg in report.packages:
        result["packages"].append({
            "name": pkg.name,
            "version": pkg.version,
            "cves": [
                {
                    "id": cve.cve_id,
                    "summary": cve.summary
                } for cve in pkg.cves  # Assuming a relationship exists
            ]
        })

    return JSONResponse(content=result)



# Public route to serve agent script
@app.get("/agent/download", response_class=Response, tags=["agent"])
def download_agent(request: Request):
    base_url = str(request.base_url).rstrip("/")
    agent_code = f'''\
import subprocess
import json
import requests
import socket

OPENVULNSCAN_API = "{base_url}/agent/report"

def get_installed_packages():
    try:
        result = subprocess.run(['dpkg', '-l'], capture_output=True, text=True, check=True)
        packages = []
        for line in result.stdout.split('\\n')[5:]:
            parts = line.split()
            if len(parts) >= 3:
                packages.append({{
                    "name": parts[1],
                    "version": parts[2]
                }})
        return packages
    except Exception as e:
        print(f"Error getting packages: {{e}}")
        return []

def send_report(packages):
    payload = {{
        "hostname": socket.gethostname(),
        "packages": packages
    }}
    headers = {{
        "Content-Type": "application/json"
    }}
    response = requests.post(OPENVULNSCAN_API, headers=headers, json=payload)
    print(f"Report sent, status: {{response.status_code}}, body: {{response.text}}")

if __name__ == "__main__":
    pkgs = get_installed_packages()
    if pkgs:
        send_report(pkgs)
'''
    return Response(content=agent_code, media_type="text/x-python")



# Register the protected routes
app.include_router(protected_router)
