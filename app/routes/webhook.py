import uuid
import json
import random
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.config import settings
from app.models import User, Company, UserRole, PlanType, Expense, ExpenseStatus
from app.services.wuzapi_service import wuzapi_client
from app.services.chatbot_service import chatbot_service
from app.services.humanizer_service import send_humanized_message
from app.services.command_handler import command_handler
from app.services.expense_service import expense_service
from app.services.onboarding_service import onboarding_service
from app.limiter import limiter
from datetime import datetime, timedelta, timezone
import logging

logger = logging.getLogger("webhook")

router = APIRouter(prefix="/webhook", tags=["Webhook"])


@router.post("/wuzapi")
@limiter.limit("30/minute")
async def handle_wuzapi_webhook(request: Request, token: str = "", db: AsyncSession = Depends(get_db)):
    """Recebe mensagens do WuzAPI e orquestra o onboarding e gestão de comprovantes."""
    # Validação do token de segurança
    if not settings.DEBUG:
        if not settings.WEBHOOK_SECRET or settings.WEBHOOK_SECRET == "change_me_in_production":
            raise HTTPException(status_code=500, detail="Webhook secret is not configured in production environment")
        if token != settings.WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Unauthorized webhook token")
    else:
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
        logger.error(f"Erro ao ler Payload: {e}")
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
            logger.warning(f"Falha ao parsear jsonData: {json_data_str[:200]}")
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

        # Log compacto (sem JPEGThumbnail/base64 que são enormes)
        if has_media:
            media_info = message.get("imageMessage") or message.get("documentMessage") or {}
            logger.info(f"MÍDIA RECEBIDA | URL: {media_info.get('URL', 'N/A')[:80]}... | mediaKey: {media_info.get('mediaKey', 'N/A')} | mime: {media_info.get('mimetype', 'N/A')} | size: {media_info.get('fileLength', 'N/A')}")

        logger.info(f"Mensagem recebida | Phone: {phone} | Texto: '{text}' | PushName: {info.get('PushName', 'N/A')} | HasMedia: {has_media}")

    else:
        # Fallback: formato genérico (caso o WuzAPI mude ou outro provedor)
        phone = data.get("Phone") or data.get("from")
        text = data.get("Body") or data.get("text", "")
        image_base64 = data.get("ImageBase64") or data.get("media_base64")

    if not phone:
        return {"status": "ignored", "reason": "No phone number extracted"}

    phone = str(phone).replace("@s.whatsapp.net", "").replace("+", "").strip()
    clean_text = text.strip() if text else ""

    if not clean_text and not has_media:
        return {"status": "ignored", "reason": "Empty message and no media"}

    # 1. Busca ou cria o registro inicial do Usuário
    user_query = select(User).where(User.phone == phone)
    res = await db.execute(user_query)
    user = res.scalar_one_or_none()

    if not user:
        user = User(phone=phone, name=None, role=UserRole.EMPLOYEE, onboarding_step=None, is_approved=True)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    # Verifica Timeout de Onboarding
    was_reset = await onboarding_service.check_onboarding_timeout(user, phone, db)
    if was_reset:
        return {"status": "ok"}

    # 2. Comando do Gestor para Aprovar/Recusar cadastro de funcionário (Suporta 1, 01, 2, 02, ACEITAR, RECUSAR)
    raw_upper = clean_text.upper().strip()
    if user.role == UserRole.ADMIN and user.company_id:
        if raw_upper.startswith("ACEITAR") or raw_upper.startswith("RECUSAR") or raw_upper in ["1", "01", "2", "02"]:
            comp_query = select(Company).where(Company.id == user.company_id)
            comp_res = await db.execute(comp_query)
            company = comp_res.scalar_one_or_none()
            if company:
                pending_users_query = select(User).where(User.company_id == company.id, User.is_approved == False)
                pending_users_res = await db.execute(pending_users_query)
                has_pending_users = len(pending_users_res.scalars().all()) > 0
                
                is_shortcut = raw_upper in ["1", "01", "2", "02"]
                
                if is_shortcut and has_pending_users:
                    # Verifica se há despesas pendentes para evitar conflito de atalho
                    pending_expenses_query = select(Expense).where(Expense.company_id == company.id, Expense.status == ExpenseStatus.PENDING)
                    pending_expenses_res = await db.execute(pending_expenses_query)
                    has_pending_expenses = len(pending_expenses_res.scalars().all()) > 0
                    
                    if has_pending_expenses:
                        await wuzapi_client.send_text_message(
                            phone, 
                            "⚠️ Você tem **funcionários** e **despesas** aguardando aprovação.\n\n"
                            "Por favor, use os comandos completos para evitar confusão:\n"
                            "• Para aprovar funcionário: *ACEITAR [telefone]*\n"
                            "• Para aprovar despesa: *APROVAR [ID]*"
                        )
                        return {"status": "ok"}
                
                if has_pending_users or raw_upper.startswith("ACEITAR") or raw_upper.startswith("RECUSAR"):
                    if is_shortcut or raw_upper.startswith("ACEITAR") or raw_upper.startswith("RECUSAR"):
                        return await command_handler.handle_aceitar_recusar(clean_text, phone, user, company, db)

    # 3. MÁQUINA DE ESTADOS DO LEAD (Onboarding iugu-Style)
    if user.onboarding_step and user.onboarding_step.startswith("LEAD_"):
        return await onboarding_service.handle_lead_onboarding(user, clean_text, phone, db)

    # 4. MENU PRINCIPAL (Opção 1, 2 ou 3)
    if user.onboarding_step == "MAIN_MENU":
        return await onboarding_service.handle_main_menu(user, clean_text, phone, db)

    # 5. MÁQUINA DE ESTADOS DO FUNCIONÁRIO (Employee Wizard)
    if user.onboarding_step and user.onboarding_step.startswith("EMP_"):
        return await onboarding_service.handle_employee_onboarding(user, clean_text, phone, db)

    # 6. MÁQUINA DE ESTADOS DA EMPRESA/GESTOR (Company Wizard)
    if user.onboarding_step and user.onboarding_step.startswith("COMP_"):
        return await onboarding_service.handle_company_onboarding(user, clean_text, phone, db)

    # 6.5 CONFIRMAÇÃO DE AÇÕES
    if user.onboarding_step and user.onboarding_step.startswith("CONFIRM_"):
        if clean_text.upper().strip() in ["SIM", "S", "Y", "YES"]:
            action_parts = user.onboarding_step.split("_", 2)
            action = action_parts[1]
            target_id = action_parts[2]
            
            user.onboarding_step = None
            
            # Buscar company para usar nos handlers
            confirm_comp = None
            if user.company_id:
                confirm_comp_query = select(Company).where(Company.id == user.company_id)
                confirm_comp_res = await db.execute(confirm_comp_query)
                confirm_comp = confirm_comp_res.scalar_one_or_none()
            
            if action in ["APROVAR", "REJEITAR"]:
                return await command_handler.handle_aprovar_rejeitar(f"{action} {target_id}", phone, user, confirm_comp, db, bypass_confirm=True)
            elif action in ["ACEITAR", "RECUSAR"]:
                return await command_handler.handle_aceitar_recusar(f"{action} {target_id}", phone, user, confirm_comp, db, bypass_confirm=True)
        elif clean_text.upper().strip() in ["CANCELAR", "NÃO", "NAO", "N"]:
            user.onboarding_step = None
            await db.commit()
            await wuzapi_client.send_text_message(phone, "🚫 Ação cancelada.")
            return {"status": "ok"}
        else:
            await wuzapi_client.send_text_message(phone, "⚠️ Por favor, responda *SIM* para confirmar ou *CANCELAR* para abortar.")
            return {"status": "ok"}

    # 7. Inicialização do Comando CRIAR Empresa (Atalho direto)
    if clean_text.upper().startswith("CRIAR"):
        return await command_handler.handle_criar(clean_text, phone, user, db)

    # Menu de Ajuda
    if clean_text.upper() in ["AJUDA", "MENU", "HELP"]:
        return await command_handler.handle_ajuda(phone, user)

    # 8. Comando de Vinculação Manual (#CODIGO)
    if clean_text.startswith("#") or clean_text.upper().startswith("ENTRAR"):
        return await command_handler.handle_vincular(clean_text, phone, user, db)

    # 9. Usuário sem cadastro completo -> Inicia o fluxo iugu de Boas-Vindas
    if not user.company_id:
        if not user.name:
            user.onboarding_step = "LEAD_NAME"
            await db.commit()
            welcome_intro = (
                "Olá! 🤗\n"
                "Somos o *ZapReembolso*, a plataforma inteligente de gestão e reembolso de despesas corporativas pelo WhatsApp.\n\n"
                "Antes de começarmos, gostaria de entender um pouco sobre você e o seu negócio.\n\n"
                "Qual é o seu *Nome Completo*?"
            )
            await wuzapi_client.send_text_message(phone, welcome_intro)
            return {"status": "ok"}
        elif not user.email:
            user.onboarding_step = "LEAD_EMAIL"
            await db.commit()
            await wuzapi_client.send_text_message(
                phone,
                f"Olá, *{user.name}*! 🤝 Pode me confirmar o seu *E-mail*? (ex: _nome@empresa.com.br_)"
            )
            return {"status": "ok"}
        else:
            user.onboarding_step = "MAIN_MENU"
            await db.commit()
            menu_msg = (
                f"Como posso te ajudar hoje, *{user.name}*?\n\n"
                f"1️⃣ *Quero cadastrar minha Empresa / Prefeitura* (Sou Gestor)\n"
                f"2️⃣ *Quero me vincular à uma empresa* (Sou Funcionário)\n"
                f"3️⃣ *Preciso de ajuda ou suporte*\n\n"
                f"Digite *1*, *2* ou *3* para escolher:"
            )
            await wuzapi_client.send_text_message(phone, menu_msg)
            return {"status": "ok"}

    # 8. Usuário Vinculado mas PENDENTE de aprovação pelo Gestor
    if not user.is_approved:
        comp_query = select(Company).where(Company.id == user.company_id)
        comp_res = await db.execute(comp_query)
        company = comp_res.scalar_one_or_none()
        c_name = company.name if company else "Sua empresa"

        await wuzapi_client.send_text_message(
            phone,
            f"⏳ **Cadastro Pendente de Aprovação!**\n\n"
            f"Sua solicitação de vínculo com a empresa **{c_name}** foi enviada ao seu gestor e está aguardando a liberação dele.\n"
            f"Assim que ele aprovar, você poderá enviar seus cupons fiscais."
        )
        return {"status": "ok"}

    # Busca os dados da empresa cadastrada
    comp_query = select(Company).where(Company.id == user.company_id)
    comp_res = await db.execute(comp_query)
    company = comp_res.scalar_one_or_none()

    # Verificação de Vencimento do Plano de Teste / Assinatura
    if company and company.trial_ends_at:
        now_utc = datetime.now(timezone.utc)
        if company.trial_ends_at <= now_utc and company.subscription_status != "ACTIVE":
            company.subscription_status = "EXPIRED"
            await db.commit()

    if company and company.subscription_status == "EXPIRED":
        if user.role == UserRole.EMPLOYEE:
            await wuzapi_client.send_text_message(
                phone,
                f"⚠️ *Serviço Pausado Temporariamente*\n\n"
                f"A assinatura da empresa *{company.name}* está pendente de renovação com o gestor.\n"
                f"Por favor, peça ao seu gestor para realizar a renovação via Pix pelo WhatsApp para liberar o envio de comprovantes!"
            )
            return {"status": "ok"}
        elif user.role == UserRole.ADMIN:
            from app.services.efi_service import efi_pay_service
            pix_data = await efi_pay_service.create_pix_cob(
                company_name=company.name,
                cnpj_or_cpf=company.cnpj or "00000000000000",
                amount=float(company.monthly_price or 99.0)
            )
            billing_msg = efi_pay_service.format_pix_whatsapp_message(
                company_name=company.name,
                plan_name=company.estimated_employees or "Plano Corporativo",
                amount=float(company.monthly_price or 99.0),
                pix_data=pix_data,
                is_expired=True
            )
            await wuzapi_client.send_text_message(phone, billing_msg)
            return {"status": "ok"}

    # Comandos de lançamento manual (Despesa sem recibo e KM)
    if clean_text.upper().startswith("DESPESA"):
        return await command_handler.handle_despesa(clean_text, phone, user, company, db)

    if clean_text.upper().startswith("KM"):
        return await command_handler.handle_km(clean_text, phone, user, company, db)

    if clean_text.upper().startswith("LIMITE"):
        return await command_handler.handle_limite(clean_text, phone, user, company, db)

    if clean_text.upper() == "EXPORTAR":
        return await command_handler.handle_exportar(clean_text, phone, user, company, db)

    # 5. Comando "RELATORIO" (suporta paginação: RELATORIO 2)
    if clean_text.upper().startswith("RELATORIO"):
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

