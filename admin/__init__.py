"""
Admin blueprint – authentication, product management and order history.
"""
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint, render_template, request, session,
    redirect, url_for, flash, current_app,
)
from werkzeug.security import check_password_hash

from extensions import db, limiter
from helpers import admin_required
from helpers.image import allowed_file, save_product_image, delete_product_image
from helpers.orders import mark_paid, cancel_order
from models import User, Product, Order

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

PER_PAGE = 15


# ═════════════════════════════════════════════════════════════════════
#  AUTHENTICATION
# ═════════════════════════════════════════════════════════════════════

@admin_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if session.get("role") == "ADMIN":
        return redirect(url_for("admin.product_list"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        if user and user.role == "ADMIN" and check_password_hash(user.password_hash, password):
            token = session.get("_csrf_token")
            session.clear()  # prevent session fixation
            if token:
                session["_csrf_token"] = token
            session["user_id"] = user.id
            session["username"] = user.username
            session["role"] = user.role
            flash(f"Welcome back, {user.username}!", "success")
            nxt = request.args.get("next", "")
            if nxt.startswith("/admin") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(url_for("admin.product_list"))

        flash("Invalid username or password.", "danger")

    return render_template("admin/login.html")


@admin_bp.route("/logout", methods=["POST"])
def logout():
    for key in ("user_id", "username", "role"):
        session.pop(key, None)
    flash("You have been signed out.", "info")
    return redirect(url_for("admin.login"))


@admin_bp.route("/")
@admin_required
def dashboard():
    return redirect(url_for("admin.product_list"))


# ═════════════════════════════════════════════════════════════════════
#  PRODUCTS
# ═════════════════════════════════════════════════════════════════════

@admin_bp.route("/products")
@admin_required
def product_list():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "", type=str).strip()
    status = request.args.get("status", "", type=str).upper()

    query = Product.query
    if search:
        like = f"%{search}%"
        query = query.filter(db.or_(Product.name.ilike(like), Product.description.ilike(like)))
    if status in Product.STATUSES:
        query = query.filter(Product.status == status)

    pagination = query.order_by(Product.id.desc()).paginate(
        page=page, per_page=PER_PAGE, error_out=False)

    stats = {
        "total": Product.query.count(),
        "active": Product.query.filter_by(status=Product.STATUS_ACTIVE).count(),
        "out_of_stock": Product.query.filter(Product.stock <= 0).count(),
        "orders": Order.query.count(),
    }
    return render_template("admin/products.html", pagination=pagination,
                           search=search, status=status, stats=stats)


def _read_product_form():
    """Parse & validate the product form. Returns (data, errors)."""
    data = {
        "name": request.form.get("name", "").strip(),
        "description": request.form.get("description", "").strip(),
        "price": request.form.get("price", "").strip(),
        "stock": request.form.get("stock", "").strip(),
        "status": request.form.get("status", Product.STATUS_ACTIVE).upper(),
    }
    errors = {}

    if not data["name"]:
        errors["name"] = "Name is required."
    elif len(data["name"]) > 150:
        errors["name"] = "Name must be 150 characters or fewer."

    if len(data["description"]) > 5000:
        errors["description"] = "Description must be 5000 characters or fewer."

    try:
        price = Decimal(data["price"]).quantize(Decimal("0.01"))
        if price <= 0 or price > Decimal("99999999.99"):
            raise InvalidOperation
        data["price_value"] = price
    except (InvalidOperation, ValueError):
        errors["price"] = "Enter a valid price greater than 0."

    try:
        stock = int(data["stock"])
        if stock < 0 or stock > 1_000_000:
            raise ValueError
        data["stock_value"] = stock
    except ValueError:
        errors["stock"] = "Stock must be a whole number (0 or more)."

    if data["status"] not in Product.STATUSES:
        errors["status"] = "Invalid status."

    file = request.files.get("image")
    if file and file.filename and not allowed_file(file.filename):
        errors["image"] = "Invalid image type. Allowed: JPG, JPEG, JFIF, PNG, WEBP."

    return data, errors, file


def _store_image(product, file):
    """Process and attach a new image to the product, replacing any previous one."""
    cfg = current_app.config
    image, thumb, image_bytes, thumb_bytes = save_product_image(
        file, cfg["UPLOAD_FOLDER_PRODUCTS"], cfg["UPLOAD_FOLDER_THUMBNAILS"]
    )
    delete_product_image(product.image, product.thumbnail,
                         cfg["UPLOAD_FOLDER_PRODUCTS"], cfg["UPLOAD_FOLDER_THUMBNAILS"])
    product.image, product.thumbnail = image, thumb
    product.image_data, product.thumbnail_data = image_bytes, thumb_bytes


@admin_bp.route("/products/new", methods=["GET", "POST"])
@admin_required
def product_create():
    if request.method == "POST":
        data, errors, file = _read_product_form()
        product = Product(
            name=data["name"],
            description=data["description"],
            price=data.get("price_value", Decimal("0")),
            stock=data.get("stock_value", 0),
            status=data["status"],
        )
        if not errors and file and file.filename:
            try:
                _store_image(product, file)
            except ValueError as exc:
                errors["image"] = str(exc)

        if errors:
            flash("Please correct the highlighted fields.", "danger")
            return render_template("admin/product_form.html", mode="create",
                                   product=None, form=data, errors=errors)

        db.session.add(product)
        db.session.commit()
        flash(f"Product “{product.name}” was created.", "success")
        return redirect(url_for("admin.product_list"))

    return render_template("admin/product_form.html", mode="create", product=None,
                           form={"status": Product.STATUS_ACTIVE, "stock": "0"}, errors={})


@admin_bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def product_edit(product_id):
    product = db.get_or_404(Product, product_id)

    if request.method == "POST":
        data, errors, file = _read_product_form()
        if not errors and file and file.filename:
            try:
                _store_image(product, file)
            except ValueError as exc:
                errors["image"] = str(exc)

        if errors:
            flash("Please correct the highlighted fields.", "danger")
            return render_template("admin/product_form.html", mode="edit",
                                   product=product, form=data, errors=errors)

        if request.form.get("remove_image") and not (file and file.filename):
            cfg = current_app.config
            delete_product_image(product.image, product.thumbnail,
                                 cfg["UPLOAD_FOLDER_PRODUCTS"], cfg["UPLOAD_FOLDER_THUMBNAILS"])
            product.image = product.thumbnail = None
            product.image_data = product.thumbnail_data = None

        product.name = data["name"]
        product.description = data["description"]
        product.price = data["price_value"]
        product.stock = data["stock_value"]
        product.status = data["status"]
        db.session.commit()
        flash(f"Product “{product.name}” was updated.", "success")
        return redirect(url_for("admin.product_list"))

    form = {
        "name": product.name,
        "description": product.description,
        "price": f"{product.price:.2f}",
        "stock": str(product.stock),
        "status": product.status,
    }
    return render_template("admin/product_form.html", mode="edit",
                           product=product, form=form, errors={})


@admin_bp.route("/products/<int:product_id>/delete", methods=["POST"])
@admin_required
def product_delete(product_id):
    product = db.get_or_404(Product, product_id)
    name = product.name
    image, thumb = product.image, product.thumbnail

    db.session.delete(product)  # order items keep their snapshot (product_id -> NULL)
    db.session.commit()

    cfg = current_app.config
    delete_product_image(image, thumb, cfg["UPLOAD_FOLDER_PRODUCTS"], cfg["UPLOAD_FOLDER_THUMBNAILS"])
    flash(f"Product “{name}” was deleted.", "success")
    return redirect(url_for("admin.product_list"))


# ═════════════════════════════════════════════════════════════════════
#  ORDERS
# ═════════════════════════════════════════════════════════════════════

@admin_bp.route("/orders")
@admin_required
def order_list():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "", type=str).strip()
    status = request.args.get("status", "", type=str).upper()

    query = Order.query
    if search:
        like = f"%{search}%"
        conditions = [Order.customer_name.ilike(like), Order.customer_phone.ilike(like),
                      Order.customer_email.ilike(like)]
        digits = search.upper().replace("ORD-", "").lstrip("0")
        if digits.isdigit():
            conditions.append(Order.id == int(digits))
        query = query.filter(db.or_(*conditions))
    if status in Order.STATUSES:
        query = query.filter(Order.status == status)

    pagination = query.order_by(Order.created_at.desc(), Order.id.desc()).paginate(
        page=page, per_page=PER_PAGE, error_out=False)

    paid_total = db.session.query(db.func.coalesce(db.func.sum(Order.total_amount), 0)) \
        .filter(Order.status == Order.STATUS_PAID).scalar()
    stats = {
        "total": Order.query.count(),
        "paid": Order.query.filter_by(status=Order.STATUS_PAID).count(),
        "pending": Order.query.filter_by(status=Order.STATUS_PENDING).count(),
        "revenue": paid_total,
    }
    return render_template("admin/orders.html", pagination=pagination,
                           search=search, status=status, stats=stats)


@admin_bp.route("/orders/<int:order_id>")
@admin_required
def order_detail(order_id):
    order = db.get_or_404(Order, order_id)
    return render_template("admin/order_detail.html", order=order)


@admin_bp.route("/orders/<int:order_id>/mark-paid", methods=["POST"])
@admin_required
def order_mark_paid(order_id):
    order = db.get_or_404(Order, order_id)
    if mark_paid(order, reference=f"Confirmed manually by {session.get('username')}"):
        flash(f"Order {order.code} marked as paid.", "success")
    return redirect(url_for("admin.order_detail", order_id=order.id))


@admin_bp.route("/orders/<int:order_id>/cancel", methods=["POST"])
@admin_required
def order_cancel(order_id):
    order = db.get_or_404(Order, order_id)
    if cancel_order(order):
        flash(f"Order {order.code} cancelled and stock restored.", "info")
    return redirect(url_for("admin.order_detail", order_id=order.id))
