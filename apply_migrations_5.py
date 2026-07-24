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
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS submission_window_days INTEGER DEFAULT 30;"
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
