"""Importing this package registers every model with Base.metadata."""
from app.models.alert import Alert
from app.models.anomaly import Anomaly
from app.models.monitor import Monitor
from app.models.monitoring_record import MonitoringRecord
from app.models.settings import AppSettings
from app.models.user import User

__all__ = ["Alert", "Anomaly", "AppSettings", "Monitor", "MonitoringRecord", "User"]
