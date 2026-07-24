import uuid
import base64
import json
import asyncio
from datetime import datetime, date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models import User, Company, Expense, ExpenseCategory, ExpenseStatus, PlanType
from app.services.ocr_service import ocr_service
from app.services.wuzapi_service import wuzapi_client
from app.services.nfce_service import nfce_service
from app.services.storage_service import storage_service
from app.services.policy_service import policy_service

class ExpenseService:
    async def process_image_receipt(self, image_base64: str, phone: str, user: User, company: Company, db: AsyncSession) -> dict:
        if company and company.plan == PlanType.FREE_TRIAL:
            count_query = select(func.count(Expense.id)).where(Expense.company_id == company.id)
            count_res = await db.execute(count_query)
            expense_count = count_res.scalar_one()
            if expense_count >= 10:
                await wuzapi_client.send_text_message(phone, "❌ **Limite do plano Free Trial atingido (10 comprovantes).**\nAssine o plano Pro para continuar enviando.")
                return {"status": "ok"}

        await wuzapi_client.send_text_message(phone, "🔍 Processando seu comprovante... Aguarde alguns segundos!")
        try:
            image_bytes = base64.b64decode(image_base64)
            
            # Tentar QR Code primeiro
            nfce_url = nfce_service.decode_qr_from_image_bytes(image_bytes)
            access_key = None
            if nfce_url:
                access_key = nfce_service.extract_access_key(nfce_url)
                # O ideal aqui seria raspar a SEFAZ usando o nfce_url, mas como fallback temporário ainda usamos o OCR.
                # Futuramente: parsed = await nfce_service.fetch_data_from_sefaz(nfce_url)
            
            # OCR Vision
            parsed = await asyncio.wait_for(ocr_service.extract_receipt_from_image_base64(image_base64), timeout=60.0)
            exp_date_obj = datetime.strptime(parsed.get("expense_date", date.today().strftime("%Y-%m-%d")), "%Y-%m-%d").date()
            
            cat_str = str(parsed.get("category", "Outros")).title()
            from app.models import Category
            cat_query = select(Category).where(
                Category.company_id == user.company_id,
                Category.name.ilike(f"%{cat_str}%")
            )
            cat_res = await db.execute(cat_query)
            category = cat_res.scalars().first()
            if not category:
                cat_query = select(Category).where(Category.company_id == user.company_id, Category.name.ilike("%Outros%"))
                category = (await db.execute(cat_query)).scalars().first()
            
            category_id = category.id if category else None
            # Mantendo category_enum provisoriamente se a coluna 'category' enum ainda for not null
            category_enum = ExpenseCategory.OUTROS

            amount = float(parsed.get("amount", 0.0))
            cnpj = parsed.get("merchant_cnpj")
            
            # Detecção de duplicidade
            is_duplicate = False
            if cnpj and amount > 0:
                dup_query = select(Expense).where(
                    Expense.company_id == user.company_id,
                    Expense.merchant_cnpj == cnpj,
                    Expense.amount == amount,
                    Expense.expense_date == exp_date_obj
                )
                dup_res = await db.execute(dup_query)
                if dup_res.scalars().first():
                    await wuzapi_client.send_text_message(
                        phone,
                        f"⚠️ *Alerta de Duplicidade!*\n\n"
                        f"Detectei que você já enviou um recibo deste estabelecimento (CNPJ: {cnpj}) com o exato valor de *R$ {amount:.2f}* para a data {exp_date_obj.strftime('%d/%m/%Y')}.\n\n"
                        f"🚫 *Esta despesa não foi salva para evitar fraude ou cobrança dupla.*\n\n"
                        f"💡 Se esta for *realmente* uma nova despesa (ex: você foi ao mesmo local 2x no mesmo dia), por favor, lance-a manualmente usando o comando:\n"
                        f"*DESPESA {amount:.2f} {parsed.get('merchant_name', 'Nome do Local')}*"
                    )
                    return {"status": "ok"}

            # Validação de Política
            is_valid, policy_reason, auto_approve_below = await policy_service.validate_expense(
                company_id=user.company_id,
                category_id=category_id,
                amount=amount,
                has_receipt=True,
                expense_date=exp_date_obj,
                db=db
            )
            
            final_status = ExpenseStatus.REJECTED
            if is_valid:
                if auto_approve_below > 0 and amount <= auto_approve_below:
                    final_status = ExpenseStatus.APPROVED
                else:
                    final_status = ExpenseStatus.PENDING
            
            # Salvar no S3
            expense_id = str(uuid.uuid4())
            file_name = f"{user.company_id}/{expense_id}.jpg"
            s3_key = await storage_service.upload_image(image_bytes, file_name)
            presigned_url = await storage_service.generate_presigned_url(s3_key)

            new_expense = Expense(
                id=expense_id,
                user_phone=phone,
                company_id=user.company_id,
                merchant_name=parsed.get("merchant_name", "Estabelecimento Comercial"),
                merchant_cnpj=cnpj,
                amount=amount,
                expense_date=exp_date_obj,
                category=category_enum,
                category_id=category_id,
                status=final_status,
                rejection_reason=policy_reason if not is_valid else None,
                image_s3_key=s3_key,
                receipt_url=presigned_url,
                ocr_confidence=parsed.get("confidence_score", 0.9),
                ocr_raw_data=json.dumps(parsed),
                nfce_access_key=access_key,
                is_duplicate_suspect=is_duplicate,
                has_receipt=True
            )
            db.add(new_expense)
            await db.commit()

            msg_duplicate = "\n⚠️ *Aviso: Parece que este comprovante já foi enviado anteriormente.*" if is_duplicate else ""
            
            status_text = f"Pendente de Aprovação do Gestor ({company.name})."
            if new_expense.status == ExpenseStatus.APPROVED:
                status_text = "✅ *Aprovada Automaticamente* (dentro da política)."
                
            confirm_msg = (
                f"✅ *Comprovante Registrado!*\n\n"
                f"🏢 *Local:* {new_expense.merchant_name}\n"
                f"💰 *Valor:* R$ {new_expense.amount:.2f}\n"
                f"📅 *Data:* {exp_date_obj.strftime('%d/%m/%Y')}\n"
                f"🏷️ *Categoria:* {category_enum.value if category_enum else (category.name if category else 'Outros')}\n\n"
                f"📋 _Status:_ {status_text}{msg_duplicate}"
            )
            await wuzapi_client.send_text_message(phone, confirm_msg)

            # Notifica o Gestor (se estiver pendente)
            if new_expense.status == ExpenseStatus.PENDING:
                # Descobrir quem é o aprovador
                approver_phone = company.admin_phone if company else None
                
                if user.department_id:
                    from app.models import UserRoleModel, Role
                    approver_query = (
                        select(UserRoleModel.user_phone)
                        .join(Role, Role.id == UserRoleModel.role_id)
                        .where(Role.name == "APROVADOR_DEPTO")
                        .where(UserRoleModel.department_id == user.department_id)
                    )
                    approver_res = await db.execute(approver_query)
                    dept_approver_phone = approver_res.scalars().first()
                    if dept_approver_phone:
                        approver_phone = dept_approver_phone
                        
                if approver_phone and approver_phone != phone:
                    receipt_url = await storage_service.generate_presigned_url(s3_key)
                    
                    # Monta detalhes ricos do funcionário
                    user_desc = user.name or phone
                    if user.job_title or user.department:
                        user_desc += f" ({user.job_title or 'Funcionário'} - {user.department or 'Geral'})"

                    caption = (
                        f"📥 Nova despesa enviada por *{user_desc}*:\n\n"
                        f"🏢 *Local:* {new_expense.merchant_name}\n"
                        f"💰 *Valor:* R$ {new_expense.amount:.2f} ({category_enum.value})\n"
                        f"📅 *Data:* {exp_date_obj.strftime('%d/%m/%Y')}\n"
                        f"{'⚠️ *Alerta: Possível Despesa Duplicada!*' if is_duplicate else ''}\n"
                        f"----------------------------------\n"
                        f"Responda este chat para decidir:\n"
                        f"✅ Responda *1* (ou *APROVAR*)\n"
                        f"❌ Responda *2* (ou *REJEITAR [motivo]*)"
                    )
                    await wuzapi_client.send_image_message(approver_phone, receipt_url, caption)
            elif new_expense.status == ExpenseStatus.REJECTED:
                # Notifica o usuário sobre a política
                await wuzapi_client.send_text_message(
                    phone,
                    f"❌ Sua despesa foi **REJEITADA AUTOMATICAMENTE** pelas políticas da empresa.\nMotivo: {policy_reason}"
                )

        except asyncio.TimeoutError:
            print("[Process Error] Timeout ao tentar ler o recibo.")
            await wuzapi_client.send_text_message(
                phone, 
                "⏳ O tempo de processamento esgotou. O serviço está congestionado, por favor tente enviar novamente em alguns minutos."
            )
        except Exception as e:
            print(f"[Process Error] Erro ao processar recibo: {e}")
            await wuzapi_client.send_text_message(
                phone, 
                "❌ Não consegui ler os dados dessa imagem. Certifique-se de que a foto da nota fiscal está nítida e bem iluminada."
            )
        return {"status": "ok"}

expense_service = ExpenseService()
