import uuid
from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.models import User, Company, Expense, UserRole, ExpenseStatus, PlanType, ExpenseCategory
from app.services.wuzapi_service import wuzapi_client
from app.services.policy_service import policy_service
import random

def generate_company_code(name: str) -> str:
    """Gera um código único curto como #ALFA1 ou #POSTO7."""
    clean_name = "".join(c for c in name if c.isalnum()).upper()[:4]
    random_num = random.randint(10, 999)
    return f"{clean_name}{random_num}"

class CommandHandler:
    async def handle_criar(self, clean_text: str, phone: str, user: User, db: AsyncSession) -> dict:
        company_name = clean_text[5:].strip()
        if not company_name:
            await wuzapi_client.send_text_message(phone, "❌ Por favor, informe o nome da sua empresa. Exemplo: *CRIAR Construtora Alfa*")
            return {"status": "ok"}

        for attempt in range(5):
            code = generate_company_code(company_name)
            new_company = Company(
                id=str(uuid.uuid4()),
                code=code,
                name=company_name,
                admin_phone=phone,
                plan=PlanType.FREE_TRIAL
            )
            db.add(new_company)
            try:
                await db.commit()
                break
            except IntegrityError:
                await db.rollback()
        else:
            await wuzapi_client.send_text_message(phone, "❌ Erro ao criar empresa (conflito de código). Tente outro nome.")
            return {"status": "error"}

        user.company_id = new_company.id
        user.role = UserRole.ADMIN
        user.name = f"Gestor ({company_name})"
        await db.commit()

        welcome_admin = (
            f"🎉 *Empresa {company_name} Criada com Sucesso!*\n\n"
            f"🏢 *Código da Sua Empresa:* `#{code}`\n\n"
            f"📢 *Passo para seus funcionários:*\n"
            f"Envie este contato para seus funcionários e peça para eles mandarem `#{code}` no primeiro acesso para se vincularem!\n\n"
            f"💡 *Seus Comandos:*\n"
            f"• Envie *RELATORIO* para ver gastos do mês.\n"
            f"• Envie *APROVAR [ID]* para dar baixa em reembolso."
        )
        await wuzapi_client.send_text_message(phone, welcome_admin)
        return {"status": "ok"}

    async def handle_vincular(self, clean_text: str, phone: str, user: User, db: AsyncSession) -> dict:
        raw_code = clean_text.replace("#", "").replace("ENTRAR", "").strip().upper()
        comp_query = select(Company).where(Company.code == raw_code)
        comp_res = await db.execute(comp_query)
        target_company = comp_res.scalar_one_or_none()

        if target_company:
            user.company_id = target_company.id
            user.role = UserRole.EMPLOYEE
            await db.commit()

            link_msg = (
                f"✅ *Conta Vinculada à empresa {target_company.name}!*\n\n"
                f"A partir de agora, qualquer foto de *cupom fiscal ou recibo* que você enviar aqui será registrada automaticamente para o reembolso do seu gestor."
            )
            await wuzapi_client.send_text_message(phone, link_msg)
        else:
            await wuzapi_client.send_text_message(phone, f"❌ Código `#{raw_code}` não encontrado. Verifique com seu gestor o código correto da empresa.")
        return {"status": "ok"}

    async def handle_relatorio(self, clean_text: str, phone: str, user: User, company: Company, db: AsyncSession) -> dict:
        if not company:
            await wuzapi_client.send_text_message(phone, "❌ Empresa não encontrada.")
            return {"status": "ok"}

        today = date.today()
        exp_query = select(Expense).where(
            Expense.company_id == company.id,
            Expense.expense_date >= today.replace(day=1)
        )
        exp_res = await db.execute(exp_query)
        all_expenses = exp_res.scalars().all()

        total_amount = sum(e.amount for e in all_expenses)
        pending_expenses = [e for e in all_expenses if e.status == ExpenseStatus.PENDING]
        approved_expenses = [e for e in all_expenses if e.status in (ExpenseStatus.APPROVED, ExpenseStatus.REIMBURSED)]

        by_category = {}
        for e in all_expenses:
            cat_name = e.category.value if hasattr(e.category, 'value') else str(e.category)
            by_category[cat_name] = by_category.get(cat_name, 0.0) + float(e.amount)

        cat_summary = "\n".join([f"• **{cat}:** R$ {amt:.2f}" for cat, amt in by_category.items()]) or "Nenhuma despesa"

        report_msg = (
            f"📊 **Resumo de Despesas - Mês Atual ({today.strftime('%m/%Y')})**\n\n"
            f"💰 **Total Acumulado:** R$ {total_amount:.2f} ({len(all_expenses)} comprovantes)\n"
            f"✅ **Aprovadas:** R$ {sum(e.amount for e in approved_expenses):.2f}\n"
            f"⏳ **Pendentes de Aprovação:** {len(pending_expenses)} (R$ {sum(e.amount for e in pending_expenses):.2f})\n\n"
            f"🏷️ **Por Categoria:**\n{cat_summary}\n\n"
        )
        
        if pending_expenses and user.role == UserRole.ADMIN:
            report_msg += "📋 **Pendentes:**\n"
            for p in pending_expenses:
                report_msg += f"- [{p.id[:4]}] {p.merchant_name} (R$ {p.amount:.2f})\n"
            report_msg += "\n💡 Responda *APROVAR [ID]* ou *REJEITAR [ID]*."

        await wuzapi_client.send_text_message(phone, report_msg)
        return {"status": "ok"}

    async def handle_aprovar_rejeitar(self, clean_text: str, phone: str, user: User, company: Company, db: AsyncSession) -> dict:
        if user.role != UserRole.ADMIN:
            await wuzapi_client.send_text_message(phone, "❌ Apenas gestores podem aprovar ou rejeitar despesas.")
            return {"status": "ok"}
            
        raw_cmd = clean_text.upper().strip()
        is_shortcut_1 = raw_cmd in ["1", "APROVAR"]
        is_shortcut_2 = raw_cmd in ["2", "REJEITAR"]

        action = "APROVAR" if (raw_cmd.startswith("APROVAR") or is_shortcut_1) else "REJEITAR"
        new_status = ExpenseStatus.APPROVED if action == "APROVAR" else ExpenseStatus.REJECTED
        parts = clean_text.split(" ", 2)
        
        short_id = None
        rejection_reason = None

        if len(parts) >= 2 and not (is_shortcut_1 or is_shortcut_2):
            short_id = parts[1].strip()
            rejection_reason = parts[2].strip() if len(parts) > 2 else None

        # Se for atalho ("1" ou "2" ou "APROVAR" sem ID), busca se existe exatamente 1 despesa pendente
        if not short_id:
            pending_query = select(Expense).where(
                Expense.company_id == company.id,
                Expense.status == ExpenseStatus.PENDING
            )
            pending_res = await db.execute(pending_query)
            pending_list = pending_res.scalars().all()

            if not pending_list:
                await wuzapi_client.send_text_message(phone, "❌ Não há nenhuma despesa pendente de aprovação no momento.")
                return {"status": "ok"}
            elif len(pending_list) == 1:
                exp = pending_list[0]
                short_id = exp.id[:4]
                if action == "REJEITAR" and not rejection_reason:
                    rejection_reason = "Não atende às políticas da empresa"
            else:
                msg = f"📋 Existem {len(pending_list)} despesas pendentes. Por favor informe o ID de 4 dígitos:\n"
                for p in pending_list[:5]:
                    msg += f"• *{action} {p.id[:4]}*\n"
                await wuzapi_client.send_text_message(phone, msg)
                return {"status": "ok"}

        if action == "REJEITAR" and not rejection_reason and len(parts) > 1:
            await wuzapi_client.send_text_message(phone, f"❌ Para rejeitar, você deve informar um motivo.\nExemplo: *REJEITAR {short_id} Valor acima do teto*")
            return {"status": "ok"}

        exp_query = select(Expense).where(
            Expense.company_id == user.company_id,
            Expense.status == ExpenseStatus.PENDING,
            Expense.id.like(f"{short_id}%")
        )
        exp_res = await db.execute(exp_query)
        exp = exp_res.scalars().first()

        if not exp:
            await wuzapi_client.send_text_message(phone, f"❌ Despesa '{short_id}' não encontrada ou já processada.")
            return {"status": "ok"}

        exp.status = new_status
        exp.approved_by = phone
        from datetime import datetime, timezone
        exp.approved_at = datetime.now(timezone.utc)
        
        if action == "REJEITAR":
            exp.rejection_reason = rejection_reason or "Rejeitado pelo gestor"

        await db.commit()
        
        # Notifica o funcionário
        employee_msg = f"🔔 **Sua despesa foi {new_status.value}!**\n📍 {exp.merchant_name} (R$ {exp.amount:.2f})\n"
        if action == "REJEITAR":
            employee_msg += f"❌ **Motivo:** {exp.rejection_reason}"
        else:
            employee_msg += "✅ Reembolso autorizado pelo gestor."
            
        await wuzapi_client.send_text_message(exp.user_phone, employee_msg)

        await wuzapi_client.send_text_message(
            phone,
            f"✅ **Despesa de {exp.merchant_name} (R$ {exp.amount:.2f}) {new_status.value}!** O funcionário foi notificado."
        )
        return {"status": "ok"}

    async def handle_aceitar_recusar(self, clean_text: str, phone: str, user: User, company: Company, db: AsyncSession) -> dict:
        """Permite que o gestor aceite ou recuse a solicitação de um funcionário."""
        if user.role != UserRole.ADMIN:
            await wuzapi_client.send_text_message(phone, "❌ Apenas gestores podem aceitar ou recusar funcionários.")
            return {"status": "ok"}

        raw_cmd = clean_text.upper().strip()
        parts = clean_text.split()
        
        is_shortcut_1 = raw_cmd in ["1", "01", "ACEITAR", "APROVAR"]
        is_shortcut_2 = raw_cmd in ["2", "02", "RECUSAR", "NEGAR"]

        action = "ACEITAR" if (raw_cmd.startswith("ACEITAR") or is_shortcut_1) else "RECUSAR"
        target_phone = parts[1].replace("+", "").replace("-", "").strip() if len(parts) >= 2 else None

        target_user = None

        if target_phone:
            # Limpa dígitos para busca flexível pelos últimos 8 ou 9 dígitos
            clean_digits = "".join(c for c in target_phone if c.isdigit())
            search_digits = clean_digits[-8:] if len(clean_digits) >= 8 else clean_digits

            user_query = select(User).where(
                User.phone.like(f"%{search_digits}%"),
                User.company_id == company.id
            )
            user_res = await db.execute(user_query)
            target_user = user_res.scalars().first()
        else:
            # Se não informou o telefone, busca se há exatamente 1 funcionário pendente
            pending_query = select(User).where(
                User.company_id == company.id,
                User.is_approved == False
            )
            pending_res = await db.execute(pending_query)
            pending_users = pending_res.scalars().all()

            if not pending_users:
                await wuzapi_client.send_text_message(phone, "❌ Não há nenhuma solicitação de cadastro de funcionário pendente no momento.")
                return {"status": "ok"}
            elif len(pending_users) == 1:
                target_user = pending_users[0]
            else:
                msg = f"📋 Existem {len(pending_users)} funcionários aguardando aprovação. Por favor, responda com o número do telefone:\n\n"
                for u in pending_users:
                    msg += f"• *{action} {u.phone}* ({u.name} - {u.department or 'Geral'})\n"
                await wuzapi_client.send_text_message(phone, msg)
                return {"status": "ok"}

        if not target_user:
            await wuzapi_client.send_text_message(phone, f"❌ Funcionário com telefone `{target_phone}` não foi encontrado nas solicitações pendentes.")
            return {"status": "ok"}

        if action == "ACEITAR":
            target_user.is_approved = True
            target_user.onboarding_step = None
            await db.commit()

            # Notifica o funcionário
            welcome_employee = (
                f"🎉 *Seu cadastro na empresa {company.name} foi APROVADO!*\n\n"
                f"👤 *Nome:* {target_user.name}\n"
                f"🏢 *Setor:* {target_user.department or 'Geral'}\n"
                f"💼 *Cargo:* {target_user.job_title or 'Funcionário'}\n\n"
                f"📸 A partir de agora, envie qualquer foto de *cupom fiscal ou recibo* aqui para registrar seu reembolso!"
            )
            await wuzapi_client.send_text_message(target_user.phone, welcome_employee)
            await wuzapi_client.send_text_message(phone, f"✅ Funcionário *{target_user.name}* ({target_user.department or 'Geral'}) foi *APROVADO* com sucesso!")

        elif action == "RECUSAR":
            target_user.company_id = None
            target_user.is_approved = False
            target_user.onboarding_step = None
            await db.commit()

            await wuzapi_client.send_text_message(target_user.phone, f"❌ Sua solicitação de vínculo com a empresa *{company.name}* foi recusada pelo gestor.")
            await wuzapi_client.send_text_message(phone, f"❌ Solicitação de *{target_user.name}* foi recusada.")

        return {"status": "ok"}

    async def handle_limite(self, clean_text: str, phone: str, user: User, company: Company, db: AsyncSession) -> dict:
        """Comando: LIMITE ALIMENTACAO 60"""
        from app.models import PolicyRule, ExpenseCategory
        
        if user.role != UserRole.ADMIN:
            await wuzapi_client.send_text_message(phone, "❌ Apenas gestores podem configurar políticas.")
            return {"status": "ok"}

        parts = clean_text.split()
        if len(parts) < 3:
            await wuzapi_client.send_text_message(phone, "❌ Formato incorreto. Use: *LIMITE [CATEGORIA] [VALOR]*\nExemplo: *LIMITE ALIMENTACAO 60*")
            return {"status": "ok"}

        cat_str = parts[1].upper()
        try:
            category_enum = ExpenseCategory[cat_str]
        except KeyError:
            await wuzapi_client.send_text_message(phone, "❌ Categoria inválida. Categorias: ALIMENTACAO, TRANSPORTE, HOSPEDAGEM, COMBUSTIVEL, MANUTENCAO, OUTROS.")
            return {"status": "ok"}

        try:
            val_str = parts[2].replace("R$", "").replace(",", ".").strip()
            max_amount = float(val_str)
        except ValueError:
            await wuzapi_client.send_text_message(phone, "❌ Valor inválido. Use números, exemplo: 60.00")
            return {"status": "ok"}

        # Verificar se já existe a regra
        query = select(PolicyRule).where(
            PolicyRule.company_id == company.id,
            PolicyRule.category == category_enum
        )
        res = await db.execute(query)
        rule = res.scalars().first()

        if rule:
            rule.max_amount = max_amount
            rule.is_active = True
        else:
            rule = PolicyRule(
                id=str(uuid.uuid4()),
                company_id=company.id,
                category=category_enum,
                max_amount=max_amount,
                requires_receipt=True
            )
            db.add(rule)

        await db.commit()
        await wuzapi_client.send_text_message(phone, f"✅ **Política Atualizada!**\nO limite para `{category_enum.value}` agora é **R$ {max_amount:.2f}**.")
        return {"status": "ok"}

    async def handle_exportar(self, clean_text: str, phone: str, user: User, company: Company, db: AsyncSession) -> dict:
        if user.role != UserRole.ADMIN:
            await wuzapi_client.send_text_message(phone, "❌ Apenas gestores podem exportar relatórios.")
            return {"status": "ok"}

        today = date.today()
        exp_query = select(Expense).where(
            Expense.company_id == company.id,
            Expense.expense_date >= today.replace(day=1),
            Expense.status == ExpenseStatus.APPROVED
        )
        exp_res = await db.execute(exp_query)
        expenses = exp_res.scalars().all()

        if not expenses:
            await wuzapi_client.send_text_message(phone, "❌ Nenhuma despesa aprovada no mês atual para exportar.")
            return {"status": "ok"}

        import io
        import csv
        
        output = io.StringIO()
        writer = csv.writer(output, delimiter=';')
        writer.writerow(["ID", "Data", "Funcionario_Phone", "Categoria", "Estabelecimento", "CNPJ", "Valor", "Tem_Recibo"])
        
        total = 0
        for e in expenses:
            writer.writerow([
                e.id[:8],
                e.expense_date.strftime("%d/%m/%Y"),
                e.user_phone,
                e.category.value,
                e.merchant_name,
                e.merchant_cnpj or "-",
                f"{e.amount:.2f}".replace(".", ","),
                "SIM" if e.has_receipt else "NAO"
            ])
            total += float(e.amount)
            
        writer.writerow([])
        writer.writerow(["TOTAL", "", "", "", "", "", f"{total:.2f}".replace(".", ",")])

        csv_content = output.getvalue()
        file_bytes = csv_content.encode('utf-8')
        
        # Em produção mandaríamos por document no WuzAPI, ou enviamos um link temporário, ou o texto cru formatado.
        # WuzAPI tem endpoint sendDocument? Como fallback vamos mandar um preview.
        preview = "📊 **Resumo CSV Exportado (copie e cole no Excel)**\n\n"
        preview += "ID;Data;Telefone;Categoria;Local;CNPJ;Valor;Recibo\n"
        for row in csv_content.split("\n")[1:10]: # Manda até 10 linhas como preview
            if row.strip():
                preview += row + "\n"
        preview += f"\n*... e mais {len(expenses)} despesas.*\nTotal Aprovado: R$ {total:.2f}"
        
        await wuzapi_client.send_text_message(phone, preview)
        return {"status": "ok"}

    async def handle_despesa(self, clean_text: str, phone: str, user: User, company: Company, db: AsyncSession) -> dict:
        """Comando: DESPESA 50.00 Almoço com cliente"""
        if not company:
            await wuzapi_client.send_text_message(phone, "❌ Você precisa estar vinculado a uma empresa para lançar despesas.")
            return {"status": "ok"}

        parts = clean_text.split(" ", 2)
        if len(parts) < 3:
            await wuzapi_client.send_text_message(phone, "❌ Formato incorreto. Use: *DESPESA [valor] [justificativa]*\nExemplo: *DESPESA 45.50 Almoço com cliente*")
            return {"status": "ok"}

        try:
            val_str = parts[1].replace("R$", "").replace(",", ".").strip()
            amount = float(val_str)
        except ValueError:
            await wuzapi_client.send_text_message(phone, "❌ Valor inválido. Use números, exemplo: 45.50")
            return {"status": "ok"}

        justification = parts[2].strip()

        # Validação de Política
        is_valid, policy_reason = await policy_service.validate_expense(
            company_id=user.company_id,
            category=ExpenseCategory.OUTROS,
            amount=amount,
            has_receipt=False,
            db=db
        )

        expense_id = str(uuid.uuid4())
        new_expense = Expense(
            id=expense_id,
            user_phone=phone,
            company_id=user.company_id,
            merchant_name="Despesa sem Comprovante",
            amount=amount,
            expense_date=date.today(),
            category=ExpenseCategory.OUTROS,
            status=ExpenseStatus.PENDING if is_valid else ExpenseStatus.REJECTED,
            rejection_reason=policy_reason if not is_valid else None,
            justification=justification,
            has_receipt=False
        )
        db.add(new_expense)
        await db.commit()

        if is_valid:
            confirm_msg = (
                f"✅ **Despesa Lançada!** (Sem Comprovante)\n\n"
                f"💰 **Valor:** R$ {amount:.2f}\n"
                f"📝 **Motivo:** {justification}\n\n"
                f"📋 *Status:* Pendente de Aprovação do Gestor."
            )
            await wuzapi_client.send_text_message(phone, confirm_msg)

            if company and company.admin_phone and company.admin_phone != phone:
                admin_alert = (
                    f"📥 **[Aviso Gestor]** Nova despesa SEM COMPROVANTE de **{user.name or phone}**:\n"
                    f"💰 R$ {amount:.2f}\n"
                    f"📝 Motivo: {justification}\n\n"
                    f"Responda *APROVAR {expense_id[:4]}* ou *REJEITAR {expense_id[:4]}*"
                )
                await wuzapi_client.send_text_message(company.admin_phone, admin_alert)
        else:
            await wuzapi_client.send_text_message(
                phone,
                f"❌ Sua despesa manual foi **REJEITADA AUTOMATICAMENTE** pelas políticas da empresa.\nMotivo: {policy_reason}"
            )

        return {"status": "ok"}

    async def handle_km(self, clean_text: str, phone: str, user: User, company: Company, db: AsyncSession) -> dict:
        """Comando: KM 42"""
        if not company:
            await wuzapi_client.send_text_message(phone, "❌ Você precisa estar vinculado a uma empresa.")
            return {"status": "ok"}

        parts = clean_text.split(" ", 1)
        if len(parts) < 2:
            await wuzapi_client.send_text_message(phone, "❌ Formato incorreto. Use: *KM [distância]*\nExemplo: *KM 45.5*")
            return {"status": "ok"}

        try:
            km_str = parts[1].replace("km", "").replace(",", ".").strip()
            distance = float(km_str)
        except ValueError:
            await wuzapi_client.send_text_message(phone, "❌ Distância inválida. Exemplo: 45.5")
            return {"status": "ok"}

        rate = company.km_rate or 0.0
        if rate <= 0:
            await wuzapi_client.send_text_message(phone, "❌ Sua empresa não configurou um valor de reembolso por KM (km_rate). Fale com seu gestor.")
            return {"status": "ok"}

        amount = distance * float(rate)
        expense_id = str(uuid.uuid4())
        new_expense = Expense(
            id=expense_id,
            user_phone=phone,
            company_id=user.company_id,
            merchant_name=f"Reembolso de KM ({distance} km)",
            amount=amount,
            expense_date=date.today(),
            category=ExpenseCategory.TRANSPORTE,
            status=ExpenseStatus.PENDING,
            justification=f"Deslocamento de {distance} km. Taxa: R${rate:.2f}/km",
            has_receipt=False
        )
        db.add(new_expense)
        await db.commit()

        confirm_msg = (
            f"🚗 **KM Registrado!**\n\n"
            f"🛣️ **Distância:** {distance} km\n"
            f"💰 **Valor Reembolso:** R$ {amount:.2f}\n"
            f"📋 *Status:* Pendente de Aprovação."
        )
        await wuzapi_client.send_text_message(phone, confirm_msg)

        if company and company.admin_phone and company.admin_phone != phone:
            admin_alert = (
                f"🚗 **[Aviso Gestor]** Reembolso de KM de **{user.name or phone}**:\n"
                f"Distância: {distance} km\n"
                f"Valor: R$ {amount:.2f}\n\n"
                f"Responda *APROVAR {expense_id[:4]}* ou *REJEITAR {expense_id[:4]}*"
            )
            await wuzapi_client.send_text_message(company.admin_phone, admin_alert)

        return {"status": "ok"}

command_handler = CommandHandler()
