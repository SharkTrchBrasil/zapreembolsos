import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv()

async def run_migrations():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ DATABASE_URL não encontrada")
        return

    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)

    print("Conectando...")
    engine = create_async_engine(db_url, echo=False)

    sql_commands = [
        "ALTER TABLE policy_rules ADD COLUMN IF NOT EXISTS category_id VARCHAR(36) REFERENCES categories(id);"
    ]

    async with engine.begin() as conn:
        for sql in sql_commands:
            try:
                await conn.execute(text(sql))
                print("Sucesso!")
            except Exception as e:
                print(f"Erro: {e}")

    await engine.dispose()
    print("Concluido!")

if __name__ == "__main__":
    asyncio.run(run_migrations())
