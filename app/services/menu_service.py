import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import User, Company, UserRole, ExpenseStatus, Expense
from app.services.wuzapi_service import wuzapi_client
from app.services.command_handler import command_handler

logger = logging.getLogger("menu_service")

class MenuService:
    async def send_main_menu(self, phone: str, user: User, db: AsyncSession) -> dict:
        user.onboarding_step = "MENU_MAIN"
        await db.commit()
        
        if user.role == UserRole.ADMIN:
            msg = (
                "🤖 *Menu Principal (Gestor)*\n"
                "Responda com o número desejado:\n\n"
                "1️⃣ - 📝 Lançamentos Manuais\n"
                "2️⃣ - ✅ Central de Aprovações\n"
                "3️⃣ - 📊 Relatórios e Exportações\n"
                "4️⃣ - 👥 Gestão de Equipe\n"
                "5️⃣ - 🌐 Acessar Painel Web\n\n"
                "💡 _Dica: Digite CANCELAR a qualquer momento para voltar._"
            )
        else:
            msg = (
                "🤖 *Menu Principal (Funcionário)*\n"
                "Responda com o número desejado:\n\n"
                "1️⃣ - 📸 Como enviar comprovantes\n"
                "2️⃣ - 📝 Lançamentos Manuais (KM, sem nota)\n"
                "3️⃣ - 📊 Meu Extrato de Gastos\n\n"
                "💡 _Dica: Digite CANCELAR a qualquer momento para voltar._"
            )
            
        await wuzapi_client.send_text_message(phone, msg)
        return {"status": "ok"}

    async def handle_main_menu(self, user: User, text: str, phone: str, company: Company, db: AsyncSession) -> dict:
        if user.role == UserRole.ADMIN:
            if text == "1":
                return await self.send_launch_menu(phone, user, db)
            elif text == "2":
                return await self.send_approval_menu(phone, user, db)
            elif text == "3":
                return await self.send_report_menu(phone, user, db)
            elif text == "4":
                return await self.send_team_menu(phone, user, db)
            elif text == "5":
                user.onboarding_step = None
                await db.commit()
                # Assuming generic link for now
                painel_url = "https://app.zapreembolso.com.br"
                await wuzapi_client.send_text_message(phone, f"🌐 *Acesse o Painel Web:* {painel_url}")
                return {"status": "ok"}
            else:
                await wuzapi_client.send_text_message(phone, "🚫 Opção inválida. Digite de 1 a 5, ou CANCELAR para sair.")
                return {"status": "ok"}
        else:
            if text == "1":
                user.onboarding_step = None
                await db.commit()
                await wuzapi_client.send_text_message(
                    phone, 
                    "📸 *Como enviar comprovantes*\n\n"
                    "É muito simples! Basta abrir a conversa comigo e enviar a *foto do seu cupom fiscal* ou *arquivo PDF*.\n"
                    "Eu leio automaticamente os dados, monto a despesa e mando para o seu gestor aprovar."
                )
                return {"status": "ok"}
            elif text == "2":
                return await self.send_launch_menu(phone, user, db)
            elif text == "3":
                user.onboarding_step = None
                await db.commit()
                return await command_handler.handle_relatorio(f"RELATORIO", phone, user, company, db)
            else:
                await wuzapi_client.send_text_message(phone, "🚫 Opção inválida. Digite de 1 a 3, ou CANCELAR para sair.")
                return {"status": "ok"}

    async def send_launch_menu(self, phone: str, user: User, db: AsyncSession) -> dict:
        user.onboarding_step = "MENU_LAUNCH"
        await db.commit()
        msg = (
            "📝 *Menu de Lançamentos Manuais*\n"
            "Responda com a opção desejada:\n\n"
            "1️⃣ - Lançar KM Rodado\n"
            "2️⃣ - Lançar Despesa sem Nota (Ex: Gorjeta, Pedágio)\n"
            "3️⃣ - Voltar ao Menu Principal"
        )
        await wuzapi_client.send_text_message(phone, msg)
        return {"status": "ok"}

    async def handle_launch_menu(self, user: User, text: str, phone: str, company: Company, db: AsyncSession) -> dict:
        if text == "1":
            user.onboarding_step = "MENU_LAUNCH_KM"
            await db.commit()
            await wuzapi_client.send_text_message(phone, "🚗 Qual foi a *distância percorrida* em KM?\n\n_Exemplo: Digite apenas o número (ex: 20, 15.5)_")
            return {"status": "ok"}
        elif text == "2":
            user.onboarding_step = "MENU_LAUNCH_MANUAL_VAL"
            await db.commit()
            await wuzapi_client.send_text_message(phone, "💰 Qual o *valor total* dessa despesa em Reais?\n\n_Exemplo: Digite 50.00_")
            return {"status": "ok"}
        elif text == "3":
            return await self.send_main_menu(phone, user, db)
        else:
            await wuzapi_client.send_text_message(phone, "🚫 Opção inválida.")
            return {"status": "ok"}

    async def handle_launch_km_step(self, user: User, text: str, phone: str, company: Company, db: AsyncSession) -> dict:
        user.onboarding_step = None
        await db.commit()
        return await command_handler.handle_km(f"KM {text}", phone, user, company, db)

    async def handle_launch_manual_val_step(self, user: User, text: str, phone: str, db: AsyncSession) -> dict:
        user.onboarding_step = f"MENU_LAUNCH_MANUAL_DESC_{text.strip()}"
        await db.commit()
        await wuzapi_client.send_text_message(phone, "📝 Qual é a *descrição* ou *motivo* desse gasto?\n\n_Exemplo: Estacionamento centro_")
        return {"status": "ok"}

    async def handle_launch_manual_desc_step(self, user: User, text: str, phone: str, company: Company, db: AsyncSession) -> dict:
        parts = user.onboarding_step.split("_", 4)
        val = parts[4] if len(parts) > 4 else "0"
        
        user.onboarding_step = None
        await db.commit()
        return await command_handler.handle_despesa(f"DESPESA {val} {text}", phone, user, company, db)

    async def send_approval_menu(self, phone: str, user: User, db: AsyncSession) -> dict:
        user.onboarding_step = "MENU_APPROVAL"
        await db.commit()
        msg = (
            "✅ *Central de Aprovações*\n"
            "Escolha o que deseja fazer:\n\n"
            "1️⃣ - Aprovar Despesa (Por ID)\n"
            "2️⃣ - Rejeitar Despesa (Por ID)\n"
            "3️⃣ - Voltar ao Menu Principal"
        )
        await wuzapi_client.send_text_message(phone, msg)
        return {"status": "ok"}

    async def handle_approval_menu(self, user: User, text: str, phone: str, company: Company, db: AsyncSession) -> dict:
        if text == "1":
            user.onboarding_step = "MENU_APPROVAL_ACCEPT"
            await db.commit()
            await wuzapi_client.send_text_message(phone, "👍 Digite o *ID* da despesa que deseja aprovar (Ex: 1A2B).")
            return {"status": "ok"}
        elif text == "2":
            user.onboarding_step = "MENU_APPROVAL_REJECT_ID"
            await db.commit()
            await wuzapi_client.send_text_message(phone, "👎 Digite o *ID* da despesa que deseja rejeitar.")
            return {"status": "ok"}
        elif text == "3":
            return await self.send_main_menu(phone, user, db)
        else:
            await wuzapi_client.send_text_message(phone, "🚫 Opção inválida.")
            return {"status": "ok"}

    async def handle_approval_accept_step(self, user: User, text: str, phone: str, company: Company, db: AsyncSession) -> dict:
        user.onboarding_step = None
        await db.commit()
        return await command_handler.handle_aprovar_rejeitar(f"APROVAR {text}", phone, user, company, db)
        
    async def handle_approval_reject_id_step(self, user: User, text: str, phone: str, db: AsyncSession) -> dict:
        user.onboarding_step = f"MENU_APPROVAL_REJECT_REASON_{text.strip()}"
        await db.commit()
        await wuzapi_client.send_text_message(phone, "Qual o *motivo* da rejeição?\n\n_Esse motivo será enviado para o funcionário._")
        return {"status": "ok"}

    async def handle_approval_reject_reason_step(self, user: User, text: str, phone: str, company: Company, db: AsyncSession) -> dict:
        parts = user.onboarding_step.split("_", 4)
        exp_id = parts[4] if len(parts) > 4 else ""
        
        user.onboarding_step = None
        await db.commit()
        return await command_handler.handle_aprovar_rejeitar(f"REJEITAR {exp_id} {text}", phone, user, company, db)

    async def send_team_menu(self, phone: str, user: User, db: AsyncSession) -> dict:
        user.onboarding_step = "MENU_TEAM"
        await db.commit()
        msg = (
            "👥 *Gestão de Equipe*\n"
            "Escolha o que deseja fazer:\n\n"
            "1️⃣ - Aprovar Novo Funcionário\n"
            "2️⃣ - Rejeitar Novo Funcionário\n"
            "3️⃣ - Definir Limite de Gastos p/ Funcionário\n"
            "4️⃣ - Voltar ao Menu Principal"
        )
        await wuzapi_client.send_text_message(phone, msg)
        return {"status": "ok"}

    async def handle_team_menu(self, user: User, text: str, phone: str, company: Company, db: AsyncSession) -> dict:
        if text == "1":
            user.onboarding_step = "MENU_TEAM_ACCEPT"
            await db.commit()
            await wuzapi_client.send_text_message(phone, "👥 Digite o *telefone* do funcionário que deseja aprovar (Ex: 5511999999999).")
            return {"status": "ok"}
        elif text == "2":
            user.onboarding_step = "MENU_TEAM_REJECT"
            await db.commit()
            await wuzapi_client.send_text_message(phone, "👥 Digite o *telefone* do funcionário que deseja rejeitar da empresa.")
            return {"status": "ok"}
        elif text == "3":
            user.onboarding_step = "MENU_TEAM_LIMIT_TEL"
            await db.commit()
            await wuzapi_client.send_text_message(phone, "💸 Digite o *telefone* do funcionário para definir o limite.")
            return {"status": "ok"}
        elif text == "4":
            return await self.send_main_menu(phone, user, db)
        else:
            await wuzapi_client.send_text_message(phone, "🚫 Opção inválida.")
            return {"status": "ok"}

    async def handle_team_accept_step(self, user: User, text: str, phone: str, company: Company, db: AsyncSession) -> dict:
        user.onboarding_step = None
        await db.commit()
        return await command_handler.handle_aceitar_recusar(f"ACEITAR {text}", phone, user, company, db)

    async def handle_team_reject_step(self, user: User, text: str, phone: str, company: Company, db: AsyncSession) -> dict:
        user.onboarding_step = None
        await db.commit()
        return await command_handler.handle_aceitar_recusar(f"RECUSAR {text}", phone, user, company, db)

    async def handle_team_limit_tel_step(self, user: User, text: str, phone: str, db: AsyncSession) -> dict:
        user.onboarding_step = f"MENU_TEAM_LIMIT_VAL_{text.strip()}"
        await db.commit()
        await wuzapi_client.send_text_message(phone, "Qual o *valor do limite* mensal em Reais?\n\n_Ex: 500.00_")
        return {"status": "ok"}

    async def handle_team_limit_val_step(self, user: User, text: str, phone: str, company: Company, db: AsyncSession) -> dict:
        parts = user.onboarding_step.split("_", 4)
        target_phone = parts[4] if len(parts) > 4 else ""
        
        user.onboarding_step = None
        await db.commit()
        return await command_handler.handle_limite(f"LIMITE {target_phone} {text}", phone, user, company, db)

    async def send_report_menu(self, phone: str, user: User, db: AsyncSession) -> dict:
        user.onboarding_step = "MENU_REPORT"
        await db.commit()
        msg = (
            "📊 *Menu de Relatórios*\n"
            "Responda com o número do relatório desejado:\n\n"
            "1️⃣ - Resumo do Mês (Categorias e Funcionários)\n"
            "2️⃣ - Ranking de Gastos\n"
            "3️⃣ - Exportar para Excel (CSV)\n"
            "4️⃣ - Voltar ao Menu Principal"
        )
        await wuzapi_client.send_text_message(phone, msg)
        return {"status": "ok"}

    async def handle_report_menu(self, user: User, text: str, phone: str, company: Company, db: AsyncSession) -> dict:
        if text == "1":
            user.onboarding_step = None
            await db.commit()
            return await command_handler.handle_relatorio("RELATORIO", phone, user, company, db)
        elif text == "2":
            user.onboarding_step = None
            await db.commit()
            return await command_handler.handle_ranking(phone, company, db)
        elif text == "3":
            user.onboarding_step = None
            await db.commit()
            return await command_handler.handle_exportar("EXPORTAR", phone, user, company, db)
        elif text == "4":
            return await self.send_main_menu(phone, user, db)
        else:
            await wuzapi_client.send_text_message(phone, "🚫 Opção inválida.")
            return {"status": "ok"}

menu_service = MenuService()
