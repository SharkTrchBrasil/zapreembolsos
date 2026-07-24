import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from dotenv import load_dotenv

# Carrega variáveis de ambiente
load_dotenv()

async def run_migrations():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ DATABASE_URL não encontrada no .env")
        return

    # Ajuste para asyncpg
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    print(f"Conectando ao banco de dados...")
    engine = create_async_engine(db_url, echo=False)

    sql_commands = [
        # Tabelas da Fase 1
        """
        CREATE TABLE IF NOT EXISTS departments (
            id VARCHAR(36) PRIMARY KEY,
            company_id VARCHAR(36) REFERENCES companies(id),
            name VARCHAR(100) NOT NULL,
            parent_id VARCHAR(36) REFERENCES departments(id),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS categories (
            id VARCHAR(36) PRIMARY KEY,
            company_id VARCHAR(36) REFERENCES companies(id),
            name VARCHAR(100) NOT NULL,
            icon VARCHAR(10),
            requires_receipt BOOLEAN DEFAULT TRUE,
            max_per_day NUMERIC(10, 2),
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id VARCHAR(36) PRIMARY KEY,
            company_id VARCHAR(36) REFERENCES companies(id),
            user_phone VARCHAR(30) REFERENCES users(phone),
            action VARCHAR(100) NOT NULL,
            entity_type VARCHAR(50) NOT NULL,
            entity_id VARCHAR(100) NOT NULL,
            old_value TEXT,
            new_value TEXT,
            ip_address VARCHAR(45),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        );
        """,
        # Alterações nas tabelas existentes
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS department_id VARCHAR(36) REFERENCES departments(id);",
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS category_id VARCHAR(36) REFERENCES categories(id);"
    ]

    async with engine.begin() as conn:
        print("Executando comandos DDL...")
        for sql in sql_commands:
            try:
                await conn.execute(text(sql))
                print(f"Executado com sucesso!")
            except Exception as e:
                print(f"Erro ao executar SQL: {e}")

    await engine.dispose()
    print("Alteracoes de banco concluidas!")

if __name__ == "__main__":
    asyncio.run(run_migrations())
