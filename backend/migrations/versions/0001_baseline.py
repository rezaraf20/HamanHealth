"""Baseline: the schema as it was before migrations were introduced.

Until now tables were created by Base.metadata.create_all at startup, so existing
servers already have some or all of them. This revision therefore only creates what is
missing (and adds cough_sessions.is_active, which migrate_add_is_active.py used to add
by hand). On an existing server and on an empty database it ends in the same state, so
no manual `alembic stamp` is needed.

Revision ID: 0001
Revises:
Create Date: 2026-10-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = _tables()

    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("hashed_password", sa.String(255), nullable=False),
            sa.Column("name", sa.String(255)),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("is_admin", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_users_id", "users", ["id"])
        op.create_index("ix_users_email", "users", ["email"], unique=True)

    if "cough_sessions" not in tables:
        op.create_table(
            "cough_sessions",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("device_session_id", sa.String(64), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ended_at", sa.DateTime(timezone=True)),
            sa.Column("sensitivity", sa.String(16)),
            sa.Column("event_count", sa.Integer(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("note", sa.Text()),
        )
        op.create_index("ix_cough_sessions_id", "cough_sessions", ["id"])
        op.create_index("ix_cough_sessions_user_id", "cough_sessions", ["user_id"])
    elif "is_active" not in _columns("cough_sessions"):
        op.add_column("cough_sessions",
                      sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()))

    if "cough_events" not in tables:
        op.create_table(
            "cough_events",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column("session_id", sa.BigInteger(), sa.ForeignKey("cough_sessions.id"), nullable=False),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("confidence", sa.Float()),
            sa.Column("clip_anon_id", sa.String(64)),
        )
        op.create_index("ix_cough_events_id", "cough_events", ["id"])
        op.create_index("ix_cough_events_session_id", "cough_events", ["session_id"])

    if "health_records" not in tables:
        op.create_table(
            "health_records",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("record_type", sa.String(32), nullable=False),
            sa.Column("record_date", sa.String(10), nullable=False),
            sa.Column("file_name", sa.String(255), nullable=False),
            sa.Column("file_path", sa.String(512), nullable=False),
            sa.Column("mime", sa.String(128), nullable=False),
            sa.Column("size_kb", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_health_records_id", "health_records", ["id"])
        op.create_index("ix_health_records_user_id", "health_records", ["user_id"])


def downgrade() -> None:
    # The baseline is the starting point; there is nothing earlier to go back to.
    raise NotImplementedError("Cannot downgrade past the baseline")
