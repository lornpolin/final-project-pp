"""
Flask extensions – database and rate limiter.
"""
import warnings

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy

# SQLite stores DECIMAL as text/float; values are always quantized to 2 places
# in the models, so the generic SQLAlchemy warning is not relevant here.
warnings.filterwarnings("ignore", message=r".*does \*not\* support Decimal objects natively.*")

db = SQLAlchemy()

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri="memory://",
)
