"""Initial schema: monitors, monitoring_records, anomalies, alerts, settings.

Hand-written to be dialect-agnostic: only portable column types
(String/Integer/Float/Boolean/Text/DateTime/JSON) and standard foreign keys
are used, so the same migration runs on MySQL and SQLite.
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monitors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=True),
        sa.Column("request_body", sa.Text(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("expected_status_codes", sa.JSON(), nullable=False),
        sa.Column("expected_fields", sa.JSON(), nullable=False),
        sa.Column("check_zero_records", sa.Boolean(), nullable=False),
        sa.Column("latency_threshold_ms", sa.Integer(), nullable=False),
        sa.Column("max_response_size_bytes", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(length=20), nullable=False),
        sa.Column("last_response_time_ms", sa.Float(), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_monitors_is_active", "monitors", ["is_active"])
    op.create_index("ix_monitors_last_status", "monitors", ["last_status"])

    op.create_table(
        "monitoring_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("monitor_id", sa.Integer(), nullable=False),
        sa.Column("response_time_ms", sa.Float(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_size_bytes", sa.Integer(), nullable=False),
        sa.Column("records_returned", sa.Integer(), nullable=True),
        sa.Column("is_success", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("is_valid_json", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_monitoring_records_monitor_id", "monitoring_records", ["monitor_id"]
    )
    op.create_index(
        "ix_monitoring_records_checked_at", "monitoring_records", ["checked_at"]
    )
    op.create_index(
        "ix_monitoring_records_is_success", "monitoring_records", ["is_success"]
    )

    op.create_table(
        "anomalies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("monitor_id", sa.Integer(), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("anomaly_type", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["record_id"], ["monitoring_records.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_anomalies_monitor_id", "anomalies", ["monitor_id"])
    op.create_index("ix_anomalies_record_id", "anomalies", ["record_id"])
    op.create_index("ix_anomalies_anomaly_type", "anomalies", ["anomaly_type"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("monitor_id", sa.Integer(), nullable=False),
        sa.Column("anomaly_id", sa.Integer(), nullable=True),
        sa.Column("anomaly_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("possible_cause", sa.Text(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("ai_generated", sa.Boolean(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["anomaly_id"], ["anomalies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alerts_monitor_id", "alerts", ["monitor_id"])
    op.create_index("ix_alerts_anomaly_type", "alerts", ["anomaly_type"])
    op.create_index("ix_alerts_severity", "alerts", ["severity"])
    op.create_index("ix_alerts_status", "alerts", ["status"])

    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("default_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("default_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("default_latency_threshold_ms", sa.Integer(), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_index("ix_alerts_status", table_name="alerts")
    op.drop_index("ix_alerts_severity", table_name="alerts")
    op.drop_index("ix_alerts_anomaly_type", table_name="alerts")
    op.drop_index("ix_alerts_monitor_id", table_name="alerts")
    op.drop_table("alerts")
    op.drop_index("ix_anomalies_anomaly_type", table_name="anomalies")
    op.drop_index("ix_anomalies_record_id", table_name="anomalies")
    op.drop_index("ix_anomalies_monitor_id", table_name="anomalies")
    op.drop_table("anomalies")
    op.drop_index("ix_monitoring_records_is_success", table_name="monitoring_records")
    op.drop_index("ix_monitoring_records_checked_at", table_name="monitoring_records")
    op.drop_index("ix_monitoring_records_monitor_id", table_name="monitoring_records")
    op.drop_table("monitoring_records")
    op.drop_index("ix_monitors_last_status", table_name="monitors")
    op.drop_index("ix_monitors_is_active", table_name="monitors")
    op.drop_table("monitors")
