"""Dashboard — FastAPI/WebSocket backend and single-page frontend.

Exists to render bus events and issue commands back onto the bus; it contains
zero physics or business logic by charter.
"""

from catsim.dashboard.app import create_app
from catsim.dashboard.config import DashboardConfig, load_dashboard_config
from catsim.dashboard.hub import EventHub

__all__ = ["DashboardConfig", "EventHub", "create_app", "load_dashboard_config"]
