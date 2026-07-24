import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv()

async def run_migrations():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL não encontrada")
        return

    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)

    print("Conectando ao banco...")
    engine = create_async_engine(db_url, echo=False)

    sql_commands = [
        "ALTER TABLE policy_rules ADD COLUMN IF NOT EXISTS requires_double_approval_above NUMERIC(10, 2);",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS delegated_to VARCHAR(30) REFERENCES users(phone);",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS delegation_expires_at TIMESTAMP WITH TIME ZONE;",
        """
        CREATE TABLE IF NOT EXISTS attachments (
            id VARCHAR(36) PRIMARY KEY,
            expense_id VARCHAR(36) NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
            file_type VARCHAR(50) NOT NULL,
            s3_key VARCHAR(255) NOT NULL,
            url TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS approval_steps (
            id VARCHAR(36) PRIMARY KEY,
            expense_id VARCHAR(36) NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
            step_order INTEGER NOT NULL,
            approver_phone VARCHAR(30) NOT NULL REFERENCES users(phone),
            status VARCHAR(20) DEFAULT 'PENDING',
            comment TEXT,
            decided_at TIMESTAMP WITH TIME ZONE
        );
        """
    ]

    async with engine.begin() as conn:
        print("Executando comandos...")
        for sql in sql_commands:
            try:
                await conn.execute(text(sql))
                print(f"Sucesso!")
            except Exception as e:
                print(f"Erro ao executar SQL: {e}")

    await engine.dispose()
    print("Concluido!")

if __name__ == "__main__":
    asyncio.run(run_migrations())
