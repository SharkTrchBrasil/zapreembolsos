from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import Company, ExpenseCategory, PolicyRule
import logging

logger = logging.getLogger("policy_service")

class PolicyService:
    async def validate_expense(self, company_id: str, category_id: str, amount: float, has_receipt: bool, expense_date: str, db: AsyncSession) -> tuple[bool, str, float]:
        """
        Valida a despesa contra as regras de política da empresa e janela de tempo.
        Retorna (is_valid, reason, auto_approve_below)
        """
        if amount <= 0: return False, "Valor da despesa deve ser positivo.", 0.0
        if amount > 999_999: return False, "Valor da despesa excede o limite razoável.", 0.0
        
        # 1. Validar Janela de Tempo (submission_window_days)
        comp_query = select(Company).where(Company.id == company_id)
        comp_res = await db.execute(comp_query)
        company = comp_res.scalar_one_or_none()
        
        if company and company.submission_window_days:
            from datetime import datetime
            try:
                if isinstance(expense_date, str):
                    exp_date_obj = datetime.strptime(expense_date, "%Y-%m-%d").date()
                else:
                    exp_date_obj = expense_date # assumed date object
                    
                days_diff = (datetime.now().date() - exp_date_obj).days
                if days_diff > company.submission_window_days:
                    return False, f"A despesa (com {days_diff} dias) excede o limite de tempo permitido para envio, que é de no máximo {company.submission_window_days} dias após a compra.", 0.0
            except (ValueError, TypeError) as e:
                logger.warning(f"Erro ao parsear data da despesa: {e}")
        query = select(PolicyRule).where(
            PolicyRule.company_id == company_id,
            PolicyRule.category_id == category_id,
            PolicyRule.is_active == True
        )
        res = await db.execute(query)
        rule = res.scalar_one_or_none()

        if not rule:
            # Sem regra específica para a categoria, aprova por padrão se tiver limite global?
            # Ou fallback para regra sem categoria (global)
            global_query = select(PolicyRule).where(
                PolicyRule.company_id == company_id,
                PolicyRule.category_id == None,
                PolicyRule.is_active == True
            )
            g_res = await db.execute(global_query)
            rule = g_res.scalar_one_or_none()

        auto_approve_below = 0.0

        if rule:
            if amount > float(rule.max_amount):
                return False, f"Valor da despesa (R$ {amount:.2f}) excede o limite permitido (R$ {rule.max_amount:.2f}) para esta categoria.", 0.0
            
            if rule.requires_receipt and not has_receipt:
                return False, "Comprovante obrigatório para este tipo de despesa não anexado.", 0.0
                
            if rule.auto_approve_below:
                auto_approve_below = float(rule.auto_approve_below)

        return True, "", auto_approve_below

policy_service = PolicyService()
