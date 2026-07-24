from sqlalchemy.ext.asyncio import AsyncSession
from app.models import AuditLog
import uuid
import logging

logger = logging.getLogger("audit_service")

class AuditService:
    @staticmethod
    async def log_action(
        db: AsyncSession,
        company_id: str,
        user_phone: str,
        action: str,
        entity_type: str,
        entity_id: str,
        old_value: str = None,
        new_value: str = None,
        ip_address: str = None
    ):
        """Registra uma ação crítica no log de auditoria imutável."""
        try:
            log_entry = AuditLog(
                id=str(uuid.uuid4()),
                company_id=company_id,
                user_phone=user_phone,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                old_value=old_value,
                new_value=new_value,
                ip_address=ip_address
            )
            db.add(log_entry)
            await db.commit()
        except Exception as e:
            logger.error(f"Falha ao registrar log de auditoria: {e}")
            await db.rollback()
            try:
                with open("audit_fallback.log", "a") as f:
                    f.write(f"Fallback Log - Action: {action}, Entity: {entity_type} {entity_id}, User: {user_phone}, Error: {e}\n")
            except Exception as fallback_e:
                logger.error(f"Falha ao escrever no log de fallback: {fallback_e}")

audit_service = AuditService()
