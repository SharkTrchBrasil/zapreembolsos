import random
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from app.database import get_db
from app.models import User, UserRole
from app.limiter import limiter
import redis.asyncio as aioredis
from app.config import settings
from app.services.wuzapi_service import wuzapi_client
from app.security import create_access_token
import logging

logger = logging.getLogger("auth")
router = APIRouter(prefix="/api/auth", tags=["Auth"])

# Setup do Redis Assíncrono para OTP
redis_client = None
if settings.REDIS_URL:
    try:
        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception as e:
        logger.error(f"Erro ao conectar ao Redis para auth: {e}")

class RequestCodeRequest(BaseModel):
    phone: str

class VerifyCodeRequest(BaseModel):
    phone: str
    code: str

@router.post("/request-code")
async def request_code(req: RequestCodeRequest, db: AsyncSession = Depends(get_db)):
    if not redis_client:
        raise HTTPException(status_code=500, detail="Redis indisponível")
        
    phone = "".join(c for c in req.phone if c.isdigit())
    
    query = select(User).where(User.phone.like(f"%{phone[-9:]}%"), User.role == UserRole.ADMIN)
    result = await db.execute(query)
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(status_code=404, detail="Administrador não encontrado para este telefone.")
        
    otp = str(random.randint(100000, 999999))
    redis_key = f"auth_otp:{user.phone}"
    
    # Salva no redis por 5 minutos (300 segundos)
    await redis_client.setex(redis_key, 300, otp)
    
    # Envia via WhatsApp
    msg = (
        f"🔐 *Código de Acesso do Dashboard*\n\n"
        f"Seu código de login é: *{otp}*\n\n"
        f"Este código expira em 5 minutos. Nunca compartilhe com ninguém."
    )
    try:
        await wuzapi_client.send_text_message(user.phone, msg)
        return {"status": "ok", "message": "Código enviado para o WhatsApp do gestor."}
    except Exception as e:
        logger.error(f"Erro ao enviar OTP no whatsapp: {e}")
        raise HTTPException(status_code=500, detail="Erro ao enviar mensagem de WhatsApp")

@router.post("/verify-code")
async def verify_code(req: VerifyCodeRequest, db: AsyncSession = Depends(get_db)):
    if not redis_client:
        raise HTTPException(status_code=500, detail="Redis indisponível")
        
    phone = "".join(c for c in req.phone if c.isdigit())
    
    query = select(User).where(User.phone.like(f"%{phone[-9:]}%"), User.role == UserRole.ADMIN)
    result = await db.execute(query)
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
        
    redis_key = f"auth_otp:{user.phone}"
    saved_otp = await redis_client.get(redis_key)
    
    if not saved_otp:
        raise HTTPException(status_code=400, detail="Código expirado ou não solicitado.")
        
    if req.code.strip() != saved_otp:
        raise HTTPException(status_code=401, detail="Código inválido.")
        
    # Remove do redis após uso bem sucedido
    await redis_client.delete(redis_key)
    
    # Gera JWT
    access_token = create_access_token(data={"sub": user.phone})
    return {"access_token": access_token, "token_type": "bearer", "company_id": user.company_id, "name": user.name}
