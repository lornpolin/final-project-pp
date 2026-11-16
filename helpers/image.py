"""
Product image helpers – validation, resizing, thumbnails and placeholders.
"""
import os
import uuid

from PIL import Image as PILImage, ImageDraw, ImageFont, ImageOps
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "jfif", "png", "webp"}
MAX_IMAGE_SIZE = (1200, 1200)
THUMB_SIZE = (480, 480)


def allowed_file(filename):
    """Return True when the file extension is in the allowed set."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _to_rgb(img):
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        background = PILImage.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        return background
    return img.convert("RGB")


def save_product_image(file, image_folder, thumb_folder):
    """
    Validate and store an uploaded product image.

    * The full image is resized to fit within 1200×1200 and stored as JPEG.
    * A square 480×480 thumbnail (centre-cropped) is generated for listings.

    Returns ``(image_filename, thumbnail_filename)``.
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

    os.makedirs(image_folder, exist_ok=True)
    os.makedirs(thumb_folder, exist_ok=True)

    img = _to_rgb(img)
    base = uuid.uuid4().hex
    image_name, thumb_name = f"{base}.jpg", f"{base}_thumb.jpg"

    full = img.copy()
    full.thumbnail(MAX_IMAGE_SIZE, PILImage.LANCZOS)
    full.save(os.path.join(image_folder, image_name), "JPEG", quality=88, optimize=True)

    thumb = ImageOps.fit(img, THUMB_SIZE, PILImage.LANCZOS)
    thumb.save(os.path.join(thumb_folder, thumb_name), "JPEG", quality=85, optimize=True)

    return image_name, thumb_name


def delete_product_image(image_name, thumb_name, image_folder, thumb_folder):
    """Remove stored image files (ignores missing files)."""
    for folder, name in ((image_folder, image_name), (thumb_folder, thumb_name)):
        if name:
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass


def create_placeholder_image(text, colors, image_folder, thumb_folder):
    """
    Generate a simple gradient product image (used for seed data).
    Returns ``(image_filename, thumbnail_filename)``.
    """
    os.makedirs(image_folder, exist_ok=True)
    os.makedirs(thumb_folder, exist_ok=True)

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

    base = uuid.uuid4().hex
    image_name, thumb_name = f"{base}.jpg", f"{base}_thumb.jpg"
    img.save(os.path.join(image_folder, image_name), "JPEG", quality=88)
    ImageOps.fit(img, THUMB_SIZE, PILImage.LANCZOS).save(
        os.path.join(thumb_folder, thumb_name), "JPEG", quality=85)
    return image_name, thumb_name
