import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from app.models import Base
from app.config import settings

async def main():
    print(f"🔄 Conectando ao banco de dados: {settings.DATABASE_URL}")
    engine = create_async_engine(settings.DATABASE_URL, echo=True)
    
    async with engine.begin() as conn:
        print("🛠️  Criando/Atualizando tabelas no PostgreSQL...")
        await conn.run_sync(Base.metadata.create_all)
        print("✅ Migração concluída com sucesso!")
        
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
