"""
Database models â€“ Order and OrderItem
"""
import uuid
from datetime import datetime, timezone

from extensions import db


def _utcnow():
    return datetime.now(timezone.utc)


class Order(db.Model):
    __tablename__ = "orders"

    STATUS_PENDING = "PENDING"      # waiting for KHQR payment
    STATUS_PAID = "PAID"            # payment received / confirmed
    STATUS_CANCELLED = "CANCELLED"  # cancelled by customer or admin
    STATUSES = (STATUS_PENDING, STATUS_PAID, STATUS_CANCELLED)

    id = db.Column(db.Integer, primary_key=True)
    # Unguessable identifier used in public (guest) URLs
    public_id = db.Column(db.String(32), unique=True, nullable=False,
                          default=lambda: uuid.uuid4().hex, index=True)

    # Guest customer information
    customer_name = db.Column(db.String(120), nullable=False)
    customer_email = db.Column(db.String(120), nullable=False)
    customer_phone = db.Column(db.String(30), nullable=False)
    shipping_address = db.Column(db.Text, nullable=False)

    total_amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="USD")
    status = db.Column(db.String(10), nullable=False, default=STATUS_PENDING, index=True)

    # KHQR payment data
    khqr_string = db.Column(db.Text)
    khqr_md5 = db.Column(db.String(32), index=True)
    khqr_expires_at = db.Column(db.DateTime)
    payment_reference = db.Column(db.String(120))  # Bakong hash / note

    created_at = db.Column(db.DateTime, default=_utcnow, index=True)
    paid_at = db.Column(db.DateTime)

    items = db.relationship("OrderItem", back_populates="order",
                            cascade="all, delete-orphan", lazy="selectin")

    @property
    def code(self):
        """Human-friendly order number, e.g. ORD-000042."""
        return f"ORD-{self.id:06d}"

    @property
    def item_count(self):
        return sum(i.quantity for i in self.items)

    @property
    def is_paid(self):
        return self.status == self.STATUS_PAID

    @property
    def is_pending(self):
        return self.status == self.STATUS_PENDING

    def _expires_utc(self):
        expires = self.khqr_expires_at
        if expires is not None and expires.tzinfo is None:  # SQLite returns naive datetimes
            expires = expires.replace(tzinfo=timezone.utc)
        return expires

    @property
    def khqr_expired(self):
        expires = self._expires_utc()
        return expires is None or _utcnow() >= expires

    @property
    def khqr_expires_ms(self):
        """Expiry as a Unix timestamp in milliseconds (for the JS countdown)."""
        expires = self._expires_utc()
        return int(expires.timestamp() * 1000) if expires else 0

    @property
    def status_badge(self):
        return {
            self.STATUS_PAID: "success",
            self.STATUS_PENDING: "warning",
            self.STATUS_CANCELLED: "secondary",
        }.get(self.status, "secondary")

    def __repr__(self):
        return f"<Order {self.code} {self.status}>"


class OrderItem(db.Model):
    __tablename__ = "order_item"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id", ondelete="SET NULL"),
                           nullable=True)

    # Snapshot of the product at purchase time (survives product edits/deletes)
    product_name = db.Column(db.String(150), nullable=False)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    subtotal = db.Column(db.Numeric(12, 2), nullable=False)

    order = db.relationship("Order", back_populates="items")
    product = db.relationship("Product", back_populates="order_items")

    def __repr__(self):
        return f"<OrderItem {self.product_name} x{self.quantity}>"
