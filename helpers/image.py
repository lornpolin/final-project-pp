"""
Product image helpers – validation, resizing, thumbnails, placeholders, and
optional Cloudinary cloud storage.
"""
import io
import os
import re
import uuid
from urllib.parse import unquote, urlparse

from flask import current_app, has_app_context
from PIL import Image as PILImage, ImageDraw, ImageFont, ImageOps
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "jfif", "png", "webp"}
MAX_IMAGE_SIZE = (1200, 1200)
THUMB_SIZE = (480, 480)
_CLOUDINARY_PUBLIC_ID_RE = re.compile(r"/upload/(?:[^/]+/)*?(?:v\d+/)?(.+?)(?:\.[^./?#]+)?(?:[?#].*)?$")


def allowed_file(filename):
    """Return True when the file extension is in the allowed set."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _cfg(key, default=""):
    if has_app_context():
        return current_app.config.get(key, default)
    return os.environ.get(key, default)


def _configure_cloudinary():
    """Configure Cloudinary from app config/env; return True if enabled."""
    url = (_cfg("CLOUDINARY_URL") or "").strip()
    cloud_name = (_cfg("CLOUDINARY_CLOUD_NAME") or "").strip()
    api_key = (_cfg("CLOUDINARY_API_KEY") or "").strip()
    api_secret = (_cfg("CLOUDINARY_API_SECRET") or "").strip()

    if url:
        parsed = urlparse(url)
        cloud_name = parsed.hostname or cloud_name
        api_key = unquote(parsed.username or "") or api_key
        api_secret = unquote(parsed.password or "") or api_secret

    if not (cloud_name and api_key and api_secret):
        return False

    import cloudinary

    cloudinary.config(cloud_name=cloud_name, api_key=api_key, api_secret=api_secret, secure=True)
    return True


def _to_rgb(img):
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        background = PILImage.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        return background
    return img.convert("RGB")


def _render_pil_bytes(img):
    """Return ``(image_name, thumb_name, image_bytes, thumb_bytes)`` for an RGB PIL image."""
    base = uuid.uuid4().hex
    full = img.copy()
    full.thumbnail(MAX_IMAGE_SIZE, PILImage.LANCZOS)
    full_buf = io.BytesIO()
    full.save(full_buf, "JPEG", quality=88, optimize=True)

    thumb = ImageOps.fit(img, THUMB_SIZE, PILImage.LANCZOS)
    thumb_buf = io.BytesIO()
    thumb.save(thumb_buf, "JPEG", quality=85, optimize=True)

    return f"{base}.jpg", f"{base}_thumb.jpg", full_buf.getvalue(), thumb_buf.getvalue()


def _store_pil_image(img, image_folder, thumb_folder):
    """Persist a validated RGB PIL image to Cloudinary (if configured) or return DB bytes."""
    image_name, thumb_name, full_bytes, thumb_bytes = _render_pil_bytes(img)
    base = image_name.rsplit(".", 1)[0]

    if _configure_cloudinary():
        import cloudinary.uploader
        import cloudinary.utils

        folder = (_cfg("CLOUDINARY_FOLDER", "pp_shop/products") or "pp_shop/products").strip("/")
        result = cloudinary.uploader.upload(
            io.BytesIO(full_bytes),
            folder=folder,
            public_id=base,
            resource_type="image",
            overwrite=True,
        )
        image_url = result["secure_url"]
        thumb_url, _ = cloudinary.utils.cloudinary_url(
            result["public_id"],
            secure=True,
            width=THUMB_SIZE[0],
            height=THUMB_SIZE[1],
            crop="fill",
            gravity="auto",
            quality="auto",
            fetch_format="auto",
        )
        return image_url, thumb_url, None, None

    return image_name, thumb_name, full_bytes, thumb_bytes


def save_product_image(file, image_folder="", thumb_folder=""):
    """
    Validate and process an uploaded product image.

    Returns ``(image_ref, thumbnail_ref, image_bytes, thumb_bytes)``.
    Raises ``ValueError`` if the file is not a valid image.
    """
    if not file or not file.filename or not allowed_file(secure_filename(file.filename)):
        raise ValueError("Invalid image type. Allowed: JPG, JPEG, JFIF, PNG, WEBP.")

    try:
        img = PILImage.open(file.stream)
        img.verify()
        file.stream.seek(0)
        img = PILImage.open(file.stream)
        img = ImageOps.exif_transpose(img)
    except Exception as exc:
        raise ValueError("The uploaded file is not a valid image.") from exc

    return _store_pil_image(_to_rgb(img), image_folder, thumb_folder)


def _extract_cloudinary_public_id(url):
    match = _CLOUDINARY_PUBLIC_ID_RE.search(url or "")
    return match.group(1) if match else None


def delete_product_image(image_name, thumb_name, image_folder, thumb_folder):
    """Remove stored image files from Cloudinary or local disk (ignores missing)."""
    if image_name and image_name.startswith(("http://", "https://")):
        if _configure_cloudinary():
            public_id = _extract_cloudinary_public_id(image_name)
            if public_id:
                import cloudinary.uploader

                try:
                    cloudinary.uploader.destroy(public_id, resource_type="image")
                except Exception:
                    pass
        return

    for folder, name in ((image_folder, image_name), (thumb_folder, thumb_name)):
        if name and not name.startswith(("http://", "https://")):
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass


def create_placeholder_image(text, colors, image_folder, thumb_folder):
    """
    Generate a simple gradient product image (used for seed data).
    Returns ``(image_ref, thumbnail_ref)``.
    """
    size = 900
    top, bottom = colors
    img = PILImage.new("RGB", (size, size), top)
    draw = ImageDraw.Draw(img)
    for y in range(size):
        ratio = y / size
        color = tuple(int(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3))
        draw.line([(0, y), (size, y)], fill=color)

    # Soft circle "product" silhouette
    draw.ellipse([220, 200, 680, 660], fill=tuple(min(c + 28, 255) for c in top))
    try:
        font = ImageFont.load_default(size=64)
        small = ImageFont.load_default(size=34)
    except TypeError:  # Pillow < 10.1
        font = small = ImageFont.load_default()

    initials = "".join(w[0] for w in text.split()[:2]).upper()
    draw.text((size / 2, 430), initials, fill=(255, 255, 255), font=font, anchor="mm")
    draw.text((size / 2, 760), text, fill=(255, 255, 255), font=small, anchor="mm")

    return _store_pil_image(img, image_folder, thumb_folder)
