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

    engine = create_async_engine(db_url, echo=False)

    sql_commands = [
        """
        CREATE TABLE IF NOT EXISTS notification_logs (
            id VARCHAR(36) PRIMARY KEY,
            company_id VARCHAR(36) REFERENCES companies(id),
            user_phone VARCHAR(30) NOT NULL,
            message_type VARCHAR(50) NOT NULL,
            content TEXT NOT NULL,
            status VARCHAR(20) DEFAULT 'SENT',
            sent_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            error_msg TEXT
        );
        """
    ]

    async with engine.begin() as conn:
        for sql in sql_commands:
            try:
                await conn.execute(text(sql))
            except Exception as e:
                print(f"Erro: {e}")

    await engine.dispose()
    print("Concluido!")

if __name__ == "__main__":
    asyncio.run(run_migrations())
