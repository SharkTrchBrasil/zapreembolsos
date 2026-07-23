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
            "Escolha a ação desejada:\n\n"
            "1️⃣ - 📋 Listar Todos os Funcionários\n"
            "2️⃣ - ✅ Aprovar Novos Cadastros\n"
            "3️⃣ - 💸 Definir Limite de Gastos\n"
            "4️⃣ - ✏️ Editar Perfil do Funcionário\n"
            "5️⃣ - ❌ Excluir / Desativar Funcionário\n"
            "6️⃣ - 🔙 Voltar ao Menu Principal"
        )
        await wuzapi_client.send_text_message(phone, msg)
        return {"status": "ok"}

    async def handle_team_menu(self, user: User, text: str, phone: str, company: Company, db: AsyncSession) -> dict:
        if text == "1":
            return await self.handle_team_list(phone, user, company, db)
        elif text == "2":
            user.onboarding_step = "MENU_TEAM_ACCEPT"
            await db.commit()
            await wuzapi_client.send_text_message(phone, "👥 Digite o *telefone* do funcionário que deseja aprovar (Ex: 5511999999999).")
            return {"status": "ok"}
        elif text == "3":
            user.onboarding_step = "MENU_TEAM_LIMIT_TEL"
            await db.commit()
            await wuzapi_client.send_text_message(phone, "💸 Digite o *telefone* do funcionário para definir o limite.")
            return {"status": "ok"}
        elif text == "4":
            user.onboarding_step = "MENU_TEAM_EDIT_TEL"
            await db.commit()
            await wuzapi_client.send_text_message(phone, "✏️ Digite o *telefone* do funcionário que deseja editar (Ex: 5511999999999).")
            return {"status": "ok"}
        elif text == "5":
            user.onboarding_step = "MENU_TEAM_DELETE_TEL"
            await db.commit()
            await wuzapi_client.send_text_message(phone, "❌ Digite o *telefone* do funcionário que deseja excluir/desativar.")
            return {"status": "ok"}
        elif text == "6":
            return await self.send_main_menu(phone, user, db)
        else:
            await wuzapi_client.send_text_message(phone, "🚫 Opção inválida. Escolha de 1 a 6.")
            return {"status": "ok"}

    async def handle_team_list(self, phone: str, user: User, company: Company, db: AsyncSession) -> dict:
        users_query = select(User).where(User.company_id == company.id)
        res = await db.execute(users_query)
        company_users = res.scalars().all()
        
        if not company_users:
            await wuzapi_client.send_text_message(phone, "📋 Sua equipe ainda está vazia.")
            return await self.send_team_menu(phone, user, db)
            
        msg = "📋 *Lista de Funcionários:*\n\n"
        for u in company_users:
            status = "✅ Ativo" if u.is_approved else "⏳ Pendente"
            role = "Gestor" if u.role == UserRole.ADMIN else "Membro"
            limite = f"R$ {float(u.monthly_limit):.2f}" if u.monthly_limit else "Ilimitado"
            nome = u.name or "Sem Nome"
            msg += f"• *{nome}* ({u.phone})\n"
            msg += f"  Status: {status} | {role} | Limite: {limite}\n\n"
            
        await wuzapi_client.send_text_message(phone, msg)
        return await self.send_team_menu(phone, user, db)

    async def handle_team_accept_step(self, user: User, text: str, phone: str, company: Company, db: AsyncSession) -> dict:
        user.onboarding_step = None
        await db.commit()
        return await command_handler.handle_aceitar_recusar(f"ACEITAR {text}", phone, user, company, db)

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

    async def handle_team_edit_tel_step(self, user: User, text: str, phone: str, company: Company, db: AsyncSession) -> dict:
        target_phone = text.replace("+", "").replace("-", "").strip()
        user.onboarding_step = f"MENU_TEAM_EDIT_FIELD_{target_phone}"
        await db.commit()
        
        msg = (
            "✏️ O que você deseja editar neste funcionário?\n\n"
            "1️⃣ - Nome Completo\n"
            "2️⃣ - Setor / Departamento\n"
            "3️⃣ - Papel (Promover a Gestor / Rebaixar a Membro)\n\n"
            "_Digite CANCELAR para abortar._"
        )
        await wuzapi_client.send_text_message(phone, msg)
        return {"status": "ok"}

    async def handle_team_edit_field_step(self, user: User, text: str, phone: str, db: AsyncSession) -> dict:
        parts = user.onboarding_step.split("_", 4)
        target_phone = parts[4] if len(parts) > 4 else ""
        
        if text not in ["1", "2", "3"]:
            await wuzapi_client.send_text_message(phone, "🚫 Opção inválida. Digite 1, 2 ou 3.")
            return {"status": "ok"}
            
        user.onboarding_step = f"MENU_TEAM_EDIT_VAL_{target_phone}_{text}"
        await db.commit()
        
        if text == "1":
            await wuzapi_client.send_text_message(phone, "Digite o *novo nome completo*:")
        elif text == "2":
            await wuzapi_client.send_text_message(phone, "Digite o *novo setor/departamento* (Ex: Vendas):")
        elif text == "3":
            await wuzapi_client.send_text_message(phone, "Qual será o novo papel?\n\n*1* - Membro Comum\n*2* - Gestor (Admin)")
            
        return {"status": "ok"}

    async def handle_team_edit_val_step(self, user: User, text: str, phone: str, company: Company, db: AsyncSession) -> dict:
        parts = user.onboarding_step.split("_", 5)
        target_phone = parts[4] if len(parts) > 4 else ""
        field = parts[5] if len(parts) > 5 else ""
        
        user.onboarding_step = None
        
        clean_digits = "".join(c for c in target_phone if c.isdigit())
        search_digits = clean_digits[-8:] if len(clean_digits) >= 8 else clean_digits
        
        t_user_query = select(User).where(User.phone.like(f"%{search_digits}%"), User.company_id == company.id)
        t_user_res = await db.execute(t_user_query)
        t_user = t_user_res.scalars().first()
        
        if not t_user:
            await db.commit()
            await wuzapi_client.send_text_message(phone, f"❌ Funcionário não encontrado com telefone {target_phone}.")
            return await self.send_team_menu(phone, user, db)
            
        if field == "1":
            t_user.name = text.strip()
            msg = f"✅ Nome alterado com sucesso para *{t_user.name}*."
        elif field == "2":
            t_user.department = text.strip()
            msg = f"✅ Setor alterado com sucesso para *{t_user.department}*."
        elif field == "3":
            if text == "1":
                t_user.role = UserRole.EMPLOYEE
                msg = f"✅ Permissões de {t_user.name} alteradas para *Membro Comum*."
            elif text == "2":
                t_user.role = UserRole.ADMIN
                msg = f"✅ Permissões de {t_user.name} alteradas para *Gestor (Admin)*."
            else:
                msg = "🚫 Opção inválida. Alteração cancelada."
        
        await db.commit()
        await wuzapi_client.send_text_message(phone, msg)
        return await self.send_team_menu(phone, user, db)

    async def handle_team_delete_tel_step(self, user: User, text: str, phone: str, company: Company, db: AsyncSession) -> dict:
        target_phone = text.replace("+", "").replace("-", "").strip()
        user.onboarding_step = f"MENU_TEAM_DELETE_CONFIRM_{target_phone}"
        await db.commit()
        
        await wuzapi_client.send_text_message(phone, "⚠️ *Tem certeza* que deseja excluir esse funcionário e desvinculá-lo da empresa?\n\nResponda *SIM* para confirmar ou *CANCELAR* para voltar.")
        return {"status": "ok"}

    async def handle_team_delete_confirm_step(self, user: User, text: str, phone: str, company: Company, db: AsyncSession) -> dict:
        parts = user.onboarding_step.split("_", 4)
        target_phone = parts[4] if len(parts) > 4 else ""
        
        if text.upper().strip() in ["SIM", "S", "YES", "Y"]:
            user.onboarding_step = None
            
            clean_digits = "".join(c for c in target_phone if c.isdigit())
            search_digits = clean_digits[-8:] if len(clean_digits) >= 8 else clean_digits
            
            t_user_query = select(User).where(User.phone.like(f"%{search_digits}%"), User.company_id == company.id)
            t_user_res = await db.execute(t_user_query)
            t_user = t_user_res.scalars().first()
            
            if not t_user:
                await db.commit()
                await wuzapi_client.send_text_message(phone, f"❌ Funcionário não encontrado com telefone {target_phone}.")
                return await self.send_team_menu(phone, user, db)
                
            t_user.company_id = None
            t_user.is_approved = False
            t_user.role = UserRole.EMPLOYEE # Remove previlégios caso fosse admin
            
            await db.commit()
            await wuzapi_client.send_text_message(t_user.phone, f"🚫 O seu vínculo com a empresa *{company.name}* foi removido pelo Gestor.")
            await wuzapi_client.send_text_message(phone, f"✅ O funcionário *{t_user.name or t_user.phone}* foi removido da equipe com sucesso.")
            return await self.send_team_menu(phone, user, db)
        else:
            user.onboarding_step = None
            await db.commit()
            await wuzapi_client.send_text_message(phone, "🚫 Exclusão cancelada.")
            return await self.send_team_menu(phone, user, db)

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
