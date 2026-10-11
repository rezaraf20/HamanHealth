"""Clips database: pseudonymised audio clip index (no user ids).

Revision ID: c001
Revises:
Create Date: 2026-10-10
"""
from alembic import op
import sqlalchemy as sa

revision = "c001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audio_clips",
        sa.Column("anon_id", sa.String(64), primary_key=True),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("sample_rate", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audio_clips_expires_at", "audio_clips", ["expires_at"])


def downgrade() -> None:
    op.drop_table("audio_clips")
