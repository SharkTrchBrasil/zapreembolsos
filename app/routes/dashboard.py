from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Dict, Any
from datetime import date
from app.database import get_db
from app.models import User, Company, Expense, ExpenseStatus, UserRole
from app.security import get_current_admin
import logging

logger = logging.getLogger("dashboard")
router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

@router.get("/stats")
async def get_dashboard_stats(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Retorna os KPIs para o topo do Dashboard."""
    company_id = admin.company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="Administrador não vinculado a uma empresa")

    today = date.today()
    start_of_month = today.replace(day=1)
    
    # Busca todas as despesas do mês atual
    exp_query = select(Expense).where(
        Expense.company_id == company_id,
        Expense.expense_date >= start_of_month
    )
    exp_res = await db.execute(exp_query)
    all_expenses = exp_res.scalars().all()
    
    total_spent = sum(e.amount for e in all_expenses if e.status in (ExpenseStatus.APPROVED, ExpenseStatus.REIMBURSED))
    pending_count = len([e for e in all_expenses if e.status == ExpenseStatus.PENDING])
    pending_amount = sum(e.amount for e in all_expenses if e.status == ExpenseStatus.PENDING)
    
    # Qtd Funcionários Ativos
    user_query = select(func.count(User.phone)).where(
        User.company_id == company_id,
        User.is_approved == True,
        User.role == UserRole.EMPLOYEE
    )
    user_res = await db.execute(user_query)
    employee_count = user_res.scalar_one_or_none() or 0

    return {
        "total_spent_month": total_spent,
        "pending_expenses_count": pending_count,
        "pending_expenses_amount": pending_amount,
        "active_employees": employee_count
    }

@router.get("/expenses")
async def get_dashboard_expenses(
    status: str = None,
    limit: int = 50,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Retorna a lista de despesas reais do banco de dados."""
    company_id = admin.company_id
    query = select(Expense, User.name.label("employee_name")).join(User, Expense.user_phone == User.phone).where(Expense.company_id == company_id)
    
    if status:
        try:
            status_enum = ExpenseStatus[status.upper()]
            query = query.where(Expense.status == status_enum)
        except KeyError:
            pass
            
    query = query.order_by(Expense.created_at.desc()).limit(limit)
    res = await db.execute(query)
    rows = res.all()
    
    expenses_list = []
    for row in rows:
        exp = row[0]
        emp_name = row[1] or exp.user_phone
        cat_name = exp.category.value if hasattr(exp.category, 'value') else str(exp.category)
        status_name = exp.status.value if hasattr(exp.status, 'value') else str(exp.status)
        
        expenses_list.append({
            "id": exp.id,
            "short_id": exp.id[:8],
            "amount": float(exp.amount),
            "date": exp.expense_date.strftime("%Y-%m-%d"),
            "category": cat_name,
            "merchant_name": exp.merchant_name or "Não informado",
            "employee_name": emp_name,
            "status": status_name,
            "receipt_url": exp.receipt_url
        })
        
    return expenses_list

@router.get("/chart")
async def get_dashboard_chart(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Dados para alimentar os gráficos (Despesas por categoria)."""
    company_id = admin.company_id
    today = date.today()
    start_of_month = today.replace(day=1)
    
    exp_query = select(Expense).where(
        Expense.company_id == company_id,
        Expense.expense_date >= start_of_month,
        Expense.status.in_([ExpenseStatus.APPROVED, ExpenseStatus.REIMBURSED])
    )
    exp_res = await db.execute(exp_query)
    all_expenses = exp_res.scalars().all()
    
    categories = {}
    for e in all_expenses:
        cat_name = e.category.value if hasattr(e.category, 'value') else str(e.category)
        categories[cat_name] = categories.get(cat_name, 0) + float(e.amount)
        
    return {
        "labels": list(categories.keys()),
        "data": list(categories.values())
    }
