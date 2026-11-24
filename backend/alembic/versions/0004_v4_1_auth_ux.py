"""v4.1 auth UX: password-change timestamp on users + password reset
tokens table (email OTP flow).

- ``users.password_changed_at``: set whenever a password is changed or
  reset; JWTs issued before it are rejected (see app.core.auth). NULL
  for users who never changed their password — their pre-v4.1 tokens
  (which carry no ``iat`` claim) stay valid.
- ``password_reset_tokens``: one row per forgot-password request. Only
  the sha256 hex digest of the 6-digit OTP is stored, never the OTP
  itself. ``attempts`` caps wrong guesses at 5 (the row is then marked
  used); ``used`` marks consumed / superseded / locked rows. FK uses ON
  DELETE CASCADE: deleting a user removes their reset tokens.
- Column/constraint changes use ``batch_alter_table`` (see 0003):
  SQLite needs batch mode for FK-bearing column changes; on MySQL it
  just issues normal ALTERs.
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_v4_1_auth_ux"
down_revision = "0003_v4_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("password_changed_at", sa.DateTime(), nullable=True)
        )

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            # Batch mode requires named constraints.
            sa.ForeignKey(
                "users.id",
                ondelete="CASCADE",
                name="fk_password_reset_tokens_user_id",
            ),
            nullable=False,
        ),
        sa.Column("otp_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_password_reset_tokens_user_id",
        "password_reset_tokens",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_password_reset_tokens_user_id", table_name="password_reset_tokens"
    )
    op.drop_table("password_reset_tokens")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("password_changed_at")
