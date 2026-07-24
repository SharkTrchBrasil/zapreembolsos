"""Add departments, categories, and audit_logs

Revision ID: 57028e890a2b
Revises: 16d96468c0f7
Create Date: 2026-07-23 18:15:45.723073

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '57028e890a2b'
down_revision: Union[str, None] = '16d96468c0f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use bind to get the current connection and check if tables exist
    conn = op.get_bind()
    
    # Departments
    op.execute("""
        CREATE TABLE IF NOT EXISTS departments (
            id VARCHAR(36) PRIMARY KEY,
            company_id VARCHAR(36) REFERENCES companies(id),
            name VARCHAR(100) NOT NULL,
            parent_id VARCHAR(36) REFERENCES departments(id),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)
    
    # Categories
    op.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id VARCHAR(36) PRIMARY KEY,
            company_id VARCHAR(36) REFERENCES companies(id),
            name VARCHAR(100) NOT NULL,
            icon VARCHAR(10),
            requires_receipt BOOLEAN DEFAULT TRUE,
            max_per_day NUMERIC(10, 2),
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)
    
    # Audit Logs
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id VARCHAR(36) PRIMARY KEY,
            company_id VARCHAR(36) REFERENCES companies(id),
            user_phone VARCHAR(30) REFERENCES users(phone),
            action VARCHAR(100) NOT NULL,
            entity_type VARCHAR(50) NOT NULL,
            entity_id VARCHAR(100) NOT NULL,
            old_value TEXT,
            new_value TEXT,
            ip_address VARCHAR(45),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)
    
    # Add foreign keys to existing tables
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS department_id VARCHAR(36) REFERENCES departments(id)")
    op.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS category_id VARCHAR(36) REFERENCES categories(id)")


def downgrade() -> None:
    op.execute("ALTER TABLE expenses DROP COLUMN IF EXISTS category_id")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS department_id")
    op.execute("DROP TABLE IF EXISTS audit_logs")
    op.execute("DROP TABLE IF EXISTS categories")
    op.execute("DROP TABLE IF EXISTS departments")
