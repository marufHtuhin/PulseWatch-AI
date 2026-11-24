"""v4.2 admin role: ``is_admin`` flag on users.

- ``users.is_admin``: admins can list/inspect/deactivate/delete other
  users and see all monitors via the /api/admin/* endpoints (see
  app.api.routes.admin). Defaults to false; the startup bootstrap
  (ADMIN_EMAIL/ADMIN_PASSWORD) creates or promotes the admin account
  (see app.core.auth.bootstrap_admin).
- Column change uses ``batch_alter_table`` (see 0003/0004): SQLite
  needs batch mode for column changes; on MySQL it just issues a
  normal ALTER. ``server_default`` backfills existing rows as
  non-admin.
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_v4_2_admin"
down_revision = "0004_v4_1_auth_ux"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_admin",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("is_admin")
