from .admin import admin_bp
from .api import api_bp
from .auth import auth_bp
from .events import events_bp
from .payments import payments_bp
from .student import student_bp

__all__ = [
    "admin_bp",
    "api_bp",
    "auth_bp",
    "events_bp",
    "payments_bp",
    "student_bp",
]
