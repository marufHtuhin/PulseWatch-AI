"""v4 auth + multi-user isolation: users table, and a nullable owner
(``user_id``) on monitors and settings.

- ``users``: id, unique email, bcrypt password hash, is_active, created_at.
- ``monitors.user_id`` / ``settings.user_id`` are nullable so pre-v4 rows
  survive the migration as ownerless; the runtime admin bootstrap claims
  them (no data migration inside alembic).
- ``settings.user_id`` is unique (one settings row per user). SQLite and
  MySQL both allow multiple NULLs in a unique index, so ownerless rows
  never collide.
- FKs use ON DELETE SET NULL: deleting a user orphans their monitors and
  settings row instead of destroying monitoring history.
- Column/constraint changes use ``batch_alter_table``: SQLite cannot add
  a column carrying a foreign key (or add a unique constraint) with a
  plain ALTER TABLE, so alembic's copy-and-move batch mode is required
  there; on MySQL batch mode just issues normal ALTERs.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_v4_auth"
down_revision = "0002_v3_upgrades"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=False)

    with op.batch_alter_table("monitors") as batch_op:
        batch_op.add_column(
            sa.Column(
                "user_id",
                sa.Integer(),
                # Batch mode requires named constraints.
                sa.ForeignKey(
                    "users.id",
                    ondelete="SET NULL",
                    name="fk_monitors_user_id",
                ),
                nullable=True,
            )
        )
        batch_op.create_index("ix_monitors_user_id", ["user_id"], unique=False)

    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey(
                    "users.id",
                    ondelete="SET NULL",
                    name="fk_settings_user_id",
                ),
                nullable=True,
            )
        )
        batch_op.create_index("ix_settings_user_id", ["user_id"], unique=False)
        batch_op.create_unique_constraint("uq_settings_user_id", ["user_id"])


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_constraint("uq_settings_user_id", type_="unique")
        batch_op.drop_index("ix_settings_user_id")
        batch_op.drop_column("user_id")
    with op.batch_alter_table("monitors") as batch_op:
        batch_op.drop_index("ix_monitors_user_id")
        batch_op.drop_column("user_id")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
