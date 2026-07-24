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
        # Adicionar novo valor no Enum ExpenseStatus se o Postgres suportar ou lidar caso o driver não crie como enum real
        # Na verdade, o SQLAlchemy cria VARCHAR com check constraint por padrão para Enum, a menos que native_enum=True
        # Para simplificar, vou alterar as tabelas que importam:
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS parent_expense_id VARCHAR(36) REFERENCES expenses(id);",
        "ALTER TABLE policy_rules ADD COLUMN IF NOT EXISTS auto_approve_below NUMERIC(10, 2);"
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
