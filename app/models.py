import enum
from datetime import datetime, date, timezone
from sqlalchemy import String, Float, Numeric, Date, DateTime, Enum, ForeignKey, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class PlanType(str, enum.Enum):
    FREE_TRIAL = "FREE_TRIAL"
    PRO_START = "PRO_START"
    PRO_ENTERPRISE = "PRO_ENTERPRISE"

class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"        # Gestor / Dono da Empresa
    EMPLOYEE = "EMPLOYEE"  # Funcionário que envia comprovantes

class ExpenseCategory(str, enum.Enum):
    COMBUSTIVEL = "COMBUSTIVEL"
    ALIMENTACAO = "ALIMENTACAO"
    HOSPEDAGEM = "HOSPEDAGEM"
    TRANSPORTE = "TRANSPORTE"
    MANUTENCAO = "MANUTENCAO"
    OUTROS = "OUTROS"

class ExpenseStatus(str, enum.Enum):
    PENDING = "PENDING"      # Aguardando aprovação do gestor
    APPROVED = "APPROVED"    # Aprovada pelo gestor
    REJECTED = "REJECTED"    # Rejeitada pelo gestor
    REIMBURSED = "REIMBURSED"# Reembolso já efetuado

class Company(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True) # Ex: ALFA123
    name: Mapped[str] = mapped_column(String(100))
    admin_phone: Mapped[str] = mapped_column(String(30)) # Telefone do Gestor Principal
    admin_name: Mapped[str | None] = mapped_column(String(100), nullable=True) # Nome do Gestor Responsável
    cnpj: Mapped[str | None] = mapped_column(String(20), nullable=True) # CNPJ para faturamento/segurança
    estimated_employees: Mapped[str | None] = mapped_column(String(50), nullable=True) # Porte (ex: 1-10, 10-50, 50-500)
    billing_email: Mapped[str | None] = mapped_column(String(100), nullable=True)
    onboarding_step: Mapped[str | None] = mapped_column(String(50), nullable=True)
    plan: Mapped[PlanType] = mapped_column(Enum(PlanType), default=PlanType.FREE_TRIAL)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    subscription_status: Mapped[str | None] = mapped_column(String(30), default="TRIAL") # TRIAL, ACTIVE, EXPIRED
    monthly_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    km_rate: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    users: Mapped[list["User"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    expenses: Mapped[list["Expense"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    policies: Mapped[list["PolicyRule"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    monthly_closes: Mapped[list["MonthlyClose"]] = relationship(back_populates="company", cascade="all, delete-orphan")

class User(Base):
    __tablename__ = "users"

    phone: Mapped[str] = mapped_column(String(30), primary_key=True) # WhatsApp: ex 5511999998888
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(100), nullable=True) # E-mail do usuário
    department: Mapped[str | None] = mapped_column(String(100), nullable=True) # Setor / Secretaria
    job_title: Mapped[str | None] = mapped_column(String(100), nullable=True) # Cargo / Profissão
    is_approved: Mapped[bool] = mapped_column(Boolean, default=True) # Se já foi aprovado pelo gestor
    onboarding_step: Mapped[str | None] = mapped_column(String(50), nullable=True) # Passo da máquina de estados
    company_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("companies.id"), nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.EMPLOYEE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    company: Mapped["Company | None"] = relationship(back_populates="users")
    expenses: Mapped[list["Expense"]] = relationship("Expense", foreign_keys="[Expense.user_phone]", back_populates="user", cascade="all, delete-orphan")

class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_phone: Mapped[str] = mapped_column(String(30), ForeignKey("users.phone"))
    company_id: Mapped[str] = mapped_column(String(36), ForeignKey("companies.id"))
    merchant_name: Mapped[str] = mapped_column(String(150)) # Nome do posto, restaurante, etc.
    merchant_cnpj: Mapped[str | None] = mapped_column(String(20), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(10, 2))
    expense_date: Mapped[date] = mapped_column(Date)
    category: Mapped[ExpenseCategory] = mapped_column(Enum(ExpenseCategory), default=ExpenseCategory.OUTROS)
    status: Mapped[ExpenseStatus] = mapped_column(Enum(ExpenseStatus), default=ExpenseStatus.PENDING)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Novos campos Fase 1
    image_s3_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ocr_raw_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    nfce_access_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_duplicate_suspect: Mapped[bool] = mapped_column(Boolean, default=False)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(30), ForeignKey("users.phone"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    has_receipt: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user: Mapped["User"] = relationship("User", foreign_keys=[user_phone], back_populates="expenses")
    approver: Mapped["User | None"] = relationship("User", foreign_keys=[approved_by])
    company: Mapped["Company"] = relationship(back_populates="expenses")

class PolicyRule(Base):
    __tablename__ = "policy_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(36), ForeignKey("companies.id"))
    category: Mapped[ExpenseCategory | None] = mapped_column(Enum(ExpenseCategory), nullable=True)
    max_amount: Mapped[float] = mapped_column(Numeric(10, 2))
    requires_receipt: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    company: Mapped["Company"] = relationship(back_populates="policies")

class MonthlyClose(Base):
    __tablename__ = "monthly_closes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(36), ForeignKey("companies.id"))
    year: Mapped[int] = mapped_column(nullable=False)
    month: Mapped[int] = mapped_column(nullable=False)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    closed_by: Mapped[str] = mapped_column(String(30), ForeignKey("users.phone"))
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2))
    total_expenses: Mapped[int] = mapped_column(nullable=False)

    company: Mapped["Company"] = relationship(back_populates="monthly_closes")
    closer: Mapped["User"] = relationship("User", foreign_keys=[closed_by])
