"""Admin audit log and two-factor authentication.

- admin_audit_log: append-only record of what each admin did (and looked at). No foreign
  key to users on purpose: the row must survive the admin or the target user being
  deleted, so it keeps an email snapshot instead. A trigger rejects UPDATE and DELETE;
  the retention job deletes old rows by setting haman.audit_purge for its own transaction.
- admin_totp: one row per admin who has started or finished TOTP enrolment. The secret
  is stored encrypted (see services/admin_security.py), never in clear text.

Both tables are new and nothing existing is altered, so the migration can be rolled back
by downgrading without touching user data.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("admin_id", sa.BigInteger(), nullable=True),
        sa.Column("admin_email", sa.String(255), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("detail", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
    )
    op.create_index("ix_admin_audit_log_at", "admin_audit_log", ["at"])
    op.create_index("ix_admin_audit_log_admin_id", "admin_audit_log", ["admin_id"])
    op.create_index("ix_admin_audit_log_action", "admin_audit_log", ["action"])

    op.execute("""
        CREATE FUNCTION admin_audit_log_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND current_setting('haman.audit_purge', true) = 'on' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'admin_audit_log is append-only';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER admin_audit_log_append_only
        BEFORE UPDATE OR DELETE ON admin_audit_log
        FOR EACH ROW EXECUTE FUNCTION admin_audit_log_guard();
    """)

    op.create_table(
        "admin_totp",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("secret_enc", sa.Text(), nullable=False),
        # NULL until the admin proves they can generate a code; a pending row does not gate login.
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        # Highest 30-second step already accepted: a code can be used once.
        sa.Column("last_used_step", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("admin_totp")
    op.execute("DROP TRIGGER IF EXISTS admin_audit_log_append_only ON admin_audit_log")
    op.execute("DROP FUNCTION IF EXISTS admin_audit_log_guard()")
    op.drop_table("admin_audit_log")
