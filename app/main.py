from contextlib import asynccontextmanager
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.config import settings
import app.models
from app.database import init_db
from app.routes import webhook
from app.services.notification_service import run_daily_reminder_job

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    
    # Agenda o Job de Lembretes Diários para rodar todo dia às 08:00 AM
    scheduler.add_job(run_daily_reminder_job, 'cron', hour=8, minute=0)
    scheduler.start()
    print("🚀 ZapReembolso API iniciada e Scheduler ativo!")
    
    yield
    
    # Shutdown
    scheduler.shutdown()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(webhook.router)

@app.get("/")
async def root():
    return {
        "app": settings.PROJECT_NAME,
        "status": "online",
        "wuzapi": settings.WUZAPI_BASE_URL
    }
