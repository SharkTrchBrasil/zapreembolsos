import asyncio
import logging
from sqlalchemy import text
from app.database import engine, Base, init_db
from seed_permissions import seed_permissions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reset_db")

async def reset_database():
    logger.info("🗑️ Limpando todo o banco de dados...")
    
    async with engine.begin() as conn:
        # TRUNCATE / DROP todas as tabelas
        try:
            # PostgreSQL TRUNCATE CASCADE
            await conn.execute(text("TRUNCATE TABLE users, companies, expenses, policy_rules, monthly_closes, departments, categories, audit_logs, permissions, roles, role_permissions, user_roles, attachments, approval_steps, notification_logs RESTART IDENTITY CASCADE;"))
            logger.info("✅ Tabelas truncadas com sucesso via TRUNCATE CASCADE!")
        except Exception as e:
            logger.warning(f"Aviso ao truncar (tentando drop_all): {e}")
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
            logger.info("✅ Tabelas recriadas via drop_all/create_all!")

    # Re-inicializa schemas e novas colunas
    await init_db()

    # Re-popula permissões padrão
    await seed_permissions()

    await engine.dispose()
    logger.info("🎉 Banco de dados 100% limpo e pronto para novos cadastros do ZERO!")

if __name__ == "__main__":
    asyncio.run(reset_database())
