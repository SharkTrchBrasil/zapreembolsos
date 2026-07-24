from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings
import logging

logger = logging.getLogger("database")

# Normaliza a URL do banco para suporte assíncrono (asyncpg) vindo do Coolify / Heroku / Supabase
db_url = settings.DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+asyncpg://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(db_url, echo=settings.DEBUG, pool_size=20, max_overflow=30, pool_pre_ping=True, pool_recycle=1800)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

class Base(DeclarativeBase):
    pass

from sqlalchemy import text

async def init_db():
    async with engine.begin() as conn:
        # Cria as tabelas caso ainda não existam (Mata as tabelas bases para garantir)
        await conn.run_sync(Base.metadata.create_all)

        # Garante que todas as colunas novas sejam adicionadas em tabelas pré-existentes no PostgreSQL
        migration_sqls = [
            # Tabela users
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(100);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS department VARCHAR(100);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS job_title VARCHAR(100);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_approved BOOLEAN DEFAULT TRUE;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_step VARCHAR(255);",
            "ALTER TABLE users ALTER COLUMN onboarding_step TYPE VARCHAR(255);",

            # Tabela companies
            "ALTER TABLE companies ADD COLUMN IF NOT EXISTS admin_name VARCHAR(100);",
            "ALTER TABLE companies ADD COLUMN IF NOT EXISTS cnpj VARCHAR(20);",
            "ALTER TABLE companies ADD COLUMN IF NOT EXISTS estimated_employees VARCHAR(50);",
            "ALTER TABLE companies ADD COLUMN IF NOT EXISTS billing_email VARCHAR(100);",
            "ALTER TABLE companies ADD COLUMN IF NOT EXISTS onboarding_step VARCHAR(255);",
            "ALTER TABLE companies ALTER COLUMN onboarding_step TYPE VARCHAR(255);",
            "ALTER TABLE companies ADD COLUMN IF NOT EXISTS km_rate NUMERIC(10, 2);",
            "ALTER TABLE companies ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMPTZ;",
            "ALTER TABLE companies ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(30) DEFAULT 'TRIAL';",
            "ALTER TABLE companies ADD COLUMN IF NOT EXISTS monthly_price NUMERIC(10, 2);",

            # Tabela expenses
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS image_s3_key VARCHAR(255);",
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS ocr_confidence FLOAT;",
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS ocr_raw_data TEXT;",
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS nfce_access_key VARCHAR(50);",
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS is_duplicate_suspect BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS justification TEXT;",
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS rejection_reason TEXT;",
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS approved_by VARCHAR(30);",
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP WITH TIME ZONE;",
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS has_receipt BOOLEAN DEFAULT TRUE;",

            # Novas colunas adicionadas nas Fases 1-3
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();",
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS receipt_url TEXT;",
        ]

        logger.info("🔄 Executando verificação de colunas e migrações do banco de dados...")
        for sql in migration_sqls:
            try:
                await conn.execute(text(sql))
            except Exception as e:
                logger.warning(f"⚠️ Aviso na migração: {e}")
        logger.info("✅ Banco de dados e schemas verificados com sucesso!")

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
