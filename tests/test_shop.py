"""
End-to-end tests for the shop.  Run with:

    python -m unittest discover -s tests -v
"""
import os
import re
import shutil
import sys
import tempfile
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import Config  # noqa: E402
from app import create_app  # noqa: E402
from extensions import db  # noqa: E402
from helpers.khqr import crc16_ccitt, generate_khqr, verify_crc  # noqa: E402
from models import Order, Product  # noqa: E402


class KHQRTests(unittest.TestCase):
    def test_crc_check_value(self):
        # Standard CRC-16/CCITT-FALSE check value
        self.assertEqual(crc16_ccitt("123456789"), "29B1")

    def test_generate_dynamic_khqr(self):
        result = generate_khqr(bakong_account_id="shop@aclb", merchant_name="PP Shop",
                               amount=Decimal("12.5"), currency="USD", bill_number="ORD-000001")
        qr = result["qr"]
        self.assertTrue(qr.startswith("000201010212"))
        self.assertIn("29130009shop@aclb", qr)
        self.assertIn("5303840", qr)
        self.assertIn("540512.50", qr)
        self.assertIn("5802KH", qr)
        self.assertIn("0110ORD-000001", qr)
        self.assertTrue(verify_crc(qr))
        self.assertEqual(len(result["md5"]), 32)

    def test_static_khr(self):
        qr = generate_khqr(bakong_account_id="shop@aclb", merchant_name="PP Shop", currency="KHR")["qr"]
        self.assertIn("010211", qr[:12])
        self.assertIn("5303116", qr)
        self.assertNotIn("5401", qr.split("5802")[0][-10:])
        self.assertTrue(verify_crc(qr))

    def test_invalid_account(self):
        with self.assertRaises(ValueError):
            generate_khqr(bakong_account_id="invalid", merchant_name="X", amount=1)


class ShopFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

        class TestConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(self.tmp, "test.db")
            UPLOAD_FOLDER_PRODUCTS = os.path.join(self.tmp, "products")
            UPLOAD_FOLDER_THUMBNAILS = os.path.join(self.tmp, "products", "thumbs")
            BAKONG_API_TOKEN = ""
            KHQR_DEMO_MODE = True
            RATELIMIT_ENABLED = False

        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers
    def csrf(self):
        self.client.get("/")
        with self.client.session_transaction() as s:
            return s["_csrf_token"]

    def first_product(self, **filters):
        with self.app.app_context():
            p = Product.query.filter(Product.stock > 2).order_by(Product.id).first()
            return p.id, p.name, p.stock, Decimal(p.price)

    def login_admin(self):
        token = self.csrf()
        return self.client.post("/admin/login", data={"csrf_token": token, "username": "admin",
                                                      "password": "Admin@123"}, follow_redirects=True)

    # tests
    def test_home_and_detail(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Wireless Headphones", r.data)
        self.assertIn(b"View Details", r.data)
        pid, name, *_ = self.first_product()
        r = self.client.get(f"/product/{pid}")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"facebook.com/sharer", r.data)
        self.assertIn(b"t.me/share/url", r.data)
        self.assertIn(b'og:title', r.data)

    def test_csrf_required(self):
        pid, *_ = self.first_product()
        r = self.client.post(f"/cart/add/{pid}", data={"quantity": 1})
        self.assertEqual(r.status_code, 400)

    def test_full_checkout_flow(self):
        token = self.csrf()
        pid, name, stock, price = self.first_product()

        r = self.client.post(f"/cart/add/{pid}", data={"csrf_token": token, "quantity": 2}, follow_redirects=True)
        self.assertIn(b"Shopping cart", r.data)
        self.assertIn(f"{price * 2:,.2f}".encode(), r.data)

        # update quantity
        self.client.post(f"/cart/update/{pid}", data={"csrf_token": token, "quantity": 3})
        with self.client.session_transaction() as s:
            self.assertEqual(s["cart"][str(pid)], 3)

        # invalid checkout
        r = self.client.post("/checkout", data={"csrf_token": token, "name": "", "email": "bad",
                                                "phone": "x", "address": ""})
        self.assertIn(b"is-invalid", r.data)

        # valid checkout
        r = self.client.post("/checkout", data={
            "csrf_token": token, "name": "Sok Dara", "email": "dara@example.com",
            "phone": "012 345 678", "address": "#12, St 271, Phnom Penh"})
        self.assertEqual(r.status_code, 302)
        pay_url = r.headers["Location"]
        public_id = re.search(r"/checkout/pay/([0-9a-f]+)", pay_url).group(1)

        with self.app.app_context():
            order = Order.query.filter_by(public_id=public_id).one()
            self.assertEqual(order.status, "PENDING")
            self.assertEqual(order.total_amount, price * 3)
            self.assertTrue(verify_crc(order.khqr_string))
            self.assertEqual(db.session.get(Product, pid).stock, stock - 3)

        r = self.client.get(pay_url)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"KHQR", r.data)
        self.assertIn(b"data:image/png;base64", r.data)

        # cart cleared after placing the order
        with self.client.session_transaction() as s:
            self.assertFalse(s.get("cart"))

        r = self.client.get(f"/checkout/pay/{public_id}/status")
        self.assertEqual(r.get_json()["status"], "PENDING")

        r = self.client.post(f"/checkout/pay/{public_id}/simulate", data={"csrf_token": token},
                             follow_redirects=True)
        self.assertIn(b"Your order is confirmed", r.data)
        self.assertIn(b"Sok Dara", r.data)
        self.assertIn(b"ORD-", r.data)

        # Admin sees the order
        self.login_admin()
        r = self.client.get("/admin/orders")
        self.assertIn(b"Sok Dara", r.data)
        self.assertIn(b"012 345 678", r.data)
        with self.app.app_context():
            oid = Order.query.filter_by(public_id=public_id).one().id
        r = self.client.get(f"/admin/orders/{oid}")
        self.assertIn(b"#12, St 271, Phnom Penh", r.data)
        self.assertIn(name.encode(), r.data)

    def test_cancel_restores_stock(self):
        token = self.csrf()
        pid, _, stock, _ = self.first_product()
        self.client.post(f"/cart/add/{pid}", data={"csrf_token": token, "quantity": 1})
        r = self.client.post("/checkout", data={
            "csrf_token": token, "name": "A B", "email": "a@b.co", "phone": "+855 12 345 678",
            "address": "Siem Reap city"})
        public_id = r.headers["Location"].rsplit("/", 1)[-1]
        self.client.post(f"/checkout/pay/{public_id}/cancel", data={"csrf_token": token})
        with self.app.app_context():
            self.assertEqual(db.session.get(Product, pid).stock, stock)
            self.assertEqual(Order.query.filter_by(public_id=public_id).one().status, "CANCELLED")

    def test_out_of_stock_cannot_be_added(self):
        token = self.csrf()
        with self.app.app_context():
            pid = Product.query.filter(Product.stock == 0).first().id
        self.client.post(f"/cart/add/{pid}", data={"csrf_token": token, "quantity": 1})
        with self.client.session_transaction() as s:
            self.assertNotIn(str(pid), s.get("cart", {}))

    def test_admin_requires_login(self):
        r = self.client.get("/admin/products")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login", r.headers["Location"])

    def test_all_pages_render(self):
        self.assertEqual(self.client.get("/healthz").status_code, 200)
        self.assertEqual(self.client.get("/cart").status_code, 200)
        self.assertEqual(self.client.get("/checkout").status_code, 302)  # empty cart
        self.assertEqual(self.client.get("/product/99999").status_code, 404)
        self.assertEqual(self.client.get("/?q=mug&sort=price_asc").status_code, 200)
        self.assertEqual(self.client.get("/admin/login").status_code, 200)
        self.login_admin()
        pid, *_ = self.first_product()
        for url in ("/admin/products", "/admin/products/new", f"/admin/products/{pid}/edit",
                    "/admin/orders", "/admin/products?status=INACTIVE&q=x", "/admin/orders?q=ORD-1"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)

    def test_admin_product_crud(self):
        self.login_admin()
        token = self.csrf()
        r = self.client.get("/admin/products")
        self.assertIn(b"Add New Product", r.data)

        # create with image
        from io import BytesIO
        from PIL import Image
        buf = BytesIO()
        Image.new("RGB", (300, 200), (200, 50, 50)).save(buf, "PNG")
        buf.seek(0)
        r = self.client.post("/admin/products/new", data={
            "csrf_token": token, "name": "Test Product", "description": "Desc", "price": "9.99",
            "stock": "7", "status": "ACTIVE", "image": (buf, "pic.png")},
            content_type="multipart/form-data", follow_redirects=True)
        self.assertIn(b"Test Product", r.data)
        with self.app.app_context():
            p = Product.query.filter_by(name="Test Product").one()
            self.assertTrue(os.path.exists(os.path.join(self.app.config["UPLOAD_FOLDER_THUMBNAILS"], p.thumbnail)))
            pid = p.id

        # invalid edit
        r = self.client.post(f"/admin/products/{pid}/edit", data={
            "csrf_token": token, "name": "", "price": "-1", "stock": "x", "status": "ACTIVE"})
        self.assertIn(b"is-invalid", r.data)

        # edit -> inactive hides it from store
        self.client.post(f"/admin/products/{pid}/edit", data={
            "csrf_token": token, "name": "Test Product 2", "description": "D", "price": "5",
            "stock": "3", "status": "INACTIVE"})
        self.assertEqual(self.client.get(f"/product/{pid}").status_code, 404)

        # delete
        self.client.post(f"/admin/products/{pid}/delete", data={"csrf_token": token})
        with self.app.app_context():
            self.assertIsNone(db.session.get(Product, pid))

    def test_jfif_image_upload(self):
        from io import BytesIO
        from PIL import Image

        self.login_admin()
        token = self.csrf()
        buf = BytesIO()
        Image.new("RGB", (240, 240), (40, 120, 200)).save(buf, "JPEG")
        buf.seek(0)
        r = self.client.post("/admin/products/new", data={
            "csrf_token": token, "name": "JFIF Product", "description": "Desc", "price": "12.00",
            "stock": "5", "status": "ACTIVE", "image": (buf, "photo.jfif")},
            content_type="multipart/form-data", follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        with self.app.app_context():
            p = Product.query.filter_by(name="JFIF Product").one()
            self.assertTrue(p.image.endswith(".jpg"))
            self.assertTrue(os.path.exists(os.path.join(self.app.config["UPLOAD_FOLDER_THUMBNAILS"], p.thumbnail)))

    def test_postgres_url_normalization(self):
        from unittest.mock import patch
        from config import _database_url

        with patch.dict(os.environ, {"DATABASE_URL": "postgres://u:p@host/db?sslmode=require"}):
            self.assertEqual(_database_url(), "postgresql://u:p@host/db?sslmode=require")

    def test_cloudinary_upload_and_delete(self):
        from io import BytesIO
        from unittest.mock import patch
        from PIL import Image

        self.login_admin()
        token = self.csrf()
        buf = BytesIO()
        Image.new("RGB", (300, 300), (10, 90, 180)).save(buf, "JPEG")
        buf.seek(0)

        fake_url = "https://res.cloudinary.com/demo/image/upload/v123456/pp_shop/products/abc123.jpg"
        fake_thumb = "https://res.cloudinary.com/demo/image/upload/c_fill,g_auto,h_480,w_480/pp_shop/products/abc123"

        with patch.dict(self.app.config, {"CLOUDINARY_URL": "cloudinary://key:secret@demo"}), \
             patch("cloudinary.uploader.upload", return_value={
                 "secure_url": fake_url, "public_id": "pp_shop/products/abc123"
             }) as mock_upload, \
             patch("cloudinary.utils.cloudinary_url", return_value=(fake_thumb, {})), \
             patch("cloudinary.uploader.destroy") as mock_destroy:
            r = self.client.post("/admin/products/new", data={
                "csrf_token": token, "name": "Cloud Item", "description": "Cloud", "price": "19.00",
                "stock": "4", "status": "ACTIVE", "image": (buf, "cloud.jpg")},
                content_type="multipart/form-data", follow_redirects=True)
            self.assertEqual(r.status_code, 200)
            mock_upload.assert_called_once()

            with self.app.app_context():
                p = Product.query.filter_by(name="Cloud Item").one()
                self.assertEqual(p.image, fake_url)
                self.assertEqual(p.thumbnail, fake_thumb)
                pid = p.id

            detail = self.client.get(f"/product/{pid}")
            self.assertIn(fake_url.encode(), detail.data)

            self.client.post(f"/admin/products/{pid}/delete", data={"csrf_token": token})
            mock_destroy.assert_called_once_with("pp_shop/products/abc123", resource_type="image")


if __name__ == "__main__":
    unittest.main()
