"""audio_clips.created_at NOT NULL, as in the model (c001 left it nullable).

Revision ID: c002
Revises: c001
Create Date: 2026-10-11
"""
from alembic import op
import sqlalchemy as sa

revision = "c002"
down_revision = "c001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE audio_clips SET created_at = now() WHERE created_at IS NULL")
    op.alter_column("audio_clips", "created_at", existing_type=sa.DateTime(timezone=True), nullable=False)


def downgrade() -> None:
    op.alter_column("audio_clips", "created_at", existing_type=sa.DateTime(timezone=True), nullable=True)
