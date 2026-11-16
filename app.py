"""
PP Shop – mini e-commerce application (Flask).

Run locally:   python app.py
Run on Render: gunicorn wsgi:app
"""
import io
import os
from datetime import datetime
from decimal import Decimal

from flask import Flask, send_file, send_from_directory
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash

from config import Config
from extensions import db, limiter


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)

    # Respect X-Forwarded-* headers behind Render's reverse proxy (HTTPS & client IP)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    os.makedirs(app.config["UPLOAD_FOLDER_PRODUCTS"], exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER_THUMBNAILS"], exist_ok=True)

    # ── Extensions
    db.init_app(app)
    limiter.init_app(app)

    # ── Blueprints
    from front import front_bp
    from admin import admin_bp

    app.register_blueprint(front_bp)
    app.register_blueprint(admin_bp)

    # ── Helpers: CSRF, filters, error pages
    from helpers import register_csrf, register_error_handlers, register_template_filters

    register_csrf(app)
    register_template_filters(app)
    register_error_handlers(app)

    @app.context_processor
    def inject_globals():
        from helpers.cart import cart_count

        return {
            "shop_name": app.config["SHOP_NAME"],
            "cart_count": cart_count(),
            "current_year": datetime.now().year,
        }

    # ── Health check for Render ──────────────────────────────────────
    @app.route("/healthz")
    def healthz():
        return {"status": "ok"}, 200

    # ── Serve uploaded product images (DB first, local disk fallback)
    @app.route("/uploads/products/<path:filename>")
    def product_image(filename):
        from models import Product

        product = Product.query.filter_by(image=filename).first()
        if product and product.image_data:
            return send_file(io.BytesIO(product.image_data), mimetype="image/jpeg", max_age=86400)
        return send_from_directory(app.config["UPLOAD_FOLDER_PRODUCTS"], filename)

    @app.route("/uploads/products/thumbs/<path:filename>")
    def product_thumbnail(filename):
        from models import Product

        product = Product.query.filter_by(thumbnail=filename).first()
        if product and product.thumbnail_data:
            return send_file(io.BytesIO(product.thumbnail_data), mimetype="image/jpeg", max_age=86400)
        return send_from_directory(app.config["UPLOAD_FOLDER_THUMBNAILS"], filename)

    # ── Create tables & seed data
    with app.app_context():
        import models  # noqa: F401 – registers all models with SQLAlchemy

        db.create_all()
        _ensure_product_image_columns()
        _backfill_db_images(app)
        _seed_data(app)

    return app


SEED_PRODUCTS = [
    ("Wireless Headphones", "49.99", 25, ((40, 44, 52), (90, 100, 120)),
     "Over-ear Bluetooth 5.3 headphones with active noise cancellation, 40-hour battery "
     "life, fast USB-C charging and soft memory-foam ear cushions for all-day comfort."),
    ("Smart Watch", "89.00", 12, ((46, 125, 96), (120, 190, 160)),
     "Track your steps, heart rate, sleep and workouts. AMOLED display, 7-day battery, "
     "water resistant to 50 m and notifications from your phone."),
    ("Ceramic Coffee Mug", "12.50", 60, ((191, 90, 54), (236, 160, 110)),
     "Handmade 350 ml ceramic mug with a terracotta glaze. Microwave and dishwasher safe. "
     "Perfect for your morning Cambodian iced coffee — or a hot one."),
    ("Canvas Backpack", "35.00", 18, ((85, 107, 47), (150, 170, 100)),
     "Minimalist 20 L canvas backpack with leather straps, padded 15\" laptop sleeve, "
     "water-resistant lining and a hidden anti-theft pocket."),
    ("White Leather Sneakers", "59.90", 4, ((120, 130, 150), (200, 205, 215)),
     "Clean, everyday sneakers made from genuine leather with a cushioned insole and "
     "durable rubber outsole. Goes with everything."),
    ("Brass Desk Lamp", "42.00", 0, ((180, 140, 60), (230, 200, 130)),
     "Adjustable desk lamp in brushed brass and matte white with a warm LED bulb "
     "(included) and three brightness levels."),
    ("Kampot Pepper Gift Box", "15.00", 40, ((60, 30, 30), (150, 70, 60)),
     "Premium PGI Kampot pepper set — black, red and white peppercorns in a handcrafted "
     "palm-leaf gift box. A taste of Cambodia."),
    ("Krama Scarf", "8.00", 100, ((160, 30, 50), (220, 90, 110)),
     "Traditional Cambodian checked krama woven from soft cotton. Use it as a scarf, "
     "headband, towel or picnic cloth."),
]


def _ensure_product_image_columns():
    """Add BLOB/BYTEA columns to an existing product table if missing."""
    cols = {c["name"] for c in inspect(db.engine).get_columns("product")}
    col_type = "BLOB" if db.engine.dialect.name == "sqlite" else "BYTEA"
    changed = False
    for col in ("image_data", "thumbnail_data"):
        if col not in cols:
            db.session.execute(text(f"ALTER TABLE product ADD COLUMN {col} {col_type}"))
            changed = True
    if changed:
        db.session.commit()


def _backfill_db_images(app):
    """Copy any existing local disk product images into the database."""
    from models import Product

    products = Product.query.filter(
        db.or_(
            db.and_(Product.image.isnot(None), Product.image_data.is_(None)),
            db.and_(Product.thumbnail.isnot(None), Product.thumbnail_data.is_(None)),
        )
    ).all()
    changed = False
    for p in products:
        if p.image and not p.image.startswith(("http://", "https://")) and p.image_data is None:
            path = os.path.join(app.config["UPLOAD_FOLDER_PRODUCTS"], p.image)
            if os.path.isfile(path):
                with open(path, "rb") as fh:
                    p.image_data = fh.read()
                changed = True
        if p.thumbnail and not p.thumbnail.startswith(("http://", "https://")) and p.thumbnail_data is None:
            path = os.path.join(app.config["UPLOAD_FOLDER_THUMBNAILS"], p.thumbnail)
            if os.path.isfile(path):
                with open(path, "rb") as fh:
                    p.thumbnail_data = fh.read()
                changed = True
    if changed:
        db.session.commit()


def _seed_data(app):
    from models import User, Product
    from helpers.image import create_placeholder_image

    admin_username = app.config.get("ADMIN_USERNAME", "admin")
    if not User.query.filter_by(username=admin_username).first():
        db.session.add(User(
            username=admin_username,
            email=app.config.get("ADMIN_EMAIL", "admin@example.com"),
            password_hash=generate_password_hash(app.config.get("ADMIN_PASSWORD", "Admin@123")),
            role="ADMIN",
        ))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()

    if Product.query.count() == 0:
        for name, price, stock, colors, description in SEED_PRODUCTS:
            image, thumb, image_bytes, thumb_bytes = create_placeholder_image(
                name, colors,
                app.config["UPLOAD_FOLDER_PRODUCTS"], app.config["UPLOAD_FOLDER_THUMBNAILS"])
            db.session.add(Product(
                name=name, description=description, price=Decimal(price),
                stock=stock, image=image, thumbnail=thumb,
                image_data=image_bytes, thumbnail_data=thumb_bytes,
                status=Product.STATUS_ACTIVE,
            ))
        db.session.commit()


if __name__ == "__main__":
    create_app().run(debug=True, host="127.0.0.1", port=5000)
elif os.environ.get("SKIP_APP_FACTORY") != "1":
    # Expose `app` at module level so Render's default `gunicorn app:app` works.
    app = create_app()
