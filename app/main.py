import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.limiter import limiter
from app.config import settings
import app.models
from app.database import init_db
from app.services.notification_service import run_daily_reminder_job, run_daily_billing_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("zapreembolso")

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup seguro com captura de exceções para garantir que a API nunca caia no boot
    try:
        await init_db()
        logger.info("✅ Banco de dados inicializado com sucesso!")
    except Exception as e:
        logger.error(f"⚠️ Alerta: Erro ao inicializar banco de dados no startup: {e}")

    try:
        scheduler.add_job(run_daily_reminder_job, 'cron', hour=8, minute=0)
        scheduler.add_job(run_daily_billing_job, 'cron', hour=9, minute=0)
        scheduler.start()
        logger.info("🚀 ZapReembolso API iniciada e Scheduler ativo!")
    except Exception as e:
        logger.error(f"⚠️ Alerta: Erro ao iniciar Scheduler: {e}")
    
    yield
    
    # Shutdown
    try:
        scheduler.shutdown()
    except Exception:
        pass

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    lifespan=lifespan
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

from fastapi.staticfiles import StaticFiles
from app.routes import webhook, auth, dashboard

app.include_router(webhook.router, tags=["Webhook"])
app.include_router(auth.router)
app.include_router(dashboard.router)

# Cria o diretório estático se não existir
os.makedirs("app/static/admin", exist_ok=True)
app.mount("/admin/static", StaticFiles(directory="app/static/admin"), name="static")

@app.get("/admin")
async def serve_admin_dashboard():
    return FileResponse("app/static/admin/index.html")

@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.PROJECT_NAME}


@app.get("/")
async def root():
    """Servindo a Landing Page HTML do ZapReembolso na raiz."""
    static_html = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(static_html):
        return FileResponse(static_html)
    return JSONResponse({
        "app": settings.PROJECT_NAME,
        "status": "online",
        "wuzapi": settings.WUZAPI_BASE_URL
    })
