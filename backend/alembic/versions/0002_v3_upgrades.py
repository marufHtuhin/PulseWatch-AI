"""v3 upgrades: Telegram notifications, consecutive-failure detection,
data retention settings, and SSL expiry monitoring.

Adds columns to monitors and settings only. Every new NOT NULL column
carries a portable server_default, which SQLite requires when adding a
column to a populated table (and keeps MySQL consistent).
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_v3_upgrades"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # monitors: consecutive-failure detection + SSL expiry monitoring.
    op.add_column(
        "monitors",
        sa.Column(
            "alert_after_failures",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("2"),
        ),
    )
    op.add_column(
        "monitors",
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "monitors", sa.Column("cert_expires_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "monitors", sa.Column("cert_checked_at", sa.DateTime(), nullable=True)
    )

    # settings: Telegram notifications + data retention.
    op.add_column(
        "settings",
        sa.Column("telegram_bot_token", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "settings",
        sa.Column("telegram_chat_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "settings",
        sa.Column(
            "telegram_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "settings",
        sa.Column(
            "telegram_min_severity",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'high'"),
        ),
    )
    op.add_column(
        "settings",
        sa.Column(
            "retention_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("90"),
        ),
    )
    op.add_column(
        "settings",
        sa.Column(
            "alert_retention_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("365"),
        ),
    )


def downgrade() -> None:
    op.drop_column("settings", "alert_retention_days")
    op.drop_column("settings", "retention_days")
    op.drop_column("settings", "telegram_min_severity")
    op.drop_column("settings", "telegram_enabled")
    op.drop_column("settings", "telegram_chat_id")
    op.drop_column("settings", "telegram_bot_token")
    op.drop_column("monitors", "cert_checked_at")
    op.drop_column("monitors", "cert_expires_at")
    op.drop_column("monitors", "consecutive_failures")
    op.drop_column("monitors", "alert_after_failures")
