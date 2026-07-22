import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.models import Base
from app.config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    logger.info(f"🔄 Conectando ao banco de dados...")
    
    # create_async_engine requires the URL to start with postgresql+asyncpg://
    db_url = settings.DATABASE_URL
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(db_url, echo=True)
    
    async with engine.begin() as conn:
        logger.info("🗑️ Resetando schema do banco de dados (apagando tabelas antigas)...")
        
        # Apagamos as tabelas em ordem para evitar erros de chave estrangeira
        drop_statements = [
            "DROP TABLE IF EXISTS monthly_closes CASCADE;",
            "DROP TABLE IF EXISTS policy_rules CASCADE;",
            "DROP TABLE IF EXISTS expenses CASCADE;",
            "DROP TABLE IF EXISTS users CASCADE;",
            "DROP TABLE IF EXISTS companies CASCADE;"
        ]

        for stmt in drop_statements:
            try:
                await conn.execute(text(stmt))
            except Exception as e:
                logger.warning(f"Aviso ao executar '{stmt}': {e}")
                
        logger.info("🛠️ Criando tabelas com o esquema mais recente...")
        await conn.run_sync(Base.metadata.create_all)
        
        logger.info("✅ Migração e Reset concluídos com sucesso!")
        
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
