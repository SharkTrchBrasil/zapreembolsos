import uuid
import random
import string
from datetime import datetime, date
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import User, Company, Expense, UserRole, ExpenseCategory, ExpenseStatus, PlanType
from app.services.wuzapi_service import wuzapi_client
from app.services.ocr_service import ocr_service

router = APIRouter(prefix="/webhook", tags=["Webhook"])

def generate_company_code(name: str) -> str:
    """Gera um código único curto como #ALFA1 ou #POSTO7."""
    clean_name = "".join(c for c in name if c.isalnum()).upper()[:4]
    random_num = random.randint(10, 99)
    return f"{clean_name}{random_num}"

@router.post("/wuzapi")
async def handle_wuzapi_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Recebe mensagens do WuzAPI e orquestra o onboarding e gestão de comprovantes."""
    data = await request.json()

    phone = data.get("Phone") or data.get("from")
    text = data.get("Body") or data.get("text", "")
    image_base64 = data.get("ImageBase64") or data.get("media_base64")

    if not phone:
        return {"status": "ignored", "reason": "No phone number"}

    phone = phone.replace("@s.whatsapp.net", "").replace("+", "").strip()
    clean_text = text.strip() if text else ""

    # 1. Busca ou cria o registro inicial do Usuário
    user_query = select(User).where(User.phone == phone)
    res = await db.execute(user_query)
    user = res.scalar_one_or_none()

    if not user:
        user = User(phone=phone, name="Novo Usuário", role=UserRole.EMPLOYEE)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    # 2. Comando: CRIAR [Nome da Empresa] (Para Gestores)
    if clean_text.upper().startswith("CRIAR"):
        company_name = clean_text[5:].strip()
        if not company_name:
            await wuzapi_client.send_text_message(phone, "❌ Por favor, informe o nome da sua empresa. Exemplo: *CRIAR Construtora Alfa*")
            return {"status": "ok"}

        code = generate_company_code(company_name)
        new_company = Company(
            id=str(uuid.uuid4()),
            code=code,
            name=company_name,
            admin_phone=phone,
            plan=PlanType.FREE_TRIAL
        )
        db.add(new_company)
        await db.commit()

        user.company_id = new_company.id
        user.role = UserRole.ADMIN
        user.name = f"Gestor ({company_name})"
        await db.commit()

        welcome_admin = (
            f"🎉 **Empresa {company_name} Criada com Sucesso!**\n\n"
            f"🏢 **Código da Sua Empresa:** `#{code}`\n\n"
            f"📢 **Passo para seus funcionários:**\n"
            f"Envie este contato para seus funcionários e peça para eles mandarem `#{code}` no primeiro acesso para se vincularem!\n\n"
            f"💡 **Seus Comandos:**\n"
            f"• Envie *RELATORIO* para ver gastos do mês.\n"
            f"• Envie *APROVAR* para dar baixa em reembolso."
        )
        await wuzapi_client.send_text_message(phone, welcome_admin)
        return {"status": "ok"}

    # 3. Comando: Vincular via Código (ex: #ALFA123 ou #ALFA)
    if clean_text.startswith("#") or clean_text.upper().startswith("ENTRAR"):
        raw_code = clean_text.replace("#", "").replace("ENTRAR", "").strip().upper()
        comp_query = select(Company).where(Company.code == raw_code)
        comp_res = await db.execute(comp_query)
        target_company = comp_res.scalar_one_or_none()

        if target_company:
            user.company_id = target_company.id
            user.role = UserRole.EMPLOYEE
            await db.commit()

            link_msg = (
                f"✅ **Conta Vinculada à empresa {target_company.name}!**\n\n"
                f"A partir de agora, qualquer foto de **cupom fiscal ou recibo** que você enviar aqui será registrada automaticamente para o reembolso do seu gestor."
            )
            await wuzapi_client.send_text_message(phone, link_msg)
        else:
            await wuzapi_client.send_text_message(phone, f"❌ Código `#{raw_code}` não encontrado. Verifique com seu gestor o código correto da empresa.")
        return {"status": "ok"}

    # 4. Verifica se o usuário já possui empresa vinculada
    if not user.company_id:
        unlinked_msg = (
            "👋 **Bem-vindo ao ZapReembolso!**\n\n"
            "Não encontrei nenhuma empresa vinculada ao seu número.\n\n"
            "👉 **Se você é Funcionário:**\n"
            "Digite o Código da sua empresa (ex: `#ALFA12`) fornecido pelo seu gestor.\n\n"
            "👉 **Se você é Gestor/Dono de Empresa:**\n"
            "Digite *CRIAR Nome da Sua Empresa* para cadastrar sua empresa agora!"
        )
        await wuzapi_client.send_text_message(phone, unlinked_msg)
        return {"status": "ok"}

    # Busca os dados da empresa cadastrada
    comp_query = select(Company).where(Company.id == user.company_id)
    comp_res = await db.execute(comp_query)
    company = comp_res.scalar_one_or_none()

    # 5. Comando "RELATORIO"
    if "RELATORIO" in clean_text.upper():
        if not company:
            await wuzapi_client.send_text_message(phone, "❌ Empresa não encontrada.")
            return {"status": "ok"}

        exp_query = select(Expense).where(Expense.company_id == company.id)
        exp_res = await db.execute(exp_query)
        all_expenses = exp_res.scalars().all()

        total_amount = sum(e.amount for e in all_expenses)
        pending_expenses = [e for e in all_expenses if e.status == ExpenseStatus.PENDING]
        approved_expenses = [e for e in all_expenses if e.status in (ExpenseStatus.APPROVED, ExpenseStatus.REIMBURSED)]

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

    # 6. Comando "APROVAR"
    if clean_text.upper().startswith("APROVAR"):
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

    # 7. Processamento de Imagem (Cupom Fiscal / Recibo)
    if image_base64:
        await wuzapi_client.send_text_message(phone, "🔍 Lendo os dados do seu recibo com IA... Aguarde alguns segundos!")
        try:
            parsed = await ocr_service.extract_receipt_from_image_base64(image_base64)
            exp_date_obj = datetime.strptime(parsed.get("expense_date", date.today().strftime("%Y-%m-%d")), "%Y-%m-%d").date()
            
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
                f"📋 *Status:* Pendente de Aprovação do Gestor ({company.name})."
            )
            await wuzapi_client.send_text_message(phone, confirm_msg)

            # Notifica o Gestor
            if company and company.admin_phone and company.admin_phone != phone:
                admin_alert = (
                    f"📥 **[Aviso Gestor ZapReembolso - {company.name}]**\n"
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
