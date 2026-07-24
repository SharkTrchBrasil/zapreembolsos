import pytest
import pytest_asyncio
import uuid
from datetime import datetime, timezone, timedelta, date
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.database import Base
from app.models import (
    User, Company, Expense, UserRole, ExpenseStatus, ExpenseCategory,
    PlanType, PolicyRule, Department, Category, Role, Permission,
    RolePermission, UserRoleModel, AuditLog
)

from sqlalchemy.pool import StaticPool

# In-memory SQLite for tests (StaticPool = single shared connection)
TEST_DB_URL = "sqlite+aiosqlite://"

@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        TEST_DB_URL,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest.fixture
def mock_wuzapi():
    """Mock WuzAPI client that captures all sent messages."""
    mock = AsyncMock()
    mock.sent_messages = []
    mock.sent_images = []
    
    async def capture_text(phone, message):
        mock.sent_messages.append({"phone": phone, "message": message})
        return True
    
    async def capture_image(phone, image_url, caption=""):
        mock.sent_images.append({"phone": phone, "url": image_url, "caption": caption})
        return True
    
    mock.send_text_message = AsyncMock(side_effect=capture_text)
    mock.send_image_message = AsyncMock(side_effect=capture_image)
    mock.send_typing_indicator = AsyncMock(return_value=True)
    mock.send_document_message = AsyncMock(return_value=True)
    mock.download_media = AsyncMock(return_value=b"fake_image_bytes")
    return mock

@pytest_asyncio.fixture
async def sample_company(db_session):
    company = Company(
        id=str(uuid.uuid4()),
        code="TEST123",
        name="Empresa Teste",
        admin_phone="5511999990000",
        admin_name="Admin Teste",
        plan=PlanType.FREE_TRIAL,
        trial_ends_at=datetime.now(timezone.utc) + timedelta(days=30),
        subscription_status="TRIAL",
        submission_window_days=30
    )
    db_session.add(company)
    await db_session.commit()
    await db_session.refresh(company)
    return company

@pytest_asyncio.fixture
async def sample_admin(db_session, sample_company):
    user = User(
        phone="5511999990000",
        name="Admin Teste",
        email="admin@teste.com",
        role=UserRole.ADMIN,
        company_id=sample_company.id,
        is_approved=True
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user

@pytest_asyncio.fixture
async def sample_employee(db_session, sample_company):
    user = User(
        phone="5511888880000",
        name="Funcionario Teste",
        email="func@teste.com",
        role=UserRole.EMPLOYEE,
        company_id=sample_company.id,
        is_approved=True,
        department="Vendas",
        job_title="Vendedor"
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user

@pytest_asyncio.fixture
async def sample_expense(db_session, sample_employee, sample_company):
    expense = Expense(
        id=str(uuid.uuid4()),
        user_phone=sample_employee.phone,
        company_id=sample_company.id,
        merchant_name="Restaurante Teste",
        merchant_cnpj="12345678000190",
        amount=45.50,
        expense_date=date.today(),
        category=ExpenseCategory.ALIMENTACAO,
        status=ExpenseStatus.PENDING,
        has_receipt=True
    )
    db_session.add(expense)
    await db_session.commit()
    await db_session.refresh(expense)
    return expense

@pytest_asyncio.fixture
async def sample_policy(db_session, sample_company):
    rule = PolicyRule(
        id=str(uuid.uuid4()),
        company_id=sample_company.id,
        max_amount=500.0,
        auto_approve_below=50.0,
        requires_receipt=True,
        is_active=True
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)
    return rule
