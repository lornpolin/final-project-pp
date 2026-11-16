"""
Front (customer) blueprint – storefront, cart, checkout and KHQR payment.
"""
import re

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, abort, jsonify, current_app, session,
)

from extensions import db
from helpers import cart as cart_svc
from helpers.khqr import check_payment, qr_png_data_uri
from helpers.orders import (
    OutOfStockError, create_order, attach_khqr, mark_paid, cancel_order, amount_matches,
)
from models import Product, Order

front_bp = Blueprint("front", __name__)

PER_PAGE = 12
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^\+?[0-9][0-9\s\-]{6,18}[0-9]$")


def _safe_next(default):
    """Only allow redirecting back to a local path."""
    target = request.form.get("next") or request.args.get("next") or ""
    if target.startswith("/") and not target.startswith("//"):
        return target
    return default


def _active_product_or_404(product_id):
    product = db.session.get(Product, product_id)
    if product is None or not product.is_active:
        abort(404)
    return product


# ═════════════════════════════════════════════════════════════════════
#  HOME & PRODUCT DETAIL
# ═════════════════════════════════════════════════════════════════════

@front_bp.route("/")
def home():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "", type=str).strip()
    sort = request.args.get("sort", "newest")

    query = Product.query.filter(Product.status == Product.STATUS_ACTIVE)
    if search:
        like = f"%{search}%"
        query = query.filter(db.or_(Product.name.ilike(like), Product.description.ilike(like)))

    order_by = {
        "price_asc": Product.price.asc(),
        "price_desc": Product.price.desc(),
        "name": Product.name.asc(),
    }.get(sort, Product.created_at.desc())

    pagination = query.order_by(order_by, Product.id.desc()).paginate(
        page=page, per_page=PER_PAGE, error_out=False)
    return render_template("shop/home.html", pagination=pagination, search=search, sort=sort)


@front_bp.route("/product/<int:product_id>")
def product_detail(product_id):
    product = _active_product_or_404(product_id)
    related = (
        Product.query.filter(Product.status == Product.STATUS_ACTIVE, Product.id != product.id)
        .order_by(db.func.random()).limit(4).all()
    )
    share_url = url_for("front.product_detail", product_id=product.id, _external=True)
    return render_template(
        "shop/product_detail.html",
        product=product,
        related=related,
        share_url=share_url,
        in_cart=cart_svc.get_quantity(product.id),
    )


# ═════════════════════════════════════════════════════════════════════
#  CART
# ═════════════════════════════════════════════════════════════════════

@front_bp.route("/cart")
def cart():
    items, total, notices = cart_svc.get_details()
    for msg in dict.fromkeys(notices):
        flash(msg, "warning")
    return render_template("shop/cart.html", items=items, total=total)


@front_bp.route("/cart/add/<int:product_id>", methods=["POST"])
def cart_add(product_id):
    product = _active_product_or_404(product_id)
    qty = max(request.form.get("quantity", 1, type=int) or 1, 1)

    if not product.in_stock:
        flash(f"Sorry, “{product.name}” is out of stock.", "danger")
        return redirect(_safe_next(url_for("front.product_detail", product_id=product.id)))

    before = cart_svc.get_quantity(product.id)
    after = cart_svc.add_item(product, qty)
    if after - before < qty:
        flash(f"Only {product.stock} of “{product.name}” available — your cart now has {after}.", "warning")
    else:
        flash(f"Added {qty} × “{product.name}” to your cart.", "success")
    return redirect(_safe_next(url_for("front.cart")))


@front_bp.route("/cart/update/<int:product_id>", methods=["POST"])
def cart_update(product_id):
    product = db.session.get(Product, product_id)
    if product is None:
        cart_svc.remove_item(product_id)
        return redirect(url_for("front.cart"))

    qty = request.form.get("quantity", 1, type=int)
    if qty is None:
        flash("Please enter a valid quantity.", "danger")
        return redirect(url_for("front.cart"))

    new_qty = cart_svc.set_quantity(product, qty)
    if new_qty == 0:
        flash(f"Removed “{product.name}” from your cart.", "info")
    elif new_qty < qty:
        flash(f"Only {product.stock} of “{product.name}” available.", "warning")
    else:
        flash("Cart updated.", "success")
    return redirect(url_for("front.cart"))


@front_bp.route("/cart/remove/<int:product_id>", methods=["POST"])
def cart_remove(product_id):
    cart_svc.remove_item(product_id)
    flash("Item removed from your cart.", "info")
    return redirect(url_for("front.cart"))


# ═════════════════════════════════════════════════════════════════════
#  CHECKOUT
# ═════════════════════════════════════════════════════════════════════

