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
                    f"⏰ *[ZapReembolso] Resumo Diário para Gestão*\n\n"
                    f"Olá! A empresa *{company.name}* possui *{len(pending_list)} comprovantes* pendentes de aprovação, totalizando *R$ {total_pending:.2f}*.\n\n"
                    f"👉 Responda *1* para aprovar ou *RELATORIO* para ver o detalhamento por funcionário."
                )
                await wuzapi_client.send_text_message(company.admin_phone, msg)

async def run_daily_billing_job():
    """Job diário executado pelo APScheduler para verificar vencimento de assinaturas e enviar Pix Copia e Cola aos Gestores."""
    from datetime import datetime, timezone, timedelta
    from app.services.efi_service import efi_pay_service

    async with AsyncSessionLocal() as db:
        comp_query = select(Company)
        comp_res = await db.execute(comp_query)
        companies = comp_res.scalars().all()
        now_utc = datetime.now(timezone.utc)

        for company in companies:
            if not company.admin_phone or not company.trial_ends_at:
                continue

            # Se o período de teste expirou e não está ATIVO
            if company.trial_ends_at <= now_utc and company.subscription_status != "ACTIVE":
                company.subscription_status = "EXPIRED"
                await db.commit()

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
                await wuzapi_client.send_text_message(company.admin_phone, billing_msg)
