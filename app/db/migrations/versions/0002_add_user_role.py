"""add user_role to users

Revision ID: 0002_add_user_role
Revises: 0001_initial
Create Date: 2026-02-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_add_user_role"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("user_role", sa.String(length=10), nullable=True, server_default="staff"))
    op.execute(
        """
        UPDATE users
        SET user_role = CASE
            WHEN role = 'ADMIN' THEN 'admin'
            ELSE 'staff'
        END
        """
    )
    op.alter_column("users", "user_role", nullable=False, server_default="staff")


def downgrade() -> None:
    op.drop_column("users", "user_role")