@front_bp.route("/checkout", methods=["GET", "POST"])
def checkout():
    items, total, notices = cart_svc.get_details()
    for msg in dict.fromkeys(notices):
        flash(msg, "warning")
    if not items:
        flash("Your cart is empty.", "info")
        return redirect(url_for("front.cart"))

    form = {
        "name": request.form.get("name", "").strip(),
        "email": request.form.get("email", "").strip(),
        "phone": request.form.get("phone", "").strip(),
        "address": request.form.get("address", "").strip(),
    }
    errors = {}

    if request.method == "POST":
        if notices:  # cart changed since the customer last saw it
            return render_template("shop/checkout.html", items=items, total=total, form=form, errors=errors)

        if not 2 <= len(form["name"]) <= 120:
            errors["name"] = "Please enter your full name."
        if not EMAIL_RE.match(form["email"]) or len(form["email"]) > 120:
            errors["email"] = "Please enter a valid email address."
        if not PHONE_RE.match(form["phone"]):
            errors["phone"] = "Please enter a valid phone number (e.g. 012 345 678)."
        if not 5 <= len(form["address"]) <= 500:
            errors["address"] = "Please enter your full shipping address."

        if not errors:
            try:
                order = create_order(form, items, total)
            except OutOfStockError as exc:
                flash(str(exc), "danger")
                return redirect(url_for("front.cart"))
            except ValueError as exc:  # KHQR configuration problem
                current_app.logger.exception("KHQR generation failed")
                flash(f"Payment is temporarily unavailable: {exc}", "danger")
                return redirect(url_for("front.cart"))

            cart_svc.clear()
            session.setdefault("my_orders", [])
            session["my_orders"] = (session["my_orders"] + [order.public_id])[-20:]
            return redirect(url_for("front.payment", public_id=order.public_id))

        flash("Please correct the highlighted fields.", "danger")

    return render_template("shop/checkout.html", items=items, total=total, form=form, errors=errors)


def _order_or_404(public_id):
    order = Order.query.filter_by(public_id=public_id).first()
    if order is None:
        abort(404)
    return order


@front_bp.route("/checkout/pay/<public_id>")
def payment(public_id):
    order = _order_or_404(public_id)
    if order.is_paid:
        return redirect(url_for("front.order_confirmation", public_id=order.public_id))
    if order.status == Order.STATUS_CANCELLED:
        flash("This order was cancelled.", "warning")
        return redirect(url_for("front.home"))

    return render_template(
        "shop/payment.html",
        order=order,
        qr_image=qr_png_data_uri(order.khqr_string),
        demo_mode=current_app.config["KHQR_DEMO_MODE"],
    )


@front_bp.route("/checkout/pay/<public_id>/status")
def payment_status(public_id):
    """Polled by the payment page. Verifies with Bakong when configured."""
    order = _order_or_404(public_id)
    cfg = current_app.config

    if order.is_pending and cfg["BAKONG_API_TOKEN"] and order.khqr_md5:
        try:
            data = check_payment(order.khqr_md5, token=cfg["BAKONG_API_TOKEN"],
                                 api_url=cfg["BAKONG_API_URL"])
            if data and amount_matches(order, data):
                mark_paid(order, reference=data.get("hash") or data.get("externalRef"))
        except RuntimeError as exc:
            current_app.logger.warning("Bakong check failed: %s", exc)

    return jsonify({
        "status": order.status,
        "expired": order.khqr_expired,
        "redirect": url_for("front.order_confirmation", public_id=order.public_id)
        if order.is_paid else None,
    })


@front_bp.route("/checkout/pay/<public_id>/regenerate", methods=["POST"])
def payment_regenerate(public_id):
    order = _order_or_404(public_id)
    if order.is_pending:
        attach_khqr(order)
        db.session.commit()
        flash("A new KHQR code has been generated.", "info")
    return redirect(url_for("front.payment", public_id=order.public_id))


@front_bp.route("/checkout/pay/<public_id>/simulate", methods=["POST"])
def payment_simulate(public_id):
    """DEMO MODE ONLY – marks the order as paid without contacting Bakong."""
    if not current_app.config["KHQR_DEMO_MODE"]:
        abort(404)
    order = _order_or_404(public_id)
    mark_paid(order, reference="DEMO-PAYMENT")
    return redirect(url_for("front.order_confirmation", public_id=order.public_id))


@front_bp.route("/checkout/pay/<public_id>/cancel", methods=["POST"])
def payment_cancel(public_id):
    order = _order_or_404(public_id)
    if cancel_order(order):
        flash(f"Order {order.code} was cancelled.", "info")
    return redirect(url_for("front.home"))


# ═════════════════════════════════════════════════════════════════════
#  ORDER CONFIRMATION
# ═════════════════════════════════════════════════════════════════════

@front_bp.route("/order/<public_id>")
def order_confirmation(public_id):
    order = _order_or_404(public_id)
    if order.is_pending:
        return redirect(url_for("front.payment", public_id=order.public_id))
    if order.status == Order.STATUS_CANCELLED:
        abort(404)
    return render_template("shop/order_confirmation.html", order=order)
