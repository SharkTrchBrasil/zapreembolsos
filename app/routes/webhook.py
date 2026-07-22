import uuid
import json
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
    # Validação do token de segurança
    if settings.WEBHOOK_SECRET and settings.WEBHOOK_SECRET != "change_me_in_production":
        if token != settings.WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Unauthorized webhook token")

    # Lemos os bytes brutos
    try:
        body_bytes = await request.body()
        body_str = body_bytes.decode('utf-8')
        
        from urllib.parse import parse_qs
        parsed_body = parse_qs(body_str)
        
        if "jsonData" in parsed_body:
            # Pega o valor desempacotado da query string
            json_data_str = parsed_body["jsonData"][0]
            data = {"jsonData": json_data_str}
        else:
            # Fallback para JSON direto
            data = json.loads(body_str) if body_str else {}
            
    except Exception as e:
        print(f"Erro ao ler Payload: {e}")
        raise HTTPException(status_code=400, detail="Invalid payload")

    phone = None
    text = ""
    image_base64 = None

    # ========================================================
    # PARSING DO PAYLOAD DO WUZAPI
    # O WuzAPI envia: {"instanceName": "...", "jsonData": "<JSON stringificado>"}
    # Dentro de jsonData temos: {"event": {...}, "type": "Message"}
    # ========================================================

    json_data_str = data.get("jsonData")

    if json_data_str and isinstance(json_data_str, str):
        # Parseia o JSON interno (jsonData é uma string, não um objeto)
        try:
            inner = json.loads(json_data_str)
        except json.JSONDecodeError:
            print(f"⚠️ Falha ao parsear jsonData: {json_data_str[:200]}")
            return {"status": "ignored", "reason": "Invalid jsonData"}

        event_type = inner.get("type", "")

        # Ignora eventos que NÃO são mensagens (ex: ChatPresence, Receipt, etc.)
        if event_type != "Message":
            return {"status": "ignored", "reason": f"Event type '{event_type}' ignored"}

        event = inner.get("event", {})
        info = event.get("Info", {})
        message = event.get("Message", {})

        # --- Extraindo o número de telefone ---
        # SenderAlt tem o formato: 5533XXXXXXXX@s.whatsapp.net (número real)
        # Sender/Chat podem ter formato LID (271459817656435@lid) que não é útil
        sender_alt = info.get("SenderAlt", "")
        if sender_alt and "@s.whatsapp.net" in sender_alt:
            phone = sender_alt.split("@")[0].split(":")[0]
        else:
            # Fallback: tenta o Chat ou Sender removendo o sufixo
            raw = info.get("Chat", "") or info.get("Sender", "")
            if "@s.whatsapp.net" in raw:
                phone = raw.split("@")[0].split(":")[0]

        # Ignora mensagens enviadas por nós mesmos (IsFromMe)
        if info.get("IsFromMe", False):
            return {"status": "ignored", "reason": "Message from self"}

        # --- Extraindo o texto e detectando Mídia ---
        has_media = False
        text = ""
        media_url = None
        media_key = None
        media_type = "Image"

        # Em WuzAPI, a mídia pode vir de várias formas
        if "imageMessage" in message:
            has_media = True
            text = message["imageMessage"].get("caption", "")
            media_url = message["imageMessage"].get("URL")
            media_key = message["imageMessage"].get("mediaKey")
            media_type = "Image"
        elif "documentMessage" in message:
            has_media = True
            text = message["documentMessage"].get("caption", "")
            media_url = message["documentMessage"].get("URL")
            media_key = message["documentMessage"].get("mediaKey")
            media_type = "Document"
        elif "conversation" in message and message["conversation"]:
            text = message["conversation"]
        elif "extendedTextMessage" in message:
            text = message["extendedTextMessage"].get("text", "")

        # Se for mídia ou texto vazio, imprime o payload para debug
        if has_media or not text:
            print("\n=== PAYLOAD WUZAPI (MÍDIA/VAZIO) ===")
            print(json.dumps(inner, indent=2))
            print("====================================\n")

        print(f"📩 Mensagem recebida | Phone: {phone} | Texto: '{text}' | PushName: {info.get('PushName', 'N/A')} | HasMedia: {has_media}")

    else:
        # Fallback: formato genérico (caso o WuzAPI mude ou outro provedor)
        phone = data.get("Phone") or data.get("from")
        text = data.get("Body") or data.get("text", "")
        image_base64 = data.get("ImageBase64") or data.get("media_base64")

    if not phone:
        return {"status": "ignored", "reason": "No phone number extracted"}

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
    elif has_media:
        if media_url and media_key:
            import base64
            # Baixa a mídia nativamente
            media_bytes = await wuzapi_client.download_media(media_url, media_key, media_type)
            if media_bytes:
                image_base64_encoded = base64.b64encode(media_bytes).decode('utf-8')
                return await expense_service.process_image_receipt(image_base64_encoded, phone, user, company, db)
        
        # Se falhou ou não tinha url/key
        await wuzapi_client.send_text_message(
            phone, 
            "📸 Recebi sua imagem! Mas falhei ao processar a foto. Certifique-se de enviá-la novamente ou usar o comando: *DESPESA 50.00 Motivo*"
        )
        return {"status": "ok"}

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

