import uuid
import json
import random
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.config import settings
from app.models import User, Company, UserRole, PlanType
from app.services.wuzapi_service import wuzapi_client
from app.services.chatbot_service import chatbot_service
from app.services.humanizer_service import send_humanized_message
from app.services.command_handler import command_handler
from app.services.expense_service import expense_service
from datetime import datetime, timedelta

router = APIRouter(prefix="/webhook", tags=["Webhook"])

# Cache em memória para evitar loop infinito com outros robôs (ex: Gringo)
welcome_sent_cache = {}

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

        # Log compacto (sem JPEGThumbnail/base64 que são enormes)
        if has_media:
            media_info = message.get("imageMessage") or message.get("documentMessage") or {}
            print(f"\n📷 MÍDIA RECEBIDA | URL: {media_info.get('URL', 'N/A')[:80]}... | mediaKey: {media_info.get('mediaKey', 'N/A')} | mime: {media_info.get('mimetype', 'N/A')} | size: {media_info.get('fileLength', 'N/A')}")

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

    # 2. Comando do Gestor para Aprovar/Recusar cadastro de funcionário
    if clean_text.upper().startswith("ACEITAR") or clean_text.upper().startswith("RECUSAR"):
        comp_query = select(Company).where(Company.id == user.company_id)
        comp_res = await db.execute(comp_query)
        company = comp_res.scalar_one_or_none()
        if company:
            return await command_handler.handle_aceitar_recusar(clean_text, phone, user, company, db)

    # 3. MÁQUINA DE ESTADOS DO LEAD (Onboarding iugu-Style)
    if user.onboarding_step and user.onboarding_step.startswith("LEAD_"):
        if user.onboarding_step == "LEAD_NAME":
            user.name = clean_text.strip()
            user.onboarding_step = "LEAD_EMAIL"
            await db.commit()
            await wuzapi_client.send_text_message(
                phone,
                f"Olá, *{user.name}*! 🤝 Pode me confirmar o seu *E-mail*? (ex: _nome@empresa.com.br_)"
            )
            return {"status": "ok"}

        elif user.onboarding_step == "LEAD_EMAIL":
            user.email = clean_text.strip()
            user.onboarding_step = "MAIN_MENU"
            await db.commit()
            
            menu_msg = (
                f"Muito obrigado, *{user.name}*! Como posso te ajudar hoje?\n\n"
                f"1️⃣ *Quero cadastrar minha Empresa / Prefeitura* (Sou Gestor)\n"
                f"2️⃣ *Quero me vincular à uma empresa* (Sou Funcionário)\n"
                f"3️⃣ *Preciso de ajuda ou suporte*\n\n"
                f"Digite *1*, *2* ou *3* para escolher:"
            )
            await wuzapi_client.send_text_message(phone, menu_msg)
            return {"status": "ok"}

    # 4. MENU PRINCIPAL (Opção 1, 2 ou 3)
    if user.onboarding_step == "MAIN_MENU":
        cmd = clean_text.strip().lower()
        if cmd in ["1", "gestor", "empresa", "dono", "cadastrar empresa"]:
            user.role = UserRole.ADMIN
            user.onboarding_step = "COMP_NAME"
            await db.commit()
            await wuzapi_client.send_text_message(
                phone,
                f"🏢 Excelente, *{user.name or ''}*! Qual é o *Nome Fantasia ou Razão Social* da sua empresa ou órgão público?"
            )
            return {"status": "ok"}

        elif cmd in ["2", "funcionario", "funcionário", "vincular"]:
            user.role = UserRole.EMPLOYEE
            user.onboarding_step = "EMP_DEPT"
            await db.commit()
            await wuzapi_client.send_text_message(
                phone,
                f"Perfeito! 👤 Qual é o seu *Setor ou Secretaria* na empresa? (ex: _Obras, Saúde, Vendas, Financeiro_)"
            )
            return {"status": "ok"}

        elif cmd in ["3", "ajuda", "suporte"]:
            await wuzapi_client.send_text_message(
                phone,
                "Para suporte ou dúvidas com nossos especialistas, você também pode acessar nosso portal:\nhttps://zapreembolso.com.br/suporte\n\nDigite *1* para cadastrar empresa ou *2* para entrar como funcionário:"
            )
            return {"status": "ok"}
        else:
            menu_msg = (
                f"Como posso te ajudar hoje, *{user.name or ''}*?\n\n"
                f"1️⃣ *Quero cadastrar minha Empresa / Prefeitura* (Sou Gestor)\n"
                f"2️⃣ *Quero me vincular à uma empresa* (Sou Funcionário)\n"
                f"3️⃣ *Preciso de ajuda ou suporte*\n\n"
                f"Digite *1*, *2* ou *3* para escolher:"
            )
            await wuzapi_client.send_text_message(phone, menu_msg)
            return {"status": "ok"}

    # 5. MÁQUINA DE ESTADOS DO FUNCIONÁRIO (Employee Wizard)
    if user.onboarding_step and user.onboarding_step.startswith("EMP_"):
        if user.onboarding_step == "EMP_DEPT":
            user.department = clean_text.strip()
            user.onboarding_step = "EMP_ROLE"
            await db.commit()
            await wuzapi_client.send_text_message(
                phone, 
                f"Excelente! Qual é a sua *Profissão ou Cargo*? (ex: _Engenheiro, Motorista, Fiscal, Consultor_)"
            )
            return {"status": "ok"}

        elif user.onboarding_step == "EMP_ROLE":
            user.job_title = clean_text.strip()
            user.onboarding_step = "EMP_CODE"
            await db.commit()
            await wuzapi_client.send_text_message(
                phone, 
                f"Perfeito! 📝\n\nAgora para vincular sua conta à sua empresa ou prefeitura, informe:\n"
                f"👉 O *Código da Empresa* (ex: `#ALFA12`), ou\n"
                f"👉 O *Telefone do seu Gestor/Empresa*."
            )
            return {"status": "ok"}

        elif user.onboarding_step == "EMP_CODE":
            raw_input = clean_text.replace("#", "").replace("+", "").replace("-", "").strip()
            
            # Limpa dígitos para busca flexível do telefone (com ou sem DDD, com ou sem 9º dígito, com ou sem DDI 55)
            clean_digits = "".join(c for c in raw_input if c.isdigit())
            search_digits = clean_digits[-8:] if len(clean_digits) >= 8 else clean_digits

            if search_digits:
                comp_query = select(Company).where(
                    (Company.code == raw_input.upper()) | 
                    (Company.admin_phone.like(f"%{search_digits}%"))
                )
            else:
                comp_query = select(Company).where(Company.code == raw_input.upper())

            comp_res = await db.execute(comp_query)
            target_company = comp_res.scalars().first()

            if target_company:
                user.company_id = target_company.id
                user.role = UserRole.EMPLOYEE
                user.is_approved = False # Exige aprovação do gestor
                user.onboarding_step = None
                await db.commit()

                # Notifica o Gestor no WhatsApp
                admin_alert = (
                    f"👤 *Solicitação de Cadastro - ZapReembolso*\n"
                    f"Um novo funcionário solicitou vínculo à sua empresa:\n\n"
                    f"👤 *Nome:* {user.name}\n"
                    f"📧 *E-mail:* {user.email or 'Não informado'}\n"
                    f"🏢 *Setor:* {user.department}\n"
                    f"💼 *Cargo:* {user.job_title}\n"
                    f"📱 *WhatsApp:* {user.phone}\n\n"
                    f"----------------------------------\n"
                    f"Responda este chat para autorizar:\n"
                    f"1 - ✅ *ACEITAR*\n"
                    f"2 - ❌ *RECUSAR*"
                )
                await wuzapi_client.send_text_message(target_company.admin_phone, admin_alert)

                # Notifica o Funcionário
                await wuzapi_client.send_text_message(
                    phone,
                    f"⏳ *Solicitação enviada com sucesso!*\n\n"
                    f"Seus dados (*{user.name} - {user.job_title}*) foram enviados para o gestor da empresa *{target_company.name}*.\n"
                    f"Assim que ele aprovar seu cadastro, você receberá uma notificação aqui e poderá enviar seus comprovantes!"
                )
                return {"status": "ok"}
            else:
                await wuzapi_client.send_text_message(
                    phone,
                    f"❌ Empresa não encontrada para o código ou telefone `{clean_text}`.\n"
                    f"Por favor, verifique o código com seu gestor e tente novamente:"
                )
                return {"status": "ok"}

    # 6. MÁQUINA DE ESTADOS DA EMPRESA/GESTOR (Company Wizard)
    if user.onboarding_step and user.onboarding_step.startswith("COMP_"):
        comp_query = select(Company).where(Company.id == user.company_id)
        comp_res = await db.execute(comp_query)
        comp = comp_res.scalar_one_or_none()

        if user.onboarding_step == "COMP_NAME":
            company_name = clean_text.strip()
            from app.services.command_handler import generate_company_code
            code = generate_company_code(company_name)
            new_company = Company(
                id=str(uuid.uuid4()),
                code=code,
                name=company_name,
                admin_phone=phone,
                admin_name=user.name,
                billing_email=user.email,
                plan=PlanType.FREE_TRIAL
            )
            db.add(new_company)
            user.company_id = new_company.id
            user.role = UserRole.ADMIN
            user.onboarding_step = "COMP_CNPJ"
            await db.commit()

            await wuzapi_client.send_text_message(
                phone,
                f"Me informe o *CNPJ* da empresa. (Digite apenas números ou com pontuação. Ex: 09.134.593/0001-53):"
            )
            return {"status": "ok"}

        elif user.onboarding_step == "COMP_CNPJ":
            clean_cnpj = "".join(c for c in clean_text if c.isdigit())
            if len(clean_cnpj) != 14:
                await wuzapi_client.send_text_message(
                    phone,
                    "⚠️ *Por favor, informe um CNPJ válido, usando apenas os 14 números.* (Exp: 15111975000164)"
                )
                return {"status": "ok"}

            if comp:
                comp.cnpj = clean_text.strip()
            user.onboarding_step = "COMP_TYPE"
            await db.commit()
            
            type_menu = (
                "Certo, e qual o tipo/porte da sua empresa?\n\n"
                "1️⃣ *MEI / Microempresa*\n"
                "2️⃣ *Pequena Empresa* (até 10 funcionários)\n"
                "3️⃣ *Média Empresa* (10 a 50 funcionários)\n"
                "4️⃣ *Grande Empresa / Prefeitura* (50 a 500+ funcionários)\n\n"
                "Digite *1*, *2*, *3* ou *4*:"
            )
            await wuzapi_client.send_text_message(phone, type_menu)
            return {"status": "ok"}

        elif user.onboarding_step == "COMP_TYPE":
            type_map = {
                "1": "MEI / Microempresa",
                "2": "Pequena Empresa (1-10)",
                "3": "Média Empresa (10-50)",
                "4": "Grande Empresa / Prefeitura (50-500+)"
            }
            size_val = type_map.get(clean_text.strip(), clean_text.strip())
            if comp:
                comp.estimated_employees = size_val
            user.onboarding_step = None
            await db.commit()

            code = comp.code if comp else "N/A"
            c_name = comp.name if comp else "Sua Empresa"

            welcome_admin = (
                f"🎉 *Cadastro da Empresa {c_name} Concluído con Sucesso!*\n\n"
                f"🏢 *Empresa:* {c_name}\n"
                f"📄 *CNPJ:* {comp.cnpj if comp else 'Não informado'}\n"
                f"🔑 *Código da Empresa:* `#{code}`\n"
                f"👤 *Gestor Responsável:* {user.name}\n"
                f"📧 *E-mail:* {user.email or 'Não informado'}\n"
                f"👥 *Porte:* {size_val}\n\n"
                f"📢 *Como adicionar funcionários:*\n"
                f"Passe o código `#{code}` para seus funcionários ou peça para eles enviarem o seu telefone no primeiro acesso!\n\n"
                f"💡 *Seus Comandos de Gestor:*\n"
                f"• Envie *RELATORIO* para ver gastos do mês.\n"
                f"• Envie *APROVAR [ID]* ou apenas *1* para aprovar reembolsos.\n"
                f"• Envie *ACEITAR [Telefone]* para aprovar novos funcionários."
            )
            await wuzapi_client.send_text_message(phone, welcome_admin)
            return {"status": "ok"}

    # 7. Inicialização do Comando CRIAR Empresa (Atalho direto)
    if clean_text.upper().startswith("CRIAR"):
        company_name = clean_text[5:].strip()
        if not company_name:
            user.role = UserRole.ADMIN
            user.onboarding_step = "COMP_NAME"
            await db.commit()
            await wuzapi_client.send_text_message(phone, "🏢 Qual o nome da sua empresa ou prefeitura?")
            return {"status": "ok"}

        from app.services.command_handler import generate_company_code
        code = generate_company_code(company_name)
        new_company = Company(
            id=str(uuid.uuid4()),
            code=code,
            name=company_name,
            admin_phone=phone,
            admin_name=user.name,
            billing_email=user.email,
            plan=PlanType.FREE_TRIAL
        )
        db.add(new_company)
        user.company_id = new_company.id
        user.role = UserRole.ADMIN
        user.onboarding_step = "COMP_CNPJ"
        await db.commit()

        await wuzapi_client.send_text_message(
            phone,
            f"Me informe o *CNPJ* da empresa. (Digite apenas números ou com pontuação. Ex: 09.134.593/0001-53):"
        )
        return {"status": "ok"}

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

