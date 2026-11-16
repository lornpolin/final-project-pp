"""
Database model – Product
"""
from datetime import datetime, timezone

from extensions import db

LOW_STOCK_THRESHOLD = 5


class Product(db.Model):
    __tablename__ = "product"

    STATUS_ACTIVE = "ACTIVE"
    STATUS_INACTIVE = "INACTIVE"
    STATUSES = (STATUS_ACTIVE, STATUS_INACTIVE)

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    price = db.Column(db.Numeric(10, 2), nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    image = db.Column(db.String(512))            # local filename or Cloudinary URL
    thumbnail = db.Column(db.String(512))        # local filename or Cloudinary URL
    status = db.Column(db.String(10), nullable=False, default=STATUS_ACTIVE, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # On delete, the ORM sets OrderItem.product_id to NULL; the item keeps its
    # name/price snapshot so order history is preserved.
    order_items = db.relationship("OrderItem", back_populates="product")

    # ── Helpers ──────────────────────────────────────────────────────
    @property
    def is_active(self):
        return self.status == self.STATUS_ACTIVE

    @property
    def in_stock(self):
        return self.stock > 0

    @property
    def is_available(self):
        """Can a customer buy this product right now?"""
        return self.is_active and self.in_stock

    @property
    def stock_status(self):
        """Return a (label, css-class) tuple for display."""
        if self.stock <= 0:
            return "Out of stock", "danger"
        if self.stock <= LOW_STOCK_THRESHOLD:
            return f"Only {self.stock} left", "warning"
        return "In stock", "success"

    @property
    def short_description(self):
        text = (self.description or "").strip()
        return text if len(text) <= 110 else text[:107].rsplit(" ", 1)[0] + "…"

    def __repr__(self):
        return f"<Product {self.id} {self.name}>"
