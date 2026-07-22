from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import Company, ExpenseCategory, PolicyRule

class PolicyService:
    async def validate_expense(self, company_id: str, category: ExpenseCategory, amount: float, has_receipt: bool, db: AsyncSession) -> tuple[bool, str]:
        """
        Valida a despesa contra as regras de política da empresa.
        Retorna (is_valid, reason)
        """
        query = select(PolicyRule).where(
            PolicyRule.company_id == company_id,
            PolicyRule.category == category,
            PolicyRule.is_active == True
        )
        res = await db.execute(query)
        rule = res.scalar_one_or_none()

        if not rule:
            # Sem regra específica para a categoria, aprova por padrão se tiver limite global?
            # Ou fallback para regra sem categoria (global)
            global_query = select(PolicyRule).where(
                PolicyRule.company_id == company_id,
                PolicyRule.category == None,
                PolicyRule.is_active == True
            )
            g_res = await db.execute(global_query)
            rule = g_res.scalar_one_or_none()

        if rule:
            if amount > float(rule.max_amount):
                return False, f"Valor da despesa (R$ {amount:.2f}) excede o limite permitido (R$ {rule.max_amount:.2f}) para esta categoria."
            
            if rule.requires_receipt and not has_receipt:
                return False, "Comprovante obrigatório para este tipo de despesa não anexado."

        return True, ""

policy_service = PolicyService()
