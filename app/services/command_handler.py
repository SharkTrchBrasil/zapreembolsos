import logging
import uuid
from datetime import date, datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError
from app.models import User, Company, Expense, UserRole, ExpenseStatus, PlanType, ExpenseCategory
from app.services.wuzapi_service import wuzapi_client
from app.services.policy_service import policy_service
from app.services.audit_service import audit_service
import random

def generate_company_code(name: str) -> str:
    """Gera um código único curto como #ALFA1 ou #POSTO7."""
    clean_name = "".join(c for c in name if c.isalnum()).upper()[:4]
    random_num = random.randint(10, 999)
    return f"{clean_name}{random_num}"

logger = logging.getLogger("command_handler")

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
                try:
                    await db.commit()
                except Exception as e:
                    await db.rollback()
                    logger.error(f"DB error: {e}")
                    await wuzapi_client.send_text_message(phone, "❌ Ocorreu um erro interno. Tente novamente.")
                    return {"status": "error"}
                break
            except IntegrityError:
                await db.rollback()
        else:
            await wuzapi_client.send_text_message(phone, "❌ Erro ao criar empresa (conflito de código). Tente outro nome.")
            return {"status": "error"}

        user.company_id = new_company.id
        user.role = UserRole.ADMIN
        user.name = f"Gestor ({company_name})"
        
        # Seed default department
        from app.models import Department, Category
        default_dept = Department(
            id=str(uuid.uuid4()),
            company_id=new_company.id,
            name="Geral"
        )
        db.add(default_dept)
        
        # Seed default categories
        default_cats = [
            ("Alimentação", "🍔"),
            ("Transporte", "🚗"),
            ("Hospedagem", "🏨"),
            ("Combustível", "⛽"),
            ("Manutenção", "🛠️"),
            ("Outros", "📦")
        ]
        for cat_name, icon in default_cats:
            db.add(Category(
                id=str(uuid.uuid4()),
                company_id=new_company.id,
                name=cat_name,
                icon=icon
            ))
            
        # Seed Default Roles
        from app.models import Role, Permission, RolePermission, UserRoleModel
        roles_to_create = [
            ("OWNER", True),
            ("GESTOR_FULL", False),
            ("GESTOR_LIMITADO", False),
            ("APROVADOR_DEPTO", False),
            ("EMPLOYEE", False)
        ]
        
        created_roles = {}
        for role_name, is_sys in roles_to_create:
            r = Role(id=str(uuid.uuid4()), company_id=new_company.id, name=role_name, is_system_role=is_sys)
            db.add(r)
            created_roles[role_name] = r
            
        try:
            await db.commit() # Commit para poder usar os IDs das Roles e buscar Permissions
        except Exception as e:
            await db.rollback()
            logger.error(f"DB error: {e}")
            await wuzapi_client.send_text_message(phone, "❌ Ocorreu um erro interno. Tente novamente.")
            return {"status": "error"}
        
        # Atribuir todas as permissões ao OWNER
        query_perms = select(Permission)
        res_perms = await db.execute(query_perms)
        all_perms = res_perms.scalars().all()
        
        for p in all_perms:
            db.add(RolePermission(id=str(uuid.uuid4()), role_id=created_roles["OWNER"].id, permission_id=p.id))
            
            # GESTOR_FULL recebe tudo menos manage_company
            if p.code != "manage_company":
                db.add(RolePermission(id=str(uuid.uuid4()), role_id=created_roles["GESTOR_FULL"].id, permission_id=p.id))
                
            # GESTOR_LIMITADO recebe apenas relatórios
            if p.code in ["view_reports", "export_data"]:
                db.add(RolePermission(id=str(uuid.uuid4()), role_id=created_roles["GESTOR_LIMITADO"].id, permission_id=p.id))
                
            # APROVADOR_DEPTO recebe aprovação e relatórios
            if p.code in ["approve_expenses", "view_reports"]:
                db.add(RolePermission(id=str(uuid.uuid4()), role_id=created_roles["APROVADOR_DEPTO"].id, permission_id=p.id))

        user.department_id = default_dept.id
        
        # Atribuir OWNER ao criador
        db.add(UserRoleModel(
            id=str(uuid.uuid4()),
            user_phone=user.phone,
            role_id=created_roles["OWNER"].id,
            scope="COMPANY"
        ))
        
        try:
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error(f"DB error: {e}")
            await wuzapi_client.send_text_message(phone, "❌ Ocorreu um erro interno. Tente novamente.")
            return {"status": "error"}

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

    async def handle_ajuda(self, phone: str, user: User) -> dict:
        # Deprecated: A lógica de menu agora vive no menu_service.py e é interceptada no webhook.py
        return {"status": "ok"}

    async def handle_vincular(self, clean_text: str, phone: str, user: User, db: AsyncSession) -> dict:
        raw_code = clean_text.replace("#", "").replace("ENTRAR", "").strip().upper()
        comp_query = select(Company).where(Company.code == raw_code)
        comp_res = await db.execute(comp_query)
        target_company = comp_res.scalar_one_or_none()

        if target_company:
            user.company_id = target_company.id
            user.role = UserRole.EMPLOYEE
            user.is_approved = False
            try:
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error(f"DB error: {e}")
                await wuzapi_client.send_text_message(phone, "❌ Ocorreu um erro interno. Tente novamente.")
                return {"status": "error"}

            link_msg = (
                f"⏳ *Solicitação enviada com sucesso!*\n\n"
                f"Sua solicitação para a empresa *{target_company.name}* foi enviada ao gestor.\n"
                f"Assim que ele aprovar seu cadastro, você receberá uma notificação aqui e poderá enviar seus comprovantes!"
            )
            await wuzapi_client.send_text_message(phone, link_msg)

            admin_alert = (
                f"👤 *Solicitação de Cadastro - ZapReembolso*\n"
                f"Um novo funcionário solicitou vínculo à sua empresa via código:\n\n"
                f"👤 *Nome:* {user.name or 'Não informado'}\n"
                f"📱 *WhatsApp:* {user.phone}\n\n"
                f"----------------------------------\n"
                f"Responda este chat para autorizar:\n"
                f"1 - ✅ *ACEITAR*\n"
                f"2 - ❌ *RECUSAR*"
            )
            await wuzapi_client.send_text_message(target_company.admin_phone, admin_alert)
        else:
            await wuzapi_client.send_text_message(phone, f"❌ Código `#{raw_code}` não encontrado. Verifique com seu gestor o código correto da empresa.")
        return {"status": "ok"}

    async def handle_relatorio(self, clean_text: str, phone: str, user: User, company: Company, db: AsyncSession) -> dict:
        if not company:
            await wuzapi_client.send_text_message(phone, "❌ Empresa não encontrada.")
            return {"status": "ok"}

        today = date.today()
        raw_lower = clean_text.lower().strip()

        # 1. Caso o usuário peça especificamente o Ranking ("quem mais gastou")
        if any(w in raw_lower for w in ["ranking", "quem mais gastou", "top"]):
            return await self.handle_ranking(phone, company, db)

        # 2. Tenta extração NLU se houver texto livre além da palavra "RELATORIO"
        import re
        is_simple_command = bool(re.fullmatch(r'^(relat[oó]rio|\d+)(?:\s+\d+)?$', raw_lower))
        
        nlu = {}
        if not is_simple_command:
            from app.services.nlu_service import nlu_service
            nlu = await nlu_service.parse_expense_query(clean_text)

        # Se for ação de Ranking via NLU
        if nlu.get("action") == "RANKING":
            return await self.handle_ranking(phone, company, db)

        # 3. Montagem de Filtros no Banco de Dados
        exp_query = select(Expense).options(joinedload(Expense.user)).where(Expense.company_id == company.id)

        # Filtro de Pessoa (Funcionário Específico)
        target_person_name = nlu.get("person_name")
        if target_person_name:
            user_subquery = select(User.phone).where(
                User.company_id == company.id,
                User.name.ilike(f"%{target_person_name}%")
            )
            user_phones_res = await db.execute(user_subquery)
            phones_list = user_phones_res.scalars().all()
            if phones_list:
                exp_query = exp_query.where(Expense.user_phone.in_(phones_list))
            else:
                await wuzapi_client.send_text_message(
                    phone, 
                    f"⚠️ Nenhum funcionário ativo encontrado com o nome *{target_person_name}*."
                )
                return {"status": "ok"}

        # Filtro de Categoria
        if nlu.get("category"):
            try:
                cat_enum = ExpenseCategory[nlu["category"]]
                exp_query = exp_query.where(Expense.category == cat_enum)
            except KeyError:
                pass

        # Filtro de Data (Padrão: mês atual se não informado range)
        if nlu.get("start_date") and nlu.get("end_date"):
            try:
                s_date = datetime.strptime(nlu["start_date"], "%Y-%m-%d").date()
                e_date = datetime.strptime(nlu["end_date"], "%Y-%m-%d").date()
                exp_query = exp_query.where(Expense.expense_date >= s_date, Expense.expense_date <= e_date)
                period_str = f"{s_date.strftime('%d/%m/%Y')} até {e_date.strftime('%d/%m/%Y')}"
            except Exception:
                from sqlalchemy import or_
                month_start_date = today.replace(day=1)
                month_start_dt = datetime.combine(month_start_date, datetime.min.time(), tzinfo=timezone.utc)
                exp_query = exp_query.where(or_(
                    Expense.expense_date >= month_start_date,
                    Expense.created_at >= month_start_dt,
                    Expense.status == ExpenseStatus.PENDING
                ))
                period_str = f"Mês Atual ({today.strftime('%m/%Y')}) + Pendentes"
        else:
            from sqlalchemy import or_
            month_start_date = today.replace(day=1)
            month_start_dt = datetime.combine(month_start_date, datetime.min.time(), tzinfo=timezone.utc)
            exp_query = exp_query.where(or_(
                Expense.expense_date >= month_start_date,
                Expense.created_at >= month_start_dt,
                Expense.status == ExpenseStatus.PENDING
            ))
            period_str = f"Mês Atual ({today.strftime('%m/%Y')}) + Pendentes"

        exp_res = await db.execute(exp_query)
        all_expenses = exp_res.scalars().all()

        if not all_expenses:
            person_note = f" de *{target_person_name}*" if target_person_name else ""
            await wuzapi_client.send_text_message(
                phone, 
                f"ℹ️ Nenhuma despesa registrada{person_note} no período (*{period_str}*)."
            )
            return {"status": "ok"}

        total_amount = sum(e.amount for e in all_expenses)
        pending_expenses = [e for e in all_expenses if e.status == ExpenseStatus.PENDING]
        approved_expenses = [e for e in all_expenses if e.status in (ExpenseStatus.APPROVED, ExpenseStatus.REIMBURSED)]

        by_category = {}
        by_user = {}
        for e in all_expenses:
            cat_name = e.category.value if hasattr(e.category, 'value') else str(e.category)
            by_category[cat_name] = by_category.get(cat_name, 0.0) + float(e.amount)
            
            user_name = e.user.name if e.user and e.user.name else e.user_phone
            by_user[user_name] = by_user.get(user_name, 0.0) + float(e.amount)

        cat_summary = "\n".join([f"• *{cat}:* R$ {amt:.2f}" for cat, amt in by_category.items()]) or "Nenhuma despesa"
        
        user_summary = ""
        if len(by_user) > 1 or (not target_person_name and len(by_user) == 1):
            user_summary = "\n👤 *Por Funcionário:*\n" + "\n".join([f"• *{u}:* R$ {amt:.2f}" for u, amt in sorted(by_user.items(), key=lambda x: x[1], reverse=True)]) + "\n"

        title_person = f" - {target_person_name}" if target_person_name else ""

        report_msg = (
            f"📊 *Relatório de Despesas{title_person} ({period_str})*\n\n"
            f"💰 *Total Acumulado:* R$ {total_amount:.2f} ({len(all_expenses)} comprovantes)\n"
            f"✅ *Aprovadas:* R$ {sum(e.amount for e in approved_expenses):.2f}\n"
            f"⏳ *Pendentes:* {len(pending_expenses)} (R$ {sum(e.amount for e in pending_expenses):.2f})\n\n"
            f"🏷️ *Por Categoria:*\n{cat_summary}\n"
            f"{user_summary}"
        )
        
        if pending_expenses and user.role == UserRole.ADMIN:
            import re
            page_match = re.search(r'\b(pag|page|pagina|página|p)\s*(\d+)\b|\b(\d+)\b', clean_text.lower())
            page = 1
            if page_match:
                page_str = page_match.group(2) or page_match.group(3)
                if page_str:
                    page = max(1, int(page_str))
            
            per_page = 5
            total_pages = (len(pending_expenses) + per_page - 1) // per_page
            page = min(page, total_pages)
            
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            
            report_msg += f"\n📋 *Despesas Pendentes (Pág {page}/{total_pages}):*\n"
            for p in pending_expenses[start_idx:end_idx]:
                p_user_name = p.user.name if p.user and p.user.name else p.user_phone
                p_date = p.expense_date.strftime("%d/%m") if p.expense_date else ""
                report_msg += f"• [{p.id[:4]}] {p_user_name} - {p.merchant_name} (R$ {p.amount:.2f}) {p_date}\n"
                
            if total_pages > page:
                report_msg += f"\n💡 *Para ver mais pendentes, envie:* RELATORIO {page+1}"
            report_msg += "\n💡 *Para aprovar:* responda *1* ou *APROVAR [ID]*."

        await wuzapi_client.send_text_message(phone, report_msg)
        return {"status": "ok"}

    async def handle_ranking(self, phone: str, company: Company, db: AsyncSession) -> dict:
        """Gera o ranking dos funcionários que mais gastaram no mês corrente."""
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

        if not all_expenses:
            await wuzapi_client.send_text_message(phone, "ℹ️ Nenhuma despesa registrada neste mês para gerar ranking.")
            return {"status": "ok"}

        user_totals = {}
        for e in all_expenses:
            user_totals[e.user_phone] = user_totals.get(e.user_phone, 0.0) + float(e.amount)

        # Ordena do maior para o menor
        sorted_users = sorted(user_totals.items(), key=lambda x: x[1], reverse=True)[:5]

        # Busca os nomes dos usuários
        phones_to_fetch = [u_phone for u_phone, _ in sorted_users]
        u_query = select(User).where(User.company_id == company.id, User.phone.in_(phones_to_fetch))
        u_res = await db.execute(u_query)
        users_batch = {u.phone: u for u in u_res.scalars().all()}
        
        ranking_msg = f"🏆 *Ranking de Maiores Gastos do Mês ({today.strftime('%m/%Y')})*\n\n"
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]

        for idx, (u_phone, total) in enumerate(sorted_users):
            u_obj = users_batch.get(u_phone)
            u_name = u_obj.name if (u_obj and u_obj.name) else u_phone
            u_dept = f" ({u_obj.department})" if (u_obj and u_obj.department) else ""
            ranking_msg += f"{medals[idx]} *{u_name}*{u_dept}: R$ {total:.2f}\n"

        ranking_msg += f"\n💡 *Total da equipe no mês:* R$ {sum(user_totals.values()):.2f}"
        await wuzapi_client.send_text_message(phone, ranking_msg)
        return {"status": "ok"}

    async def handle_exportar(self, clean_text: str, phone: str, user: User, company: Company, db: AsyncSession) -> dict:
        if not company:
            await wuzapi_client.send_text_message(phone, "❌ Empresa não encontrada.")
            return {"status": "ok"}
            
        if user.role != UserRole.ADMIN:
            await wuzapi_client.send_text_message(phone, "❌ Apenas gestores podem exportar relatórios.")
            return {"status": "ok"}
            
        today = date.today()
        exp_query = select(Expense).where(
            Expense.company_id == company.id,
            Expense.expense_date >= today.replace(day=1)
        )
        exp_res = await db.execute(exp_query)
        all_expenses = exp_res.scalars().all()

        if not all_expenses:
            await wuzapi_client.send_text_message(phone, "ℹ️ Nenhuma despesa registrada neste mês para exportar.")
            return {"status": "ok"}

        # Gerar CSV
        import csv
        import io
        import base64
        
        output = io.StringIO()
        writer = csv.writer(output, delimiter=';')
        writer.writerow(['ID', 'Data', 'Funcionario', 'Categoria', 'Estabelecimento', 'CNPJ', 'Valor', 'Status'])

        for e in all_expenses:
            cat_name = e.category.value if hasattr(e.category, 'value') else str(e.category)
            status_name = e.status.value if hasattr(e.status, 'value') else str(e.status)
            writer.writerow([
                e.id[:8],
                e.expense_date.strftime("%d/%m/%Y"),
                e.user_phone,
                cat_name,
                e.merchant_name or '',
                e.merchant_cnpj or '',
                f"{e.amount:.2f}".replace('.', ','),
                status_name
            ])

        csv_content = output.getvalue().encode('utf-8')
        b64_csv = base64.b64encode(csv_content).decode('utf-8')
        filename = f"Relatorio_Despesas_{company.name.replace(' ', '_')}_{today.strftime('%Y_%m')}.csv"

        caption = f"📊 *Relatório Exportado com Sucesso!*\n\nEmpresa: {company.name}\nPeríodo: Mês {today.strftime('%m/%Y')}\nTotal de Lançamentos: {len(all_expenses)}\n\nO arquivo CSV está anexado acima e pode ser aberto no Excel."
        
        await wuzapi_client.send_document_message(
            phone=phone,
            document_base64=b64_csv,
            filename=filename,
            caption=caption
        )
        return {"status": "ok"}

    async def handle_aprovar_rejeitar(self, clean_text: str, phone: str, user: User, company: Company, db: AsyncSession, bypass_confirm: bool = False) -> dict:
        if not company:
            await wuzapi_client.send_text_message(phone, "❌ Empresa não encontrada.")
            return {"status": "ok"}
            
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
            Expense.status.in_([ExpenseStatus.PENDING, ExpenseStatus.PARTIALLY_APPROVED]),
            Expense.id.like(f"{short_id}%")
        )
        exp_res = await db.execute(exp_query)
        exps = exp_res.scalars().all()

        if not exps:
            await wuzapi_client.send_text_message(phone, f"❌ Despesa '{short_id}' não encontrada ou já processada.")
            return {"status": "ok"}
            
        if len(exps) > 1:
            msg = f"⚠️ Múltiplas despesas encontradas com o ID '{short_id}'. Por favor, seja mais específico:\n"
            for e in exps[:5]:
                msg += f"• *{action} {e.id[:8]}* (R$ {e.amount:.2f})\n"
            await wuzapi_client.send_text_message(phone, msg)
            return {"status": "ok"}
            
        exp = exps[0]
            
        if not bypass_confirm:
            user.onboarding_step = f"CONFIRM_{action}_{exp.id}"
            try:
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error(f"DB error: {e}")
                await wuzapi_client.send_text_message(phone, "❌ Ocorreu um erro interno. Tente novamente.")
                return {"status": "error"}
            
            action_pt = "aprovar" if action == "APROVAR" else "rejeitar"
            await wuzapi_client.send_text_message(
                phone,
                f"⚠️ *Tem certeza* que deseja {action_pt} a despesa de R$ {exp.amount:.2f} do estabelecimento {exp.merchant_name}?\n\n"
                f"Responda *SIM* para confirmar, ou *CANCELAR* para abortar."
            )
            return {"status": "ok"}

        from datetime import datetime, timezone
        from app.models import PolicyRule, ApprovalStep
        import uuid
        
        # Lógica de Aprovação Dupla (Cadeia)
        if action == "APROVAR":
            policy_query = select(PolicyRule).where(
                PolicyRule.company_id == exp.company_id,
                PolicyRule.category_id == exp.category_id,
                PolicyRule.is_active == True
            )
            pol_res = await db.execute(policy_query)
            policy = pol_res.scalar_one_or_none()
            
            # Fallback para política global se não houver específica
            if not policy:
                g_query = select(PolicyRule).where(
                    PolicyRule.company_id == exp.company_id,
                    PolicyRule.category_id == None,
                    PolicyRule.is_active == True
                )
                g_res = await db.execute(g_query)
                policy = g_res.scalar_one_or_none()
                
            req_double = policy.requires_double_approval_above if policy else None
            
            # Cria o ApprovalStep do gestor atual
            step_count_query = select(ApprovalStep).where(ApprovalStep.expense_id == exp.id)
            step_count_res = await db.execute(step_count_query)
            existing_steps = step_count_res.scalars().all()
            
            # Se a despesa for cara e esta for a primeira aprovação, vira PARTIALLY_APPROVED
            if req_double is not None and exp.amount > float(req_double) and len(existing_steps) == 0:
                new_status = ExpenseStatus.PARTIALLY_APPROVED
                
            step = ApprovalStep(
                id=str(uuid.uuid4()),
                expense_id=exp.id,
                step_order=len(existing_steps) + 1,
                approver_phone=phone,
                status="APPROVED",
                decided_at=datetime.now(timezone.utc)
            )
            db.add(step)

        exp.status = new_status
        exp.approved_by = phone
        exp.approved_at = datetime.now(timezone.utc)
        
        if action == "REJEITAR":
            exp.rejection_reason = rejection_reason or "Rejeitado pelo gestor"

        try:
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error(f"DB error: {e}")
            await wuzapi_client.send_text_message(phone, "❌ Ocorreu um erro interno. Tente novamente.")
            return {"status": "error"}
        
        await audit_service.log_action(
            db=db,
            company_id=user.company_id,
            user_phone=user.phone,
            action=f"{action}_EXPENSE",
            entity_type="Expense",
            entity_id=exp.id,
            new_value=exp.status.value
        )
        
        # Converte o status para português
        if new_status == ExpenseStatus.APPROVED:
            status_pt = "APROVADA"
        elif new_status == ExpenseStatus.REJECTED:
            status_pt = "REJEITADA"
        else:
            status_pt = "PRÉ-APROVADA (Aguardando Diretoria)"
        
        # Notifica o funcionário
        employee_msg = f"🔔 **Sua despesa foi {status_pt}!**\n📍 {exp.merchant_name} (R$ {exp.amount:.2f})\n"
        if action == "REJEITAR":
            employee_msg += f"❌ **Motivo:** {exp.rejection_reason}\n\n"
            employee_msg += f"💡 _Dica: Para corrigir e reenviar, você pode digitar:_ *REENVIAR {short_id}*"
        elif new_status == ExpenseStatus.PARTIALLY_APPROVED:
            employee_msg += "✅ Aprovada pelo gestor local. Enviada para aprovação final da diretoria."
        else:
            employee_msg += "✅ Reembolso autorizado pelo gestor."
            
        await wuzapi_client.send_text_message(exp.user_phone, employee_msg)

        if new_status == ExpenseStatus.PARTIALLY_APPROVED and company and company.admin_phone:
            # Envia para o Master Admin
            await wuzapi_client.send_text_message(
                company.admin_phone,
                f"📥 *Aprovação Dupla Necessária*\n\n"
                f"O gestor {user.name or phone} pré-aprovou a despesa de R$ {exp.amount:.2f} de {exp.merchant_name} (Func: {exp.user_phone}).\n"
                f"Por exceder o teto, requer sua aprovação final.\n\n"
                f"Responda *APROVAR {short_id}* ou *REJEITAR {short_id} [motivo]*."
            )
            
            await wuzapi_client.send_text_message(
                phone,
                f"✅ **Despesa pré-aprovada!** Por exceder o limite, ela foi enviada para o administrador geral."
            )
        else:
            await wuzapi_client.send_text_message(
                phone,
                f"✅ **Despesa de {exp.merchant_name} (R$ {exp.amount:.2f}) {status_pt}!** O funcionário foi notificado."
            )
        return {"status": "ok"}

    async def handle_aceitar_recusar(self, clean_text: str, phone: str, user: User, company: Company, db: AsyncSession, bypass_confirm: bool = False) -> dict:
        """Permite que o gestor aceite ou recuse a solicitação de um funcionário."""
        if not company:
            await wuzapi_client.send_text_message(phone, "❌ Empresa não encontrada.")
            return {"status": "ok"}
            
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
            
        if not bypass_confirm:
            user.onboarding_step = f"CONFIRM_{action}_{target_user.phone}"
            try:
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error(f"DB error: {e}")
                await wuzapi_client.send_text_message(phone, "❌ Ocorreu um erro interno. Tente novamente.")
                return {"status": "error"}
            
            action_pt = "aceitar" if action == "ACEITAR" else "recusar"
            await wuzapi_client.send_text_message(
                phone,
                f"⚠️ *Tem certeza* que deseja {action_pt} o funcionário *{target_user.name}* ({target_user.phone})?\n\n"
                f"Responda *SIM* para confirmar, ou *CANCELAR* para abortar."
            )
            return {"status": "ok"}

        if action == "ACEITAR":
            target_user.is_approved = True
            target_user.onboarding_step = None
            try:
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error(f"DB error: {e}")
                await wuzapi_client.send_text_message(phone, "❌ Ocorreu um erro interno. Tente novamente.")
                return {"status": "error"}

            await audit_service.log_action(
                db=db,
                company_id=user.company_id,
                user_phone=user.phone,
                action="APPROVE_USER",
                entity_type="User",
                entity_id=target_user.phone,
                new_value="Approved"
            )

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
            try:
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error(f"DB error: {e}")
                await wuzapi_client.send_text_message(phone, "❌ Ocorreu um erro interno. Tente novamente.")
                return {"status": "error"}

            await audit_service.log_action(
                db=db,
                company_id=user.company_id,
                user_phone=user.phone,
                action="REJECT_USER",
                entity_type="User",
                entity_id=target_user.phone,
                new_value="Rejected (Unlinked)"
            )

            await wuzapi_client.send_text_message(target_user.phone, f"❌ Sua solicitação de vínculo com a empresa *{company.name}* foi recusada pelo gestor.")
            await wuzapi_client.send_text_message(phone, f"❌ Solicitação de *{target_user.name}* foi recusada.")

        return {"status": "ok"}

    async def handle_limite(self, clean_text: str, phone: str, user: User, company: Company, db: AsyncSession) -> dict:
        """Comando: LIMITE ALIMENTACAO 60"""
        from app.models import PolicyRule, ExpenseCategory
        
        if not company:
            await wuzapi_client.send_text_message(phone, "❌ Empresa não encontrada.")
            return {"status": "ok"}
            
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

        try:
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error(f"DB error: {e}")
            await wuzapi_client.send_text_message(phone, "❌ Ocorreu um erro interno. Tente novamente.")
            return {"status": "error"}

        await audit_service.log_action(
            db=db,
            company_id=user.company_id,
            user_phone=user.phone,
            action="CHANGE_LIMIT",
            entity_type="PolicyRule",
            entity_id=rule.id,
            new_value=str(max_amount)
        )
        await wuzapi_client.send_text_message(phone, f"✅ **Política Atualizada!**\nO limite para `{category_enum.value}` agora é **R$ {max_amount:.2f}**.")
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
        # Buscar category_id padrão para "OUTROS"
        cat_query = select(Category.id).where(Category.company_id == user.company_id, Category.name == "Outros")
        cat_res = await db.execute(cat_query)
        cat_id = cat_res.scalar_one_or_none()
        
        is_valid, policy_reason, auto_approve_below = await policy_service.validate_expense(
            company_id=user.company_id,
            category_id=cat_id,
            amount=amount,
            has_receipt=False,
            expense_date=date.today(),
            db=db
        )

        final_status = ExpenseStatus.REJECTED
        if is_valid:
            if auto_approve_below > 0 and amount <= auto_approve_below:
                final_status = ExpenseStatus.APPROVED
            else:
                final_status = ExpenseStatus.PENDING
                
        expense_id = str(uuid.uuid4())
        new_expense = Expense(
            id=expense_id,
            user_phone=phone,
            company_id=user.company_id,
            merchant_name="Despesa sem Comprovante",
            amount=amount,
            expense_date=date.today(),
            category=ExpenseCategory.OUTROS,
            status=final_status,
            rejection_reason=policy_reason if not is_valid else None,
            justification=justification,
            has_receipt=False
        )
        db.add(new_expense)
        try:
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error(f"DB error: {e}")
            await wuzapi_client.send_text_message(phone, "❌ Ocorreu um erro interno. Tente novamente.")
            return {"status": "error"}

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
                    f"📥 Nova despesa **SEM COMPROVANTE** de **{user.name or phone}**:\n"
                    f"💰 R$ {amount:.2f}\n"
                    f"📝 Motivo: {justification}\n\n"
                    f"Responda *1* para *APROVAR* ou *2* para *REJEITAR*"
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
        try:
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error(f"DB error: {e}")
            await wuzapi_client.send_text_message(phone, "❌ Ocorreu um erro interno. Tente novamente.")
            return {"status": "error"}

        confirm_msg = (
            f"🚗 **KM Registrado!**\n\n"
            f"🛣️ **Distância:** {distance} km\n"
            f"💰 **Valor Reembolso:** R$ {amount:.2f}\n"
            f"📋 *Status:* Pendente de Aprovação."
        )
        await wuzapi_client.send_text_message(phone, confirm_msg)

        if company and company.admin_phone and company.admin_phone != phone:
            admin_alert = (
                f"🚗 Reembolso de KM de **{user.name or phone}**:\n"
                f"Distância: {distance} km\n"
                f"Valor: R$ {amount:.2f}\n\n"
                f"Responda *1* para *APROVAR* ou *2* para *REJEITAR*"
            )
            await wuzapi_client.send_text_message(company.admin_phone, admin_alert)

        return {"status": "ok"}

    async def handle_cancelar_despesa(self, clean_text: str, phone: str, user: User, company: Company, db: AsyncSession) -> dict:
        parts = clean_text.split()
        if len(parts) < 2:
            await wuzapi_client.send_text_message(phone, "❌ Para cancelar, informe o número da despesa. Ex: *CANCELAR 1*")
            return {"status": "ok"}
            
        target_index_str = parts[1]
        if not target_index_str.isdigit():
            await wuzapi_client.send_text_message(phone, "❌ Número inválido.")
            return {"status": "ok"}
            
        target_index = int(target_index_str) - 1
        
        # Buscar as PENDING do usuário
        query = select(Expense).where(
            Expense.user_phone == phone,
            Expense.status == ExpenseStatus.PENDING
        ).order_by(Expense.created_at.asc())
        
        res = await db.execute(query)
        expenses = res.scalars().all()
        
        if target_index < 0 or target_index >= len(expenses):
            await wuzapi_client.send_text_message(phone, f"❌ Despesa #{target_index_str} não encontrada entre as suas pendentes.")
            return {"status": "ok"}
            
        target_expense = expenses[target_index]
        target_expense.status = ExpenseStatus.CANCELLED
        try:
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error(f"DB error: {e}")
            await wuzapi_client.send_text_message(phone, "❌ Ocorreu um erro interno. Tente novamente.")
            return {"status": "error"}
        
        await wuzapi_client.send_text_message(phone, f"✅ Despesa de R$ {target_expense.amount:.2f} ({target_expense.merchant_name}) foi *CANCELADA*.")
        
        # Log Audit
        from app.services.audit_service import audit_service
        await audit_service.log_action(db, company.id, phone, "CANCEL_EXPENSE", "Expense", target_expense.id, "PENDING", "CANCELLED")
        
        return {"status": "ok"}

    async def handle_reenviar_despesa(self, clean_text: str, phone: str, user: User, company: Company, db: AsyncSession) -> dict:
        parts = clean_text.split()
        if len(parts) < 2:
            await wuzapi_client.send_text_message(phone, "❌ Para reenviar, informe o número da despesa. Ex: *REENVIAR 1*")
            return {"status": "ok"}
            
        target_index_str = parts[1]
        if not target_index_str.isdigit():
            await wuzapi_client.send_text_message(phone, "❌ Número inválido.")
            return {"status": "ok"}
            
        target_index = int(target_index_str) - 1
        
        # Buscar as REJECTED do usuário
        query = select(Expense).where(
            Expense.user_phone == phone,
            Expense.status == ExpenseStatus.REJECTED
        ).order_by(Expense.created_at.asc())
        
        res = await db.execute(query)
        expenses = res.scalars().all()
        
        if target_index < 0 or target_index >= len(expenses):
            await wuzapi_client.send_text_message(phone, f"❌ Despesa #{target_index_str} não encontrada entre as rejeitadas.")
            return {"status": "ok"}
            
        old_expense = expenses[target_index]
        
        import uuid
        # Cria uma cópia, mas como PENDING e ligada a anterior
        new_expense = Expense(
            id=str(uuid.uuid4()),
            user_phone=phone,
            company_id=user.company_id,
            merchant_name=old_expense.merchant_name,
            merchant_cnpj=old_expense.merchant_cnpj,
            amount=old_expense.amount,
            expense_date=old_expense.expense_date,
            category=old_expense.category,
            category_id=old_expense.category_id,
            status=ExpenseStatus.PENDING,
            image_s3_key=old_expense.image_s3_key,
            receipt_url=old_expense.receipt_url,
            has_receipt=old_expense.has_receipt,
            parent_expense_id=old_expense.id,
            justification=f"Reenvio da despesa rejeitada. Motivo original: {old_expense.rejection_reason}"
        )
        db.add(new_expense)
        
        # Marca a antiga como CANCELLED para sair da lista de REJECTED ativas
        old_expense.status = ExpenseStatus.CANCELLED
        try:
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error(f"DB error: {e}")
            await wuzapi_client.send_text_message(phone, "❌ Ocorreu um erro interno. Tente novamente.")
            return {"status": "error"}
        
        await wuzapi_client.send_text_message(phone, f"✅ Despesa reenviada com sucesso para aprovação!")
        
        # Log Audit
        from app.services.audit_service import audit_service
        await audit_service.log_action(db, company.id, phone, "RESUBMIT_EXPENSE", "Expense", new_expense.id, None, f"parent={old_expense.id}")
        
        return {"status": "ok"}

    async def handle_delegar(self, clean_text: str, phone: str, user: User, company: Company, db: AsyncSession) -> dict:
        parts = clean_text.split()
        if len(parts) < 3:
            await wuzapi_client.send_text_message(phone, "❌ Para delegar suas aprovações, use: *DELEGAR [telefone] [dias]*\nExemplo: *DELEGAR 5511999999999 15*")
            return {"status": "ok"}
            
        target_phone = parts[1].replace("+", "").replace("-", "").replace(" ", "")
        
        try:
            days = int(parts[2])
        except ValueError:
            await wuzapi_client.send_text_message(phone, "❌ A quantidade de dias deve ser um número inteiro.")
            return {"status": "ok"}
            
        if days <= 0 or days > 365:
            await wuzapi_client.send_text_message(phone, "❌ A quantidade de dias deve estar entre 1 e 365.")
            return {"status": "ok"}
            
        # Verifica se o delegado existe e é da mesma empresa
        query = select(User).where(User.phone == target_phone, User.company_id == user.company_id)
        res = await db.execute(query)
        delegate = res.scalar_one_or_none()
        
        if not delegate:
            await wuzapi_client.send_text_message(phone, "❌ Usuário não encontrado na sua empresa.")
            return {"status": "ok"}
            
        from datetime import datetime, timedelta, timezone
        user.delegated_to = delegate.phone
        user.delegation_expires_at = datetime.now(timezone.utc) + timedelta(days=days)
        
        try:
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error(f"DB error: {e}")
            await wuzapi_client.send_text_message(phone, "❌ Ocorreu um erro interno. Tente novamente.")
            return {"status": "error"}
        
        await wuzapi_client.send_text_message(phone, f"✅ Delegação ativada! Suas aprovações serão encaminhadas para {delegate.name or delegate.phone} pelos próximos {days} dias.")
        
        # Log Audit
        from app.services.audit_service import audit_service
        await audit_service.log_action(db, company.id, phone, "DELEGATE", "User", user.phone, None, f"to={delegate.phone}, days={days}")
        
        return {"status": "ok"}

command_handler = CommandHandler()
