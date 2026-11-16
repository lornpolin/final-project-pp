# PP Shop – Mini E-Commerce with KHQR Payment

A mini e-commerce web application built with **Python / Flask**. Guests can browse
products, share them to Facebook and Telegram, manage a shopping cart and check out
by scanning a **Bakong KHQR** code. Administrators manage the product catalog and
view the order history.

---

## Features

### Customer (guest) pages
| Page | Route | What it does |
|------|-------|--------------|
| Home | `/` | Product grid (thumbnail, name, price, description) with search, sorting and pagination. **View Details** and **Add to Cart** actions. |
| Product detail | `/product/<id>` | Full description, price, stock status, large image, quantity selector + Add to Cart, **Share to Facebook / Telegram** (plus Copy link). Open Graph tags give rich link previews. |
| Cart | `/cart` | Items with quantity, unit price, subtotal and total. Update quantity (auto-submits) or remove items. **Proceed to Checkout**. |
| Checkout | `/checkout` | Guest form: full name, email, phone, shipping address (server-side validation). Places the order and reserves stock. |
| KHQR payment | `/checkout/pay/<public_id>` | Displays a dynamic **KHQR** code (amount + bill number embedded) in the official KHQR card style, a countdown and auto-refreshing payment status. |
| Order confirmation | `/order/<public_id>` | Success message and summary: Order ID, customer details, items and total amount. Printable. |

### Admin pages (login required)
| Page | Route | What it does |
|------|-------|--------------|
| Login | `/admin/login` | Admin sign-in (rate-limited: 5 POST / minute / IP). |
| Product list | `/admin/products` | Table with ID, image, name, price, stock, status (Active/Inactive); search & filter; **Add New Product / Edit / Delete**. |
| Product form | `/admin/products/new`, `/admin/products/<id>/edit` | Name, description, price, stock quantity, image (auto-thumbnail), status. |
| Order history | `/admin/orders` | Table with Order ID, customer name, phone, total amount, order date and status; search & filter. |
| Order details | `/admin/orders/<id>` | Purchased items, quantities, subtotals, total, shipping address, customer and payment info. Mark as paid / cancel pending orders. |

---

## Tech stack

Python 3.13 · Flask 3 · Flask-SQLAlchemy (SQLite) · Flask-Limiter · Pillow · qrcode ·
Jinja2 · Bootstrap 5 · vanilla JavaScript

---

## Getting started

```powershell
# 1. Create & activate a virtual environment
python -m venv .venv
.venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. (optional) configure – copy and edit the env file
copy .env.example .env

# 4. Run
python app.py            # or:  flask --app app run --debug
```

Open **http://127.0.0.1:5000**.

The SQLite database (`instance/shop.db`) is created automatically on first run and
seeded with 8 sample products (with generated placeholder images) and an admin account:

| Username | Password |
|----------|----------|
| `admin`  | `Admin@123` |

> ⚠️ Development credentials only – change the password and `SECRET_KEY` before deploying.

### Run the tests

```powershell
python -m unittest discover -s tests -v
```

---

## KHQR payment

`helpers/khqr.py` builds an EMVCo-compliant KHQR payload as defined by the National Bank
of Cambodia — no third-party KHQR library is required:

| Tag | Meaning | Example |
|-----|---------|---------|
| `00` | Payload format | `01` |
| `01` | Point of initiation | `12` (dynamic, has amount) |
| `29` | Individual account → `00` Bakong account ID | `ppshop@aclb` |
| `52` | Merchant category code | `5999` |
| `53` | Currency | `840` USD / `116` KHR |
| `54` | Amount | `99.98` |
| `58` / `59` / `60` | Country / merchant name / city | `KH` / `PP Shop` / `Phnom Penh` |
| `62` | Additional data → bill number (`ORD-000001`), store & terminal label | |
| `99` | Creation & expiration timestamps (ms) | |
| `63` | CRC-16/CCITT-FALSE checksum | |

The MD5 of the payload is stored with the order and is the key the Bakong Open API uses
to look up the transaction.

### Payment flow

```
Cart ─► Checkout form ─► Order saved (PENDING, stock reserved) ─► KHQR page
                                                                   │  polls /status every 4 s
                                                                   ▼
                                     Bakong API confirms (or demo button / admin) ─► PAID ─► Confirmation
```

* **Real verification** – set `BAKONG_ACCOUNT_ID` to your own Bakong account and
  `BAKONG_API_TOKEN` to a token from <https://api-bakong.nbc.gov.kh>. The status endpoint
  calls `POST /v1/check_transaction_by_md5`, checks the amount and currency, then marks
  the order **PAID**.
