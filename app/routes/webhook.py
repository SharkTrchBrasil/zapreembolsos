import uuid
from datetime import datetime, date
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.models import User, Company, Expense, UserRole, ExpenseCategory, ExpenseStatus, PlanType
from app.services.wuzapi_service import wuzapi_client
from app.services.ocr_service import ocr_service

router = APIRouter(prefix="/webhook", tags=["Webhook"])

@router.post("/wuzapi")
async def handle_wuzapi_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Recebe mensagens do WuzAPI e processa comprovantes de reembolso e comandos."""
    data = await request.json()

    phone = data.get("Phone") or data.get("from")
    text = data.get("Body") or data.get("text", "")
    image_base64 = data.get("ImageBase64") or data.get("media_base64")

    if not phone:
        return {"status": "ignored", "reason": "No phone number"}

    phone = phone.replace("@s.whatsapp.net", "").replace("+", "").strip()

    # 1. Busca ou cria o Usuário e a Empresa padrão de demonstração
    user_query = select(User).where(User.phone == phone)
    res = await db.execute(user_query)
    user = res.scalar_one_or_none()

    if not user:
        # Cria uma Empresa de Teste para o novo onboarding
        company_id = str(uuid.uuid4())
        new_company = Company(
            id=company_id,
            name="Sua Empresa (Defina com EMPRESA NOME)",
            admin_phone=phone,
            plan=PlanType.FREE_TRIAL
        )
        db.add(new_company)

        user = User(
            phone=phone,
            name="Funcionário / Gestor",
            company_id=company_id,
            role=UserRole.ADMIN
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        welcome_msg = (
            "👋 **Bem-vindo ao ZapReembolso!**\n\n"
            "Eu sou seu assistente de reembolsos e gestão de comprovantes da empresa.\n\n"
            "📸 **Como usar:** Envie a foto de qualquer **cupom fiscal ou recibo** (Combustível, Almoço, Hospedagem) e a IA lerá os dados e registrará o reembolso instantaneamente!\n\n"
            "💡 **Comandos úteis:**\n"
            "• Envie *RELATORIO* para ver o resumo do mês.\n"
            "• Envie *APROVAR* para dar baixa nas despesas pendentes."
        )
        await wuzapi_client.send_text_message(phone, welcome_msg)

    # Garante que temos a empresa do usuário
    comp_query = select(Company).where(Company.id == user.company_id)
    comp_res = await db.execute(comp_query)
    company = comp_res.scalar_one_or_none()

    # 2. Comando "RELATORIO"
    if text and "RELATORIO" in text.strip().upper():
        if not company:
            await wuzapi_client.send_text_message(phone, "❌ Empresa não cadastrada.")
            return {"status": "ok"}

        exp_query = select(Expense).where(Expense.company_id == company.id)
        exp_res = await db.execute(exp_query)
        all_expenses = exp_res.scalars().all()

        total_amount = sum(e.amount for e in all_expenses)
        pending_expenses = [e for e in all_expenses if e.status == ExpenseStatus.PENDING]
        approved_expenses = [e for e in all_expenses if e.status in (ExpenseStatus.APPROVED, ExpenseStatus.REIMBURSED)]

        # Agrupa por Categoria
        by_category = {}
        for e in all_expenses:
            cat_name = e.category.value if hasattr(e.category, 'value') else str(e.category)
            by_category[cat_name] = by_category.get(cat_name, 0.0) + e.amount

        cat_summary = "\n".join([f"• **{cat}:** R$ {amt:.2f}" for cat, amt in by_category.items()]) or "Nenhuma despesa"

        report_msg = (
            f"📊 **Resumo de Despesas - {company.name}**\n\n"
            f"💰 **Total Acumulado:** R$ {total_amount:.2f} ({len(all_expenses)} comprovantes)\n"
            f"✅ **Aprovadas:** R$ {sum(e.amount for e in approved_expenses):.2f}\n"
            f"⏳ **Pendentes de Aprovação:** {len(pending_expenses)} (R$ {sum(e.amount for e in pending_expenses):.2f})\n\n"
            f"🏷️ **Por Categoria:**\n{cat_summary}\n\n"
            f"💡 Responda *APROVAR* para aprovar as pendentes."
        )
        await wuzapi_client.send_text_message(phone, report_msg)
        return {"status": "ok"}

    # 3. Comando "APROVAR"
    if text and text.strip().upper().startswith("APROVAR"):
        exp_query = select(Expense).where(
            Expense.company_id == user.company_id,
            Expense.status == ExpenseStatus.PENDING
        )
        exp_res = await db.execute(exp_query)
        pending_list = exp_res.scalars().all()

        if not pending_list:
            await wuzapi_client.send_text_message(phone, "🎉 Nenhuma despesa pendente de aprovação no momento!")
            return {"status": "ok"}

        for exp in pending_list:
            exp.status = ExpenseStatus.APPROVED
        
        await db.commit()
        await wuzapi_client.send_text_message(
            phone,
            f"✅ **{len(pending_list)} despesas aprovadas com sucesso!** Relatório atualizado."
        )
        return {"status": "ok"}

    # 4. Leitura de Imagem / Recibo / Cupom Fiscal
    if image_base64:
        await wuzapi_client.send_text_message(phone, "🔍 Lendo os dados do seu recibo com IA... Aguarde alguns segundos!")
        try:
            parsed = await ocr_service.extract_receipt_from_image_base64(image_base64)
            exp_date_obj = datetime.strptime(parsed.get("expense_date", date.today().strftime("%Y-%m-%d")), "%Y-%m-%d").date()
            
            # Valida/Mapeia categoria
            cat_str = str(parsed.get("category", "OUTROS")).upper()
            try:
                category_enum = ExpenseCategory[cat_str]
            except KeyError:
                category_enum = ExpenseCategory.OUTROS

            new_expense = Expense(
                id=str(uuid.uuid4()),
                user_phone=phone,
                company_id=user.company_id,
                merchant_name=parsed.get("merchant_name", "Estabelecimento Comercial"),
                merchant_cnpj=parsed.get("merchant_cnpj"),
                amount=float(parsed.get("amount", 0.0)),
                expense_date=exp_date_obj,
                category=category_enum,
                status=ExpenseStatus.PENDING
            )
            db.add(new_expense)
            await db.commit()

            confirm_msg = (
                f"✅ **Comprovante Registrado!**\n\n"
                f"🏢 **Local:** {new_expense.merchant_name}\n"
                f"💰 **Valor:** R$ {new_expense.amount:.2f}\n"
                f"📅 **Data:** {exp_date_obj.strftime('%d/%m/%Y')}\n"
                f"🏷️ **Categoria:** {category_enum.value}\n\n"
                f"📋 *Status:* Pendente de Aprovação do Gestor."
            )
            await wuzapi_client.send_text_message(phone, confirm_msg)

            # Notifica o Gestor (se for uma pessoa diferente do funcionário)
            if company and company.admin_phone and company.admin_phone != phone:
                admin_alert = (
                    f"📥 **[Aviso Gestor ZapReembolso]**\n"
                    f"Nova despesa enviada por **{user.name or phone}**:\n\n"
                    f"🏢 **Local:** {new_expense.merchant_name}\n"
                    f"💰 **Valor:** R$ {new_expense.amount:.2f} ({category_enum.value})\n\n"
                    f"Responda *APROVAR* para autorizar o reembolso."
                )
                await wuzapi_client.send_text_message(company.admin_phone, admin_alert)

        except Exception as e:
            print(f"[OCR Error] Erro ao processar recibo: {e}")
            await wuzapi_client.send_text_message(
                phone, 
                "❌ Não consegui ler os dados dessa imagem. Certifique-se de que a foto da nota fiscal está nítida e bem iluminada."
            )

    return {"status": "ok"}
