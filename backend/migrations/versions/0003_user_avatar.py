"""Profile photo.

- users.avatar: the user's profile photo as a small data: URL (the web app resizes to
  256px before upload). Nullable, so existing rows are unaffected and fall back to initials.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar")