* **Demo mode** (default when no token is set) – the payment page shows a
  *Simulate successful payment* button so the whole flow can be tested without a bank.
  Admins can also confirm a payment manually with **Mark as paid**.
* QR codes expire after `KHQR_EXPIRE_MINUTES` (default 15); the customer can generate
  a new one. Cancelling a pending order returns its stock.

---

## Deploy to Render + Neon DB

1. **Create a Neon PostgreSQL database** at <https://neon.tech> and copy the connection string
   (it looks like `postgresql://user:password@ep-xxx.aws.neon.tech/neondb?sslmode=require`).
2. **Push this repository to GitHub.**
3. **Create a Web Service on Render** (<https://render.com>):
   - You can use the included [`render.yaml`](render.yaml) Blueprint, **or** configure manually:
     - **Build Command:** `pip install -r requirements.txt`
     - **Start Command:** `gunicorn wsgi:app --workers 1 --threads 4 --bind 0.0.0.0:$PORT`
4. **Set Environment Variables in Render:**
   - `DATABASE_URL` = your Neon connection string (`?sslmode=require`)
   - `SECRET_KEY` = a long random string
   - `ADMIN_PASSWORD` = a strong password for the initial `admin` user (created automatically on first boot)
   - `BAKONG_ACCOUNT_ID`, `KHQR_MERCHANT_NAME`, `KHQR_MERCHANT_CITY`, and optionally `BAKONG_API_TOKEN`

> **Note on product images:** Render's free tier uses an ephemeral filesystem, so images uploaded to
> `uploads/products/` will reset on redeploy/restart unless you attach a Render Persistent Disk or
> integrate external object storage (e.g. Cloudinary / S3).

---

## Configuration (`.env` or environment variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | dev key | Flask session secret |
| `SHOP_NAME` | `PP Shop` | Store name shown everywhere |
| `CURRENCY` | `USD` | `USD` or `KHR` |
| `BAKONG_ACCOUNT_ID` | `ppshop@aclb` | Bakong account that receives payments |
| `KHQR_MERCHANT_NAME` / `KHQR_MERCHANT_CITY` | shop name / Phnom Penh | Shown in banking apps |
| `KHQR_EXPIRE_MINUTES` | `15` | QR validity |
| `BAKONG_API_TOKEN` | *(empty)* | Enables automatic payment verification |
| `KHQR_DEMO_MODE` | `true` if no token | Show the simulate-payment button |
| `DATABASE_URL` | `sqlite:///shop.db` | SQLAlchemy database URL |

---

## Project structure

```
final-exam-project-pp/
├── app.py                 # Application factory, seed data, entry point
├── config.py              # Configuration (env / .env)
├── extensions.py          # SQLAlchemy & Flask-Limiter instances
├── models/
│   ├── product.py         # Product
│   ├── order.py           # Order, OrderItem (price/name snapshot)
│   └── user.py            # Admin user
├── front/__init__.py      # Customer blueprint: home, detail, cart, checkout, payment
├── admin/__init__.py      # Admin blueprint: login, products CRUD, order history
├── helpers/
│   ├── __init__.py        # admin_required, CSRF, template filters, error pages
│   ├── cart.py            # Session cart
│   ├── orders.py          # Create / pay / cancel orders, stock reservation
│   ├── khqr.py            # KHQR generator, QR rendering, Bakong API check
│   └── image.py           # Upload validation, resize, thumbnails, placeholders
├── templates/
│   ├── base.html, _macros.html, errors.html
│   ├── shop/              # home, product_detail, cart, checkout, payment, order_confirmation
│   └── admin/             # base, login, products, product_form, orders, order_detail
├── static/css/style.css, static/js/main.js
├── uploads/products/      # Product images (+ thumbs/)
└── tests/test_shop.py     # Unit & end-to-end tests
```

### Database schema

```
product   (id, name, description, price, stock, image, thumbnail, status, created_at, updated_at)
orders    (id, public_id, customer_name, customer_email, customer_phone, shipping_address,
           total_amount, currency, status, khqr_string, khqr_md5, khqr_expires_at,
           payment_reference, created_at, paid_at)
order_item(id, order_id → orders, product_id → product (NULL if deleted),
           product_name, unit_price, quantity, subtotal)
user      (id, username, email, password_hash, role, created_at)
```

---

## Security notes

* Passwords hashed with Werkzeug (`scrypt`); session fixation prevented on login.
* CSRF token required on every POST form.
* Guest order pages use an unguessable `public_id` (UUID) instead of the numeric ID.
* Stock is reserved atomically (`UPDATE … WHERE stock >= qty`) to prevent overselling.
* Uploaded images are verified with Pillow, re-encoded to JPEG and given random names.
* Admin login is rate-limited; uploads are limited to 10 MB.
