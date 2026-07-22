import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.config import settings
import app.models
from app.database import init_db
from app.routes import webhook
from app.services.notification_service import run_daily_reminder_job

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup seguro com captura de exceções para garantir que a API nunca caia no boot
    try:
        await init_db()
        print("✅ Banco de dados inicializado com sucesso!")
    except Exception as e:
        print(f"⚠️ Alerta: Erro ao inicializar banco de dados no startup: {e}")

    try:
        scheduler.add_job(run_daily_reminder_job, 'cron', hour=8, minute=0)
        scheduler.start()
        print("🚀 ZapReembolso API iniciada e Scheduler ativo!")
    except Exception as e:
        print(f"⚠️ Alerta: Erro ao iniciar Scheduler: {e}")
    
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

app.include_router(webhook.router)

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
