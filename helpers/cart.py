"""
Session-based shopping cart.

The cart is stored in the Flask session as ``{"<product_id>": quantity}``.
"""
from decimal import Decimal

from flask import session

from extensions import db
from models import Product

CART_KEY = "cart"
MAX_QTY_PER_ITEM = 99


def _raw():
    return session.get(CART_KEY, {})


def _save(cart):
    session[CART_KEY] = cart
    session.modified = True


def cart_count():
    return sum(_raw().values())


def get_quantity(product_id):
    return _raw().get(str(product_id), 0)


def add_item(product, qty=1):
    """Add ``qty`` of a product. Returns the quantity actually in the cart."""
    cart = _raw()
    key = str(product.id)
    new_qty = min(cart.get(key, 0) + max(qty, 1), product.stock, MAX_QTY_PER_ITEM)
    if new_qty <= 0:
        cart.pop(key, None)
    else:
        cart[key] = new_qty
    _save(cart)
    return new_qty


def set_quantity(product, qty):
    cart = _raw()
    key = str(product.id)
    qty = min(max(qty, 0), product.stock, MAX_QTY_PER_ITEM)
    if qty <= 0:
        cart.pop(key, None)
    else:
        cart[key] = qty
    _save(cart)
    return qty


def remove_item(product_id):
    cart = _raw()
    cart.pop(str(product_id), None)
    _save(cart)


def clear():
    session.pop(CART_KEY, None)


def get_details():
    """
    Resolve the cart into product rows.

    Removes products that no longer exist / are inactive and clamps
    quantities to available stock. Returns ``(items, total, notices)``.
    """
    cart = _raw()
    if not cart:
        return [], Decimal("0.00"), []

    ids = [int(pid) for pid in cart.keys() if pid.isdigit()]
    products = {p.id: p for p in db.session.query(Product).filter(Product.id.in_(ids)).all()}

    items, notices, changed = [], [], False
    total = Decimal("0.00")
    for pid_str, qty in list(cart.items()):
        product = products.get(int(pid_str)) if pid_str.isdigit() else None
        if product is None or not product.is_active:
            notices.append("An item in your cart is no longer available and was removed.")
            cart.pop(pid_str, None)
            changed = True
            continue
        if product.stock <= 0:
            notices.append(f"“{product.name}” is out of stock and was removed from your cart.")
            cart.pop(pid_str, None)
            changed = True
            continue
        if qty > product.stock:
            notices.append(f"Only {product.stock} of “{product.name}” available — quantity adjusted.")
            qty = product.stock
            cart[pid_str] = qty
            changed = True

        subtotal = (Decimal(product.price) * qty).quantize(Decimal("0.01"))
        total += subtotal
        items.append({"product": product, "quantity": qty, "subtotal": subtotal})

    if changed:
        _save(cart)
    return items, total.quantize(Decimal("0.01")), notices
