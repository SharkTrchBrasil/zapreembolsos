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
    CANCELLED = "CANCELLED"  # Cancelada pelo funcionário
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED" # Aprovada por 1 nível, aguardando próximo

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
    onboarding_step: Mapped[str | None] = mapped_column(String(255), nullable=True)
    plan: Mapped[PlanType] = mapped_column(Enum(PlanType), default=PlanType.FREE_TRIAL)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    subscription_status: Mapped[str | None] = mapped_column(String(30), default="TRIAL") # TRIAL, ACTIVE, EXPIRED
    monthly_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    km_rate: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    submission_window_days: Mapped[int] = mapped_column(default=30)

    users: Mapped[list["User"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    expenses: Mapped[list["Expense"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    policies: Mapped[list["PolicyRule"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    monthly_closes: Mapped[list["MonthlyClose"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    departments: Mapped[list["Department"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    categories: Mapped[list["Category"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    roles: Mapped[list["Role"]] = relationship(back_populates="company", cascade="all, delete-orphan")

class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True) # e.g. manage_users
    description: Mapped[str] = mapped_column(String(100))
    group: Mapped[str] = mapped_column(String(50)) # e.g. Admin, Finance
    
class Role(Base):
    __tablename__ = "roles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("companies.id"), nullable=True) # None = System Role
    name: Mapped[str] = mapped_column(String(100))
    is_system_role: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    company: Mapped["Company | None"] = relationship(back_populates="roles")
    role_permissions: Mapped[list["RolePermission"]] = relationship(cascade="all, delete-orphan")

class RolePermission(Base):
    __tablename__ = "role_permissions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    role_id: Mapped[str] = mapped_column(String(36), ForeignKey("roles.id"))
    permission_id: Mapped[str] = mapped_column(String(36), ForeignKey("permissions.id"))
    
class UserRoleModel(Base):
    __tablename__ = "user_roles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_phone: Mapped[str] = mapped_column(String(30), ForeignKey("users.phone"))
    role_id: Mapped[str] = mapped_column(String(36), ForeignKey("roles.id"))
    scope: Mapped[str] = mapped_column(String(20), default="COMPANY") # COMPANY or DEPARTMENT
    department_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("departments.id"), nullable=True)

class Department(Base):
    __tablename__ = "departments"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(36), ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String(100))
    parent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("departments.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    company: Mapped["Company"] = relationship(back_populates="departments")
    users: Mapped[list["User"]] = relationship(back_populates="department_rel")

class Category(Base):
    __tablename__ = "categories"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(36), ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String(100))
    icon: Mapped[str | None] = mapped_column(String(10), nullable=True)
    requires_receipt: Mapped[bool] = mapped_column(Boolean, default=True)
    max_per_day: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    company: Mapped["Company"] = relationship(back_populates="categories")
    expenses: Mapped[list["Expense"]] = relationship(back_populates="custom_category")

class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(36), ForeignKey("companies.id"))
    user_phone: Mapped[str] = mapped_column(String(30), ForeignKey("users.phone"))
    action: Mapped[str] = mapped_column(String(100)) # Ex: CREATE_EXPENSE, APPROVE_USER
    entity_type: Mapped[str] = mapped_column(String(50)) # Ex: Expense, User
    entity_id: Mapped[str] = mapped_column(String(100)) # ID da entidade afetada
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    company: Mapped["Company"] = relationship(back_populates="audit_logs")
    user: Mapped["User"] = relationship(foreign_keys=[user_phone])

class User(Base):
    __tablename__ = "users"

    phone: Mapped[str] = mapped_column(String(30), primary_key=True) # WhatsApp: ex 5511999998888
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(100), nullable=True) # E-mail do usuário
    job_title: Mapped[str | None] = mapped_column(String(100), nullable=True) # Cargo / Profissão
    is_approved: Mapped[bool] = mapped_column(Boolean, default=True) # Se já foi aprovado pelo gestor
    onboarding_step: Mapped[str | None] = mapped_column(String(255), nullable=True) # Passo da máquina de estados
    department: Mapped[str | None] = mapped_column(String(100), nullable=True) # Legado, manter por enquanto
    department_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("departments.id"), nullable=True)
    company_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("companies.id"), nullable=True)
    delegated_to: Mapped[str | None] = mapped_column(String(30), ForeignKey("users.phone"), nullable=True)
    delegation_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.EMPLOYEE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    company: Mapped["Company | None"] = relationship(back_populates="users")
    department_rel: Mapped["Department | None"] = relationship(back_populates="users")
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
    category: Mapped[ExpenseCategory] = mapped_column(Enum(ExpenseCategory), default=ExpenseCategory.OUTROS) # Legado
    category_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("categories.id"), nullable=True)
    status: Mapped[ExpenseStatus] = mapped_column(Enum(ExpenseStatus), default=ExpenseStatus.PENDING)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Novos campos Fase 1
    image_s3_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ocr_raw_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    nfce_access_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_duplicate_suspect: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_expense_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("expenses.id"), nullable=True) # Para reenvios
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(30), ForeignKey("users.phone"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    has_receipt: Mapped[bool] = mapped_column(Boolean, default=True)
    receipt_url: Mapped[str | None] = mapped_column(Text, nullable=True)  # URL pública do comprovante (S3 presigned)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user: Mapped["User"] = relationship("User", foreign_keys=[user_phone], back_populates="expenses")
    approver: Mapped["User | None"] = relationship("User", foreign_keys=[approved_by])
    company: Mapped["Company"] = relationship(back_populates="expenses")
    custom_category: Mapped["Category | None"] = relationship(back_populates="expenses")
    attachments: Mapped[list["Attachment"]] = relationship("Attachment", back_populates="expense", cascade="all, delete-orphan")
    approval_steps: Mapped[list["ApprovalStep"]] = relationship("ApprovalStep", back_populates="expense", cascade="all, delete-orphan")

class PolicyRule(Base):
    __tablename__ = "policy_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(36), ForeignKey("companies.id"))
    category: Mapped[ExpenseCategory | None] = mapped_column(Enum(ExpenseCategory), nullable=True) # Legado
    category_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("categories.id"), nullable=True)
    max_amount: Mapped[float] = mapped_column(Numeric(10, 2))
    auto_approve_below: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    requires_double_approval_above: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    requires_receipt: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    company: Mapped["Company"] = relationship(back_populates="policies")
    custom_category: Mapped["Category | None"] = relationship()

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

class Attachment(Base):
    __tablename__ = "attachments"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    expense_id: Mapped[str] = mapped_column(String(36), ForeignKey("expenses.id", ondelete="CASCADE"))
    file_type: Mapped[str] = mapped_column(String(50)) # e.g. "image/jpeg", "application/pdf"
    s3_key: Mapped[str] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(Text, nullable=True) # presigned url
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    expense: Mapped["Expense"] = relationship(back_populates="attachments")

class ApprovalStep(Base):
    __tablename__ = "approval_steps"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    expense_id: Mapped[str] = mapped_column(String(36), ForeignKey("expenses.id", ondelete="CASCADE"))
    step_order: Mapped[int] = mapped_column()
    approver_phone: Mapped[str] = mapped_column(String(30), ForeignKey("users.phone"))
    status: Mapped[str] = mapped_column(String(20), default="PENDING") # PENDING, APPROVED, REJECTED
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    expense: Mapped["Expense"] = relationship(back_populates="approval_steps")
    approver: Mapped["User"] = relationship("User", foreign_keys=[approver_phone])

class NotificationLog(Base):
    __tablename__ = "notification_logs"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("companies.id"), nullable=True)
    user_phone: Mapped[str] = mapped_column(String(30))
    message_type: Mapped[str] = mapped_column(String(50)) # e.g. "REMINDER", "EXPENSE_REJECTED"
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="SENT")
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
