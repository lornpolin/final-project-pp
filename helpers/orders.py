"""
Order services shared by the shop and admin blueprints.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import current_app

from extensions import db
from helpers.khqr import generate_khqr
from models import Order, OrderItem, Product


class OutOfStockError(Exception):
    pass


def create_order(customer, cart_items, total):
    """
    Create a PENDING order from resolved cart items and reserve stock.

    Stock is decremented with a conditional UPDATE so two customers cannot
    buy the last unit at the same time. Raises ``OutOfStockError``.
    """
    order = Order(
        customer_name=customer["name"],
        customer_email=customer["email"],
        customer_phone=customer["phone"],
        shipping_address=customer["address"],
        total_amount=total,
        currency=current_app.config["CURRENCY"],
        status=Order.STATUS_PENDING,
    )
    try:
        for item in cart_items:
            product, qty = item["product"], item["quantity"]
            updated = (
                db.session.query(Product)
                .filter(Product.id == product.id,
                        Product.status == Product.STATUS_ACTIVE,
                        Product.stock >= qty)
                .update({Product.stock: Product.stock - qty}, synchronize_session=False)
            )
            if not updated:
                raise OutOfStockError(f"Sorry, “{product.name}” no longer has enough stock.")
            order.items.append(OrderItem(
                product_id=product.id,
                product_name=product.name,
                unit_price=product.price,
                quantity=qty,
                subtotal=item["subtotal"],
            ))
        db.session.add(order)
        db.session.flush()  # assigns order.id for the KHQR bill number
        attach_khqr(order)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return order


def attach_khqr(order):
    """Generate (or regenerate) the dynamic KHQR for an order."""
    cfg = current_app.config
    khqr = generate_khqr(
        bakong_account_id=cfg["BAKONG_ACCOUNT_ID"],
        merchant_name=cfg["KHQR_MERCHANT_NAME"],
        merchant_city=cfg["KHQR_MERCHANT_CITY"],
        acquiring_bank=cfg["KHQR_ACQUIRING_BANK"],
        mobile_number=cfg["KHQR_MOBILE_NUMBER"],
        amount=order.total_amount,
        currency=order.currency,
        bill_number=order.code,
        store_label=cfg["SHOP_NAME"],
        terminal_label="Online",
        expire_minutes=cfg["KHQR_EXPIRE_MINUTES"],
    )
    order.khqr_string = khqr["qr"]
    order.khqr_md5 = khqr["md5"]
    order.khqr_expires_at = datetime.now(timezone.utc) + timedelta(minutes=cfg["KHQR_EXPIRE_MINUTES"])
    return order


def mark_paid(order, reference=None):
    if order.status != Order.STATUS_PENDING:
        return False
    order.status = Order.STATUS_PAID
    order.paid_at = datetime.now(timezone.utc)
    order.payment_reference = (reference or "")[:120] or None
    db.session.commit()
    return True


def cancel_order(order):
    """Cancel a pending order and return its reserved stock."""
    if order.status != Order.STATUS_PENDING:
        return False
    for item in order.items:
        if item.product_id:
            db.session.query(Product).filter(Product.id == item.product_id).update(
                {Product.stock: Product.stock + item.quantity}, synchronize_session=False)
    order.status = Order.STATUS_CANCELLED
    db.session.commit()
    return True


def amount_matches(order, bakong_data):
    """Make sure the Bakong transaction matches the order total and currency."""
    try:
        paid = Decimal(str(bakong_data.get("amount")))
    except Exception:
        return False
    currency = str(bakong_data.get("currency", order.currency)).upper()
    return currency == order.currency and paid >= Decimal(order.total_amount)
