import uuid
import json
import random
from fastapi import APIRouter, Depends, Request, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.database import get_db, AsyncSessionLocal
from app.config import settings
from app.models import User, Company, UserRole, PlanType, Expense, ExpenseStatus
from app.services.wuzapi_service import wuzapi_client
from app.services.chatbot_service import chatbot_service
from app.services.humanizer_service import send_humanized_message
from app.services.command_handler import command_handler
from app.services.expense_service import expense_service
from app.services.onboarding_service import onboarding_service
from app.services.menu_service import menu_service
from app.limiter import limiter
from datetime import datetime, timedelta, timezone
import logging

logger = logging.getLogger("webhook")

router = APIRouter(prefix="/webhook", tags=["Webhook"])


@router.post("/wuzapi")
@limiter.limit("30/minute")
async def handle_wuzapi_webhook(request: Request, background_tasks: BackgroundTasks, token: str = "", db: AsyncSession = Depends(get_db)):
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

    # 2. Comando do Gestor para Aprovação/Recusa (Suporta 1, 01, 2, 02, ACEITAR, RECUSAR, APROVAR, REJEITAR)
    raw_upper = clean_text.upper().strip()
    if user.role == UserRole.ADMIN and user.company_id:
        is_user_cmd = raw_upper.startswith("ACEITAR") or raw_upper.startswith("RECUSAR")
        is_exp_cmd = raw_upper.startswith("APROVAR") or raw_upper.startswith("REJEITAR")
        is_shortcut = raw_upper in ["1", "01", "2", "02"]

        if is_user_cmd or is_exp_cmd or is_shortcut:
            comp_query = select(Company).where(Company.id == user.company_id)
            comp_res = await db.execute(comp_query)
            company = comp_res.scalar_one_or_none()
            if company:
                if is_user_cmd:
                    return await command_handler.handle_aceitar_recusar(clean_text, phone, user, company, db)
                elif is_exp_cmd:
                    return await command_handler.handle_aprovar_rejeitar(clean_text, phone, user, company, db)
                elif is_shortcut:
                    pending_users_query = select(User).where(User.company_id == company.id, User.is_approved == False)
                    pending_users_res = await db.execute(pending_users_query)
                    has_pending_users = len(pending_users_res.scalars().all()) > 0

                    pending_expenses_query = select(Expense).where(Expense.company_id == company.id, Expense.status == ExpenseStatus.PENDING)
                    pending_expenses_res = await db.execute(pending_expenses_query)
                    has_pending_expenses = len(pending_expenses_res.scalars().all()) > 0

                    if has_pending_users and has_pending_expenses:
                        await wuzapi_client.send_text_message(
                            phone, 
                            "⚠️ Você tem **funcionários** e **despesas** aguardando aprovação.\n\n"
                            "Por favor, use os comandos completos para evitar confusão:\n"
                            "• Para aprovar funcionário: *ACEITAR [telefone]*\n"
                            "• Para aprovar despesa: *APROVAR [ID]*"
                        )
                        return {"status": "ok"}
                    elif has_pending_expenses:
                        return await command_handler.handle_aprovar_rejeitar(clean_text, phone, user, company, db)
                    elif has_pending_users:
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

    # 6.6 MENUS INTERATIVOS (MENU_*)
    if user.onboarding_step and user.onboarding_step.startswith("MENU_"):
        # Permite cancelar a qualquer momento
        if clean_text.upper().strip() in ["CANCELAR", "SAIR"]:
            user.onboarding_step = None
            await db.commit()
            await wuzapi_client.send_text_message(phone, "🚫 Operação cancelada.")
            return await menu_service.send_main_menu(phone, user, db)

        if user.onboarding_step == "MENU_MAIN":
            return await menu_service.handle_main_menu(user, clean_text, phone, company, db)
        elif user.onboarding_step == "MENU_LAUNCH":
            return await menu_service.handle_launch_menu(user, clean_text, phone, company, db)
        elif user.onboarding_step == "MENU_LAUNCH_KM":
            return await menu_service.handle_launch_km_step(user, clean_text, phone, company, db)
        elif user.onboarding_step == "MENU_LAUNCH_MANUAL_VAL":
            return await menu_service.handle_launch_manual_val_step(user, clean_text, phone, db)
        elif user.onboarding_step.startswith("MENU_LAUNCH_MANUAL_DESC_"):
            return await menu_service.handle_launch_manual_desc_step(user, clean_text, phone, company, db)
        elif user.onboarding_step == "MENU_APPROVAL":
            return await menu_service.handle_approval_menu(user, clean_text, phone, company, db)
        elif user.onboarding_step == "MENU_APPROVAL_ACCEPT":
            return await menu_service.handle_approval_accept_step(user, clean_text, phone, company, db)
        elif user.onboarding_step == "MENU_APPROVAL_REJECT_ID":
            return await menu_service.handle_approval_reject_id_step(user, clean_text, phone, db)
        elif user.onboarding_step.startswith("MENU_APPROVAL_REJECT_REASON_"):
            return await menu_service.handle_approval_reject_reason_step(user, clean_text, phone, company, db)
        elif user.onboarding_step == "MENU_TEAM":
            return await menu_service.handle_team_menu(user, clean_text, phone, company, db)
        elif user.onboarding_step == "MENU_TEAM_ACCEPT":
            return await menu_service.handle_team_accept_step(user, clean_text, phone, company, db)
        elif user.onboarding_step == "MENU_TEAM_REJECT":
            return await menu_service.handle_team_reject_step(user, clean_text, phone, company, db)
        elif user.onboarding_step == "MENU_TEAM_LIMIT_TEL":
            return await menu_service.handle_team_limit_tel_step(user, clean_text, phone, db)
        elif user.onboarding_step.startswith("MENU_TEAM_LIMIT_VAL_"):
            return await menu_service.handle_team_limit_val_step(user, clean_text, phone, company, db)
        elif user.onboarding_step == "MENU_REPORT":
            return await menu_service.handle_report_menu(user, clean_text, phone, company, db)
        elif user.onboarding_step == "REPORT_MENU": # Backwards compatibility for old state
            return await menu_service.handle_report_menu(user, clean_text, phone, company, db)

    # 7. Inicialização do Comando CRIAR Empresa (Atalho direto)
    if clean_text.upper().startswith("CRIAR"):
        return await command_handler.handle_criar(clean_text, phone, user, db)

    # Menu de Ajuda (Agora roteia para o Menu Principal interativo)
    if clean_text.upper() in ["AJUDA", "MENU", "HELP", "0"]:
        return await menu_service.send_main_menu(phone, user, db)

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
    if clean_text.upper() == "RELATORIO" or (user.role == UserRole.ADMIN and clean_text == "4"):
        return await menu_service.send_report_menu(phone, user, db)
    elif clean_text.upper().startswith("RELATORIO"):
        return await command_handler.handle_relatorio(clean_text, phone, user, company, db)

    # 6. Comando "APROVAR" e "REJEITAR"
    if clean_text.upper().startswith("APROVAR") or clean_text.upper().startswith("REJEITAR"):
        return await command_handler.handle_aprovar_rejeitar(clean_text, phone, user, company, db)

    # 7. Processamento de Imagem (Cupom Fiscal / Recibo) EM BACKGROUND (Evita Timeout/Retrys do WuzAPI)
    if image_base64 or (has_media and media_url and media_key):
        async def background_process_image(bg_media_url: str, bg_media_key: str, bg_media_type: str, bg_image_base64: str, bg_phone: str, bg_user_phone: str):
            async with AsyncSessionLocal() as bg_db:
                bg_user_query = select(User).where(User.phone == bg_user_phone)
                bg_res = await bg_db.execute(bg_user_query)
                bg_user = bg_res.scalar_one_or_none()
                
                bg_company = None
                if bg_user and bg_user.company_id:
                    bg_comp_query = select(Company).where(Company.id == bg_user.company_id)
                    bg_comp_res = await bg_db.execute(bg_comp_query)
                    bg_company = bg_comp_res.scalar_one_or_none()
                
                if not bg_user:
                    return

                if bg_image_base64:
                    await expense_service.process_image_receipt(bg_image_base64, bg_phone, bg_user, bg_company, bg_db)
                elif bg_media_url and bg_media_key:
                    import base64
                    media_bytes = await wuzapi_client.download_media(bg_media_url, bg_media_key, bg_media_type)
                    if media_bytes:
                        encoded = base64.b64encode(media_bytes).decode('utf-8')
                        await expense_service.process_image_receipt(encoded, bg_phone, bg_user, bg_company, bg_db)
                    else:
                        await wuzapi_client.send_text_message(bg_phone, "📸 Falhei ao processar a foto. Envie novamente.")

        background_tasks.add_task(background_process_image, media_url, media_key, media_type, image_base64, phone, user.phone)
        return {"status": "ok"}


    # 7.5. Atalhos Numéricos (Menu Rápido)
    if user and user.role == UserRole.ADMIN:
        if clean_text in ["1", "01", "2", "02"]:
            await wuzapi_client.send_text_message(phone, "❌ Você não tem despesas ou funcionários aguardando aprovação no momento.")
            return {"status": "ok"}
        elif clean_text == "3":
            from fastapi import Request
            painel_url = f"{request.base_url}admin" if request else "/admin"
            await wuzapi_client.send_text_message(phone, f"🌐 *Acesse o Painel Web:* {painel_url}")
            return {"status": "ok"}
        elif clean_text == "4":
            pass # Tratado acima (abre o REPORT_MENU)
        elif clean_text == "5":
            return await command_handler.handle_exportar("EXPORTAR", phone, user, company, db)
        elif clean_text == "6":
            return await command_handler.handle_ajuda(phone, user)

    # 8. Mensagem não reconhecida (Fallback / Ajuda / Interceptor IA)
    if clean_text:
        ai_response = await chatbot_service.generate_response(clean_text, user_role=user.role.value if user else None)
        
        if user and user.role == UserRole.ADMIN:
            admin_tips = (
                "\n\n🤖 *Para voltar ao Menu Principal:*\n"
                "Digite *MENU* a qualquer momento."
            )
            ai_response += admin_tips
            
        await send_humanized_message(phone, ai_response)

    return {"status": "ok"}

