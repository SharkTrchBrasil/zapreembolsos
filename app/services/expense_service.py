import uuid
import base64
import json
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
            parsed = await ocr_service.extract_receipt_from_image_base64(image_base64)
            exp_date_obj = datetime.strptime(parsed.get("expense_date", date.today().strftime("%Y-%m-%d")), "%Y-%m-%d").date()
            
            cat_str = str(parsed.get("category", "OUTROS")).upper()
            try:
                category_enum = ExpenseCategory[cat_str]
            except KeyError:
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
                    is_duplicate = True

            # Validação de Política
            is_valid, policy_reason = await policy_service.validate_expense(
                company_id=user.company_id,
                category=category_enum,
                amount=amount,
                has_receipt=True,
                db=db
            )
            
            # Salvar no S3
            expense_id = str(uuid.uuid4())
            file_name = f"{user.company_id}/{expense_id}.jpg"
            s3_key = storage_service.upload_image(image_bytes, file_name)

            new_expense = Expense(
                id=expense_id,
                user_phone=phone,
                company_id=user.company_id,
                merchant_name=parsed.get("merchant_name", "Estabelecimento Comercial"),
                merchant_cnpj=cnpj,
                amount=amount,
                expense_date=exp_date_obj,
                category=category_enum,
                status=ExpenseStatus.PENDING if is_valid else ExpenseStatus.REJECTED,
                rejection_reason=policy_reason if not is_valid else None,
                image_s3_key=s3_key,
                ocr_confidence=parsed.get("confidence_score", 0.9), # Fake score if not returned
                ocr_raw_data=json.dumps(parsed),
                nfce_access_key=access_key,
                is_duplicate_suspect=is_duplicate,
                has_receipt=True
            )
            db.add(new_expense)
            await db.commit()

            msg_duplicate = "\n⚠️ *Aviso: Parece que este comprovante já foi enviado anteriormente.*" if is_duplicate else ""
            confirm_msg = (
                f"✅ *Comprovante Registrado!*\n\n"
                f"🏢 *Local:* {new_expense.merchant_name}\n"
                f"💰 *Valor:* R$ {new_expense.amount:.2f}\n"
                f"📅 *Data:* {exp_date_obj.strftime('%d/%m/%Y')}\n"
                f"🏷️ *Categoria:* {category_enum.value}\n\n"
                f"📋 _Status:_ Pendente de Aprovação do Gestor ({company.name}).{msg_duplicate}"
            )
            await wuzapi_client.send_text_message(phone, confirm_msg)

            # Notifica o Gestor (se estiver pendente)
            if new_expense.status == ExpenseStatus.PENDING and company and company.admin_phone and company.admin_phone != phone:
                receipt_url = storage_service.generate_presigned_url(s3_key)
                
                # Monta detalhes ricos do funcionário
                user_desc = user.name or phone
                if user.job_title or user.department:
                    user_desc += f" ({user.job_title or 'Funcionário'} - {user.department or 'Geral'})"

                caption = (
                    f"📥 *[Aviso Gestor ZapReembolso - {company.name}]*\n"
                    f"Nova despesa enviada por *{user_desc}*:\n\n"
                    f"🏢 *Local:* {new_expense.merchant_name}\n"
                    f"💰 *Valor:* R$ {new_expense.amount:.2f} ({category_enum.value})\n"
                    f"📅 *Data:* {exp_date_obj.strftime('%d/%m/%Y')}\n"
                    f"{'⚠️ *Alerta: Possível Despesa Duplicada!*' if is_duplicate else ''}\n"
                    f"----------------------------------\n"
                    f"Responda este chat para decidir:\n"
                    f"✅ *APROVAR {new_expense.id[:4]}* (ou apenas *1*)\n"
                    f"❌ *REJEITAR {new_expense.id[:4]} [motivo]* (ou apenas *2*)"
                )
                await wuzapi_client.send_image_message(company.admin_phone, receipt_url, caption)
            elif new_expense.status == ExpenseStatus.REJECTED:
                # Notifica o usuário sobre a política
                await wuzapi_client.send_text_message(
                    phone,
                    f"❌ Sua despesa foi **REJEITADA AUTOMATICAMENTE** pelas políticas da empresa.\nMotivo: {policy_reason}"
                )

        except Exception as e:
            print(f"[Process Error] Erro ao processar recibo: {e}")
            await wuzapi_client.send_text_message(
                phone, 
                "❌ Não consegui ler os dados dessa imagem. Certifique-se de que a foto da nota fiscal está nítida e bem iluminada."
            )
        return {"status": "ok"}

expense_service = ExpenseService()
