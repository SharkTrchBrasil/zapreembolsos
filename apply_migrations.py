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
        logger.info("🛠️ Criando tabelas novas (ex: PolicyRule)...")
        await conn.run_sync(Base.metadata.create_all)
        
        logger.info("⚡ Atualizando tabela 'expenses' com os novos campos da Fase 1...")
        
        alter_statements = [
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS image_s3_key VARCHAR(255);",
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS ocr_confidence FLOAT;",
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS ocr_raw_data TEXT;",
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS nfce_access_key VARCHAR(50);",
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS is_duplicate_suspect BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS justification TEXT;",
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS rejection_reason TEXT;",
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS approved_by VARCHAR(30);",
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP WITH TIME ZONE;",
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS has_receipt BOOLEAN DEFAULT TRUE;"
        ]

        for stmt in alter_statements:
            try:
                await conn.execute(text(stmt))
            except Exception as e:
                logger.warning(f"Aviso ao executar '{stmt}': {e}")
                
        logger.info("✅ Migração concluída com sucesso!")
        
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
