"""
PP Shop – mini e-commerce application (Flask).

Run locally:   python app.py
Run on Render: gunicorn wsgi:app
"""
import os
from datetime import datetime
from decimal import Decimal

from flask import Flask, send_from_directory
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

    # ── Serve uploaded product images
    @app.route("/uploads/products/<path:filename>")
    def product_image(filename):
        return send_from_directory(app.config["UPLOAD_FOLDER_PRODUCTS"], filename)

    @app.route("/uploads/products/thumbs/<path:filename>")
    def product_thumbnail(filename):
        return send_from_directory(app.config["UPLOAD_FOLDER_THUMBNAILS"], filename)

    # ── Create tables & seed data
    with app.app_context():
        import models  # noqa: F401 – registers all models with SQLAlchemy

        db.create_all()
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
            image, thumb = create_placeholder_image(
                name, colors,
                app.config["UPLOAD_FOLDER_PRODUCTS"], app.config["UPLOAD_FOLDER_THUMBNAILS"])
            db.session.add(Product(
                name=name, description=description, price=Decimal(price),
                stock=stock, image=image, thumbnail=thumb, status=Product.STATUS_ACTIVE,
            ))
        db.session.commit()


if __name__ == "__main__":
    create_app().run(debug=True, host="127.0.0.1", port=5000)
