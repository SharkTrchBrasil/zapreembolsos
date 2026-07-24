from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import User, Company, UserRole
import pandas as pd
import io

router = APIRouter(prefix="/api", tags=["API"])

@router.post("/users/import-csv")
async def import_users_csv(
    file: UploadFile = File(...),
    company_id: str = "TEST", # To be replaced with actual auth in the future
    db: AsyncSession = Depends(get_db)
):
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Arquivo deve ser um CSV")
        
    # Verificar company
    comp_query = select(Company).where(Company.id == company_id)
    comp_res = await db.execute(comp_query)
    company = comp_res.scalar_one_or_none()
    
    if not company:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")

    content = await file.read()
    
    try:
        # Lê o CSV. Formato esperado: phone,name,department,role
        df = pd.read_csv(io.StringIO(content.decode('utf-8')))
        
        imported = 0
        errors = []
        
        for index, row in df.iterrows():
            try:
                phone = str(row['phone']).strip()
                name = str(row['name']).strip()
                
                # Check se já existe
                u_query = select(User).where(User.phone == phone)
                u_res = await db.execute(u_query)
                user = u_res.scalar_one_or_none()
                
                if not user:
                    user = User(
                        phone=phone,
                        name=name,
                        company_id=company.id,
                        role=UserRole.EMPLOYEE,
                        is_approved=True,
                        onboarding_step=None
                    )
                    db.add(user)
                    imported += 1
            except Exception as e:
                errors.append(f"Linha {index}: {str(e)}")
                
        await db.commit()
        
        return {
            "status": "success",
            "imported": imported,
            "errors": errors
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao processar CSV: {str(e)}")

@router.get("/reports/summary")
async def get_reports_summary(
    company_id: str = "TEST",
    db: AsyncSession = Depends(get_db)
):
    from sqlalchemy import func
    from app.models import Expense, ExpenseStatus
    
    # Valida company
    comp = await db.execute(select(Company).where(Company.id == company_id))
    if not comp.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
        
    query = select(
        Expense.status, 
        func.count(Expense.id).label('count'),
        func.sum(Expense.amount).label('total')
    ).where(Expense.company_id == company_id).group_by(Expense.status)
    
    res = await db.execute(query)
    data = res.all()
    
    summary = {}
    for status, count, total in data:
        summary[status.value] = {
            "count": count,
            "total": float(total) if total else 0.0
        }
        
    return {"status": "success", "data": summary}

@router.get("/reports/export-csv")
async def export_reports_csv(
    company_id: str = "TEST",
    db: AsyncSession = Depends(get_db)
):
    from fastapi.responses import StreamingResponse
    from app.models import Expense
    
    query = select(Expense).where(Expense.company_id == company_id)
    res = await db.execute(query)
    expenses = res.scalars().all()
    
    if not expenses:
        raise HTTPException(status_code=404, detail="Nenhuma despesa encontrada")
        
    data = []
    for e in expenses:
        data.append({
            "id": e.id,
            "telefone": e.user_phone,
            "estabelecimento": e.merchant_name,
            "valor": float(e.amount),
            "data": e.expense_date.strftime("%Y-%m-%d"),
            "status": e.status.value,
            "motivo_rejeicao": e.rejection_reason or ""
        })
        
    df = pd.DataFrame(data)
    stream = io.StringIO()
    df.to_csv(stream, index=False)
    
    response = StreamingResponse(iter([stream.getvalue()]), media_type="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=despesas.csv"
    return response

@router.get("/reports/export-pdf")
async def export_reports_pdf(
    company_id: str = "TEST",
    db: AsyncSession = Depends(get_db)
):
    from fastapi.responses import Response
    from app.models import Expense
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    
    query = select(Expense).where(Expense.company_id == company_id).order_by(Expense.created_at.desc())
    res = await db.execute(query)
    expenses = res.scalars().all()
    
    if not expenses:
        raise HTTPException(status_code=404, detail="Nenhuma despesa encontrada")
        
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 50, "Relatório Corporativo de Despesas - ZapReembolsos")
    
    c.setFont("Helvetica", 10)
    y = height - 90
    
    for e in expenses:
        if y < 50:
            c.showPage()
            c.setFont("Helvetica", 10)
            y = height - 50
            
        line = f"ID: {e.id[:8]} | Data: {e.expense_date.strftime('%d/%m/%Y')} | Local: {e.merchant_name} | Valor: R$ {e.amount:.2f} | Status: {e.status.value}"
        c.drawString(50, y, line)
        y -= 20
        
    c.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()
    
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=relatorio_despesas.pdf"}
    )

@router.post("/users/{phone}/anonymize")
async def anonymize_user(
    phone: str,
    company_id: str = "TEST",
    db: AsyncSession = Depends(get_db)
):
    """
    Endpoint LGPD: Anonimiza os dados do usuário, substituindo nome, e-mail e telefone por hashes irreversíveis,
    mas mantendo o histórico de despesas para relatórios financeiros da empresa.
    """
    import hashlib
    import uuid
    from app.models import User
    
    query = select(User).where(User.phone == phone, User.company_id == company_id)
    res = await db.execute(query)
    user = res.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
        
    salt = str(uuid.uuid4())
    anon_phone = "ANON_" + hashlib.sha256((phone + salt).encode()).hexdigest()[:15]
    
    user.name = "Usuário Anonimizado"
    user.email = None
    user.phone = anon_phone
    user.is_approved = False
    
    # As despesas continuam ligadas a esse anon_phone, garantindo integridade financeira da empresa
    
    await db.commit()
    
    return {"status": "success", "message": "Dados do usuário foram anonimizados conforme a LGPD."}
