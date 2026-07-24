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
        """
        CREATE TABLE IF NOT EXISTS permissions (
            id VARCHAR(36) PRIMARY KEY,
            code VARCHAR(50) UNIQUE NOT NULL,
            description VARCHAR(100) NOT NULL,
            "group" VARCHAR(50) NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS roles (
            id VARCHAR(36) PRIMARY KEY,
            company_id VARCHAR(36) REFERENCES companies(id),
            name VARCHAR(100) NOT NULL,
            is_system_role BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS role_permissions (
            id VARCHAR(36) PRIMARY KEY,
            role_id VARCHAR(36) REFERENCES roles(id) ON DELETE CASCADE,
            permission_id VARCHAR(36) REFERENCES permissions(id) ON DELETE CASCADE
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS user_roles (
            id VARCHAR(36) PRIMARY KEY,
            user_phone VARCHAR(30) REFERENCES users(phone) ON DELETE CASCADE,
            role_id VARCHAR(36) REFERENCES roles(id) ON DELETE CASCADE,
            scope VARCHAR(20) DEFAULT 'COMPANY',
            department_id VARCHAR(36) REFERENCES departments(id) ON DELETE CASCADE
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
