from fastapi import APIRouter, Request, Depends, Form, Body, status
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from starlette.status import HTTP_303_SEE_OTHER
from fastapi.templating import Jinja2Templates
import httpx
import os
from auth.dependencies import require_authentication
from fastapi import Depends

from sqlalchemy.orm import Session
from sqlalchemy import func, desc, select
from database.db_manager import get_db
from models.agent_report import AgentReport, Package, CVE


router = APIRouter()
templates = Jinja2Templates(directory="templates")





from models.users import User
from auth.dependencies import get_current_user
from passlib.context import CryptContext


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

@router.post("/settings/change-password")
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    if new_password != confirm_password:
        return templates.TemplateResponse("settings.html", {"request": request, "error": "Passwords do not match."})

    if not pwd_context.verify(current_password, user.hashed_password):
        return templates.TemplateResponse("settings.html", {"request": request, "error": "Current password is incorrect."})

    user.hashed_password = pwd_context.hash(new_password)
    db.commit()

    return templates.TemplateResponse("settings.html", {"request": request, "success": "Password updated successfully."})


# Default CVE API URL (can be modified in settings)
CVE_API_URL = os.getenv("CVE_API_URL", "https://api.osv.dev/v1/query")

@router.get("/settings", response_class=HTMLResponse, dependencies=[Depends(require_authentication)], tags=["Configuration"])
def settings_page(request: Request, user: User = Depends(require_authentication)):
    """Display settings page."""
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "cve_api_url": CVE_API_URL
    })

@router.post("/settings/update",  tags=["Configuration"])
def update_settings(request: Request, cve_api_url: str = Form(...), user: User = Depends(require_authentication)):
    """Update CVE API URL setting."""
    global CVE_API_URL
    CVE_API_URL = cve_api_url
    return RedirectResponse(url="/settings", status_code=HTTP_303_SEE_OTHER)

@router.post("/cve/check", response_class=JSONResponse, dependencies=[Depends(require_authentication)], tags=["agent"])
async def check_package_cves(
    payload: dict = Body(...), user: User = Depends(require_authentication)
):
    """
    Dynamically query the CVE database for a given package name, version, and ecosystem.
    Expected payload format:
    {
        "name": "openssl",
        "version": "1.1.1",
        "ecosystem": "Debian"
    }
    """
    try:
        query = {
            "package": {
                "name": payload["name"],
                "ecosystem": payload.get("ecosystem", "Debian")  # Default to Debian
            },
            "version": payload["version"]
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(CVE_API_URL, json=query)
            response.raise_for_status()
            data = response.json()
            return {
                "status": "success",
                "query": query,
                "vulnerabilities": data.get("vulns", [])
            }

    except Exception as e:
        return {"status": "error", "message": str(e)}
    
@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(require_authentication)):
    report_count = db.scalar(select(func.count()).select_from(AgentReport))
    package_count = db.scalar(select(func.count()).select_from(Package))
    cve_count = db.scalar(select(func.count()).select_from(CVE))

    # Top vulnerable packages by CVE count
    top_packages_query = (
        select(Package.name, func.count(CVE.id).label("cve_count"))
        .join(CVE, CVE.package_id == Package.id)
        .group_by(Package.name)
        .order_by(func.count(CVE.id).desc())
        .limit(5)
    )
    top_packages = db.execute(top_packages_query).all()

    # Distinct agents with latest report
    latest_reports_query = (
        select(AgentReport.hostname, AgentReport.id.label("latest_report_id"), AgentReport.reported_at)
        .distinct(AgentReport.hostname)
        .order_by(AgentReport.hostname, AgentReport.reported_at.desc())
    )
    agents = db.execute(latest_reports_query).all()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "report_count": report_count,
        "package_count": package_count,
        "cve_count": cve_count,
        "top_packages": top_packages,
        "agents": agents
    })

    