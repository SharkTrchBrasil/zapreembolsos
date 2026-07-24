import logging
import asyncio
from datetime import date
from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app.models import Company, Expense, ExpenseStatus
from app.services.wuzapi_service import wuzapi_client

logger = logging.getLogger(__name__)

async def run_daily_reminder_job():
    """Job diário executado pelo APScheduler às 08:00 AM enviando resumo de despesas pendentes para os Gestores."""
    async with AsyncSessionLocal() as db:
        query = (
            select(Company, func.count(Expense.id).label("count"), func.sum(Expense.amount).label("total"))
            .join(Expense, Company.id == Expense.company_id)
            .where(Expense.status == ExpenseStatus.PENDING)
            .group_by(Company.id)
        )
        res = await db.execute(query)
        results = res.all()

        for company, count, total in results:
            if not company.admin_phone:
                continue

            try:
                msg = (
                    f"⏰ *[ZapReembolso] Resumo Diário para Gestão*\n\n"
                    f"Olá! A empresa *{company.name}* possui *{count} comprovantes* pendentes de aprovação, totalizando *R$ {total:.2f}*.\n\n"
                    f"👉 Responda *1* para aprovar ou *RELATORIO* para ver o detalhamento por funcionário."
                )
                await wuzapi_client.send_text_message(company.admin_phone, msg)
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Erro ao enviar lembrete diário para a empresa {company.id}: {e}")

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

            try:
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
                    await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Erro ao enviar cobrança diária para a empresa {company.id}: {e}")
