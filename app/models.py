import enum
from datetime import datetime, date
from sqlalchemy import String, Float, Date, DateTime, Enum, ForeignKey, Text
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
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True) # Ex: ALFA123 (Código para funcionários vincularem)
    name: Mapped[str] = mapped_column(String(100))
    admin_phone: Mapped[str] = mapped_column(String(30)) # Telefone do Gestor Principal
    plan: Mapped[PlanType] = mapped_column(Enum(PlanType), default=PlanType.FREE_TRIAL)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    users: Mapped[list["User"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    expenses: Mapped[list["Expense"]] = relationship(back_populates="company", cascade="all, delete-orphan")

class User(Base):
    __tablename__ = "users"

    phone: Mapped[str] = mapped_column(String(30), primary_key=True) # WhatsApp: ex 5511999998888
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    company_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("companies.id"), nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.EMPLOYEE)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    company: Mapped["Company | None"] = relationship(back_populates="users")
    expenses: Mapped[list["Expense"]] = relationship(back_populates="user", cascade="all, delete-orphan")

class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_phone: Mapped[str] = mapped_column(String(30), ForeignKey("users.phone"))
    company_id: Mapped[str] = mapped_column(String(36), ForeignKey("companies.id"))
    merchant_name: Mapped[str] = mapped_column(String(150)) # Nome do posto, restaurante, etc.
    merchant_cnpj: Mapped[str | None] = mapped_column(String(20), nullable=True)
    amount: Mapped[float] = mapped_column(Float)
    expense_date: Mapped[date] = mapped_column(Date)
    category: Mapped[ExpenseCategory] = mapped_column(Enum(ExpenseCategory), default=ExpenseCategory.OUTROS)
    status: Mapped[ExpenseStatus] = mapped_column(Enum(ExpenseStatus), default=ExpenseStatus.PENDING)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="expenses")
    company: Mapped["Company"] = relationship(back_populates="expenses")
