import uuid
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.models import User, Company, UserRole, PlanType
from app.services.wuzapi_service import wuzapi_client
from app.services.command_handler import command_handler, generate_company_code

logger = logging.getLogger("onboarding")

class OnboardingService:
    
    async def check_onboarding_timeout(self, user: User, phone: str, db: AsyncSession) -> bool:
        """
        Verifica se o usuário ficou travado no fluxo de onboarding por mais de 24 horas.
        Retorna True se sofreu reset, False caso contrário.
        """
        if not user.onboarding_step:
            return False
            
        # Se for estado de confirmação de ação, resetar mais rápido (ex: 1 hora)
        timeout_hours = 1 if user.onboarding_step.startswith("CONFIRM_") else 24
            
        if user.updated_at and (datetime.now(timezone.utc) - user.updated_at) > timedelta(hours=timeout_hours):
            logger.info(f"Timeout de onboarding atingido para {phone} no passo {user.onboarding_step}")
            user.onboarding_step = None
            if user.role != UserRole.ADMIN and user.role != UserRole.EMPLOYEE:
                 user.role = UserRole.EMPLOYEE # Reset seguro
            await db.commit()
            
            await wuzapi_client.send_text_message(
                phone,
                "⚠️ *Sua sessão expirou por inatividade.*\n\n"
                "Para reiniciar, por favor digite *MENU* ou envie o comando desejado."
            )
            return True
        return False

    async def handle_lead_onboarding(self, user: User, clean_text: str, phone: str, db: AsyncSession) -> dict:
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
                f"1️⃣ *Quero cadastrar minha Empresa / Órgão* (Sou Gestor)\n"
                f"2️⃣ *Quero me vincular à uma empresa* (Sou Funcionário)\n"
                f"3️⃣ *Preciso de ajuda ou suporte*\n\n"
                f"Digite *1*, *2* ou *3* para escolher:"
            )
            await wuzapi_client.send_text_message(phone, menu_msg)
            return {"status": "ok"}
            
        return {"status": "ignored"}

    async def handle_main_menu(self, user: User, clean_text: str, phone: str, db: AsyncSession) -> dict:
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

    async def handle_employee_onboarding(self, user: User, clean_text: str, phone: str, db: AsyncSession) -> dict:
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
            
            # Limpa dígitos para busca flexível do telefone
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
                
        return {"status": "ignored"}

    async def handle_company_onboarding(self, user: User, clean_text: str, phone: str, db: AsyncSession) -> dict:
        comp_query = select(Company).where(Company.id == user.company_id)
        comp_res = await db.execute(comp_query)
        comp = comp_res.scalar_one_or_none()

        if user.onboarding_step == "COMP_NAME":
            company_name = clean_text.strip()
            for attempt in range(5):
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
                try:
                    await db.flush()
                    break
                except IntegrityError:
                    await db.rollback()
            else:
                await wuzapi_client.send_text_message(phone, "❌ Erro ao criar empresa (conflito de código). Tente outro nome.")
                return {"status": "error"}

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
            user.onboarding_step = "COMP_PLAN"
            await db.commit()

            plan_menu = (
                "🚀 *Escolha seu Plano de Teste (30 Dias Grátis - Sem Cartão)*\n\n"
                "Sua empresa terá 30 dias de acesso total e ilimitado para testar com a equipe!\n\n"
                "1️⃣ *Plano Starter* (Até 5 funcionários) — _R$ 49,90/mês pós teste_\n"
                "2️⃣ *Plano Pro* (Até 20 funcionários + Relatórios) — _R$ 99,90/mês pós teste_\n"
                "3️⃣ *Plano Enterprise* (Ilimitado + Suporte VIP) — _R$ 199,90/mês pós teste_\n\n"
                "Digite *1*, *2* ou *3* para ativar seus 30 dias grátis:"
            )
            await wuzapi_client.send_text_message(phone, plan_menu)
            return {"status": "ok"}

        elif user.onboarding_step == "COMP_PLAN":
            plan_choice = clean_text.strip()
            price = 49.90
            plan_name = "Starter (Até 5 funcionários)"
            
            if plan_choice in ["2", "pro"]:
                price = 99.90
                plan_name = "Pro (Até 20 funcionários)"
            elif plan_choice in ["3", "enterprise"]:
                price = 199.90
                plan_name = "Enterprise (Ilimitado)"

            trial_expiration = datetime.now(timezone.utc) + timedelta(days=30)
            
            if comp:
                comp.plan = PlanType.FREE_TRIAL
                comp.trial_ends_at = trial_expiration

            user.onboarding_step = None
            await db.commit()

            code = comp.code if comp else "ERRO"
            success_msg = (
                f"🎉 *Cadastro Concluído com Sucesso!*\n\n"
                f"Sua empresa foi cadastrada no plano *{plan_name}*.\n"
                f"O período de teste grátis vai até {trial_expiration.strftime('%d/%m/%Y')}.\n\n"
                f"👉 Seu código de convite para funcionários é: *{code}*\n\n"
                f"Peça para seus funcionários mandarem um 'Oi' neste mesmo número e usarem esse código para se vincularem à sua empresa.\n\n"
                f"Você já pode mandar fotos de comprovantes fiscais!"
            )
            await wuzapi_client.send_text_message(phone, success_msg)
            return {"status": "ok"}
            
        return {"status": "ignored"}

onboarding_service = OnboardingService()
