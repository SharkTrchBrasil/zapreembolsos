from datetime import date
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import Company, Expense, ExpenseStatus
from app.services.wuzapi_service import wuzapi_client

async def run_daily_reminder_job():
    """Job diário executado pelo APScheduler às 08:00 AM enviando resumo de despesas pendentes para os Gestores."""
    async with AsyncSessionLocal() as db:
        comp_query = select(Company)
        comp_res = await db.execute(comp_query)
        companies = comp_res.scalars().all()

        for company in companies:
            if not company.admin_phone:
                continue

            exp_query = select(Expense).where(
                Expense.company_id == company.id,
                Expense.status == ExpenseStatus.PENDING
            )
            exp_res = await db.execute(exp_query)
            pending_list = exp_res.scalars().all()

            if pending_list:
                total_pending = sum(e.amount for e in pending_list)
                msg = (
                    f"⏰ **[ZapReembolso] Resumo Diário para Gestão**\n\n"
                    f"Olá! A empresa **{company.name}** possui **{len(pending_list)} comprovantes** pendentes de aprovação, totalizando **R$ {total_pending:.2f}**.\n\n"
                    f"👉 Responda *APROVAR* para dar baixa em todas as despesas ou *RELATORIO* para ver o detalhamento por funcionário."
                )
                await wuzapi_client.send_text_message(company.admin_phone, msg)
