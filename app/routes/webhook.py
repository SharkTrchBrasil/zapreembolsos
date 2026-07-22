import uuid
import random
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.config import settings
from app.models import User, Company, UserRole
from app.services.wuzapi_service import wuzapi_client
from app.services.chatbot_service import chatbot_service
from app.services.humanizer_service import send_humanized_message
from app.services.command_handler import command_handler
from app.services.expense_service import expense_service

router = APIRouter(prefix="/webhook", tags=["Webhook"])

@router.post("/wuzapi")
async def handle_wuzapi_webhook(request: Request, token: str = "", db: AsyncSession = Depends(get_db)):
    """Recebe mensagens do WuzAPI e orquestra o onboarding e gestão de comprovantes."""
    # Se houver um WEBHOOK_SECRET definido nas variáveis (que não o padrão), exigimos o token.
    if settings.WEBHOOK_SECRET and settings.WEBHOOK_SECRET != "change_me_in_production":
        if token != settings.WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Unauthorized webhook token")

    try:
        data = await request.json()
        print("\n\n=== WEBHOOK PAYLOAD RECEBIDO ===")
        print(data)
        print("================================\n\n")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    phone = None
    text = ""
    image_base64 = None

    # O WuzAPI normalmente envia uma lista de eventos ou um dicionário estruturado.
    # Vamos tentar extrair os dados de algumas estruturas comuns:
    if isinstance(data, list) and len(data) > 0:
        event = data[0]
    else:
        event = data

    if isinstance(event, dict):
        # Padrão genérico/antigo WuzAPI ou Z-API / Evolution
        phone = event.get("Phone") or event.get("from")
        text = event.get("Body") or event.get("text", "")
        image_base64 = event.get("ImageBase64") or event.get("media_base64")
        
        # Padrão nativo Baileys (WuzAPI events)
        if "data" in event and isinstance(event["data"], dict):
            msg_data = event["data"]
            # Extraindo número
            if "key" in msg_data and "remoteJid" in msg_data["key"]:
                phone = msg_data["key"]["remoteJid"].split("@")[0]
            elif "pushName" in msg_data: # Fallback genérico
                phone = event.get("instanceId") # Só para ter um fallback, ideal é remoteJid

            # Extraindo texto
            if "message" in msg_data:
                msg = msg_data["message"]
                if "conversation" in msg:
                    text = msg["conversation"]
                elif "extendedTextMessage" in msg and "text" in msg["extendedTextMessage"]:
                    text = msg["extendedTextMessage"]["text"]
                elif "imageMessage" in msg and "caption" in msg["imageMessage"]:
                    text = msg["imageMessage"]["caption"]

    if not phone:
        print("⚠️ Nenhuma mensagem ou número de telefone extraído. Ignorando evento.")
        return {"status": "ignored", "reason": "No phone number"}

    phone = str(phone).replace("@s.whatsapp.net", "").replace("+", "").strip()
    clean_text = text.strip() if text else ""

    # 1. Busca ou cria o registro inicial do Usuário
    user_query = select(User).where(User.phone == phone)
    res = await db.execute(user_query)
    user = res.scalar_one_or_none()

    if not user:
        user = User(phone=phone, name="Novo Usuário", role=UserRole.EMPLOYEE)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    # 2. Comando: CRIAR [Nome da Empresa] (Para Gestores)
    if clean_text.upper().startswith("CRIAR"):
        return await command_handler.handle_criar(clean_text, phone, user, db)

    # 3. Comando: Vincular via Código (ex: #ALFA123 ou #ALFA)
    if clean_text.startswith("#") or clean_text.upper().startswith("ENTRAR"):
        return await command_handler.handle_vincular(clean_text, phone, user, db)

    # 4. Verifica se o usuário já possui empresa vinculada
    if not user.company_id:
        unlinked_msg = (
            "👋 **Bem-vindo ao ZapReembolso!**\n\n"
            "Não encontrei nenhuma empresa vinculada ao seu número.\n\n"
            "👉 **Se você é Funcionário:**\n"
            "Digite o Código da sua empresa (ex: `#ALFA12`) fornecido pelo seu gestor.\n\n"
            "👉 **Se você é Gestor/Dono de Empresa:**\n"
            "Digite *CRIAR Nome da Sua Empresa* para cadastrar sua empresa agora!"
        )
        await wuzapi_client.send_text_message(phone, unlinked_msg)
        return {"status": "ok"}

    # Busca os dados da empresa cadastrada
    comp_query = select(Company).where(Company.id == user.company_id)
    comp_res = await db.execute(comp_query)
    company = comp_res.scalar_one_or_none()

    # Comandos de lançamento manual (Despesa sem recibo e KM)
    if clean_text.upper().startswith("DESPESA"):
        return await command_handler.handle_despesa(clean_text, phone, user, company, db)

    if clean_text.upper().startswith("KM"):
        return await command_handler.handle_km(clean_text, phone, user, company, db)

    if clean_text.upper().startswith("LIMITE"):
        return await command_handler.handle_limite(clean_text, phone, user, company, db)

    if clean_text.upper() == "EXPORTAR":
        return await command_handler.handle_exportar(clean_text, phone, user, company, db)

    # 5. Comando "RELATORIO"
    if clean_text.upper() == "RELATORIO":
        return await command_handler.handle_relatorio(clean_text, phone, user, company, db)

    # 6. Comando "APROVAR" e "REJEITAR"
    if clean_text.upper().startswith("APROVAR") or clean_text.upper().startswith("REJEITAR"):
        return await command_handler.handle_aprovar_rejeitar(clean_text, phone, user, company, db)

    # 7. Processamento de Imagem (Cupom Fiscal / Recibo)
    if image_base64:
        return await expense_service.process_image_receipt(image_base64, phone, user, company, db)

    # 8. Mensagem não reconhecida (Fallback / Ajuda / Interceptor IA)
    if clean_text:
        ai_response = await chatbot_service.generate_response(clean_text)
        
        if user.role == UserRole.ADMIN:
            admin_tips = (
                "\n\n🤖 *Dica de Gestor:*\n"
                "- `RELATORIO`\n"
                "- `APROVAR [ID]`\n"
                "- `REJEITAR [ID]`"
            )
            ai_response += admin_tips
            
        await send_humanized_message(phone, ai_response)

    return {"status": "ok"}

