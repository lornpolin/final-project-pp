"""
Application configuration.

Values can be overridden with environment variables or a `.env` file
placed next to this file (see `.env.example`).
"""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

try:  # Load .env if python-dotenv is installed
    from dotenv import load_dotenv

    load_dotenv(os.path.join(BASE_DIR, ".env"))
except ImportError:  # pragma: no cover
    pass


def _bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _database_url():
    url = os.environ.get("DATABASE_URL", "sqlite:///shop.db").strip()
    # Neon/Heroku sometimes provide "postgres://", which SQLAlchemy 2.x rejects.
    if url.startswith("postgres://"):   
        url = "postgresql://" + url[len("postgres://"):]
    return url


_DB_URL = _database_url()


class Config:
    # ── Core ─────────────────────────────────────────────────────────
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    SQLALCHEMY_DATABASE_URI = _DB_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Neon suspends idle computes; pre-ping and recycle prevent stale connections.
    SQLALCHEMY_ENGINE_OPTIONS = (
        {} if _DB_URL.startswith("sqlite") else {"pool_pre_ping": True, "pool_recycle": 300}
    )
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB upload limit

    # ── Shop ─────────────────────────────────────────────────────────
    SHOP_NAME = os.environ.get("SHOP_NAME", "PP Shop")
    CURRENCY = os.environ.get("CURRENCY", "USD").upper()  # USD | KHR
    DISPLAY_UTC_OFFSET_HOURS = int(os.environ.get("DISPLAY_UTC_OFFSET_HOURS", "7"))  # Asia/Phnom_Penh

    # ── Initial Admin Seed (only used when creating the first admin) ──
    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@123")

    # ── Uploads / Cloudinary ─────────────────────────────────────────
    UPLOAD_FOLDER_PRODUCTS = os.path.join(BASE_DIR, "uploads", "products")
    UPLOAD_FOLDER_THUMBNAILS = os.path.join(BASE_DIR, "uploads", "products", "thumbs")
    CLOUDINARY_URL = os.environ.get("CLOUDINARY_URL", "").strip()
    CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "").strip()
    CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY", "").strip()
    CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "").strip()
    CLOUDINARY_FOLDER = os.environ.get("CLOUDINARY_FOLDER", "pp_shop/products").strip()

    # ── KHQR / Bakong ────────────────────────────────────────────────
    # Your Bakong account ID, e.g. "your_name@aclb" (shown in the Bakong app).
    BAKONG_ACCOUNT_ID = os.environ.get("BAKONG_ACCOUNT_ID", "ppshop@aclb")
    KHQR_MERCHANT_NAME = os.environ.get("KHQR_MERCHANT_NAME", SHOP_NAME)
    KHQR_MERCHANT_CITY = os.environ.get("KHQR_MERCHANT_CITY", "Phnom Penh")
    KHQR_ACQUIRING_BANK = os.environ.get("KHQR_ACQUIRING_BANK", "")
    KHQR_MOBILE_NUMBER = os.environ.get("KHQR_MOBILE_NUMBER", "")
    KHQR_EXPIRE_MINUTES = int(os.environ.get("KHQR_EXPIRE_MINUTES", "15"))

    # Optional: Bakong Open API token (https://api-bakong.nbc.gov.kh) used to
    # verify payments automatically. When empty, the app runs in DEMO mode and
    # shows a "simulate payment" button instead.
    BAKONG_API_TOKEN = os.environ.get("BAKONG_API_TOKEN", "")
    BAKONG_API_URL = os.environ.get("BAKONG_API_URL", "https://api-bakong.nbc.gov.kh")
    KHQR_DEMO_MODE = _bool("KHQR_DEMO_MODE", default=not bool(BAKONG_API_TOKEN))
