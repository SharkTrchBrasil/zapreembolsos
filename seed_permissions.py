import asyncio
import os
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text, select
from dotenv import load_dotenv

load_dotenv()

async def seed_permissions():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL não encontrada")
        return

    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)

    print("Conectando ao banco...")
    engine = create_async_engine(db_url, echo=False)

    permissions = [
        {"code": "manage_users", "description": "Gerenciar funcionários e equipe", "group": "Admin"},
        {"code": "approve_expenses", "description": "Aprovar e rejeitar despesas", "group": "Finance"},
        {"code": "view_reports", "description": "Visualizar relatórios e extratos", "group": "Reports"},
        {"code": "export_data", "description": "Exportar dados", "group": "Reports"},
        {"code": "edit_limits", "description": "Editar limites de política", "group": "Admin"},
        {"code": "manage_categories", "description": "Gerenciar categorias de despesa", "group": "Admin"},
        {"code": "view_audit", "description": "Visualizar log de auditoria", "group": "Admin"},
        {"code": "manage_company", "description": "Gerenciar configurações da empresa", "group": "Admin"}
    ]

    async with engine.begin() as conn:
        for p in permissions:
            # Check if exists
            res = await conn.execute(text("SELECT id FROM permissions WHERE code = :code"), {"code": p["code"]})
            if not res.fetchone():
                await conn.execute(
                    text("INSERT INTO permissions (id, code, description, \"group\") VALUES (:id, :code, :desc, :grp)"),
                    {"id": str(uuid.uuid4()), "code": p["code"], "desc": p["description"], "grp": p["group"]}
                )
                print(f"Permissão {p['code']} inserida.")

    await engine.dispose()
    print("Permissões cadastradas!")

if __name__ == "__main__":
    asyncio.run(seed_permissions())
