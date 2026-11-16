"""
KHQR (Bakong) payment helpers.

Builds an EMVCo-compliant *KHQR* payload string following the NBC KHQR
specification, renders it as a QR code image and (optionally) checks the
payment status through the Bakong Open API.

KHQR string layout (Tag-Length-Value):

    00  Payload format indicator            "01"
    01  Point of initiation                 "11" static / "12" dynamic (has amount)
    29  Individual merchant account info
        00  Bakong account ID               e.g. "shop@aclb"
        01  Account information (optional)
        02  Acquiring bank     (optional)
    52  Merchant category code              "5999"
    53  Transaction currency                "840" USD / "116" KHR
    54  Transaction amount
    58  Country code                        "KH"
    59  Merchant name   (max 25)
    60  Merchant city   (max 15)
    62  Additional data
        01  Bill number     (max 25)
        02  Mobile number   (max 25)
        03  Store label     (max 25)
        07  Terminal label  (max 25)
    99  Timestamp
        00  Creation timestamp (ms)
        01  Expiration timestamp (ms)
    63  CRC-16/CCITT-FALSE checksum
"""
import base64
import hashlib
import io
import json
import time
import urllib.error
import urllib.request
from decimal import Decimal, ROUND_HALF_UP

import qrcode
from qrcode.constants import ERROR_CORRECT_Q

CURRENCY_CODES = {"USD": "840", "KHR": "116"}


# ── TLV helpers ──────────────────────────────────────────────────────

def _tlv(tag: str, value: str) -> str:
    value = str(value)
    if len(value) > 99:
        raise ValueError(f"KHQR tag {tag} value too long")
    return f"{tag}{len(value):02d}{value}"


def crc16_ccitt(data: str) -> str:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) as 4 upper-case hex chars."""
    crc = 0xFFFF
    for byte in data.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def _format_amount(amount, currency: str) -> str:
    amount = Decimal(str(amount))
    if currency == "KHR":
        return str(int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
    return str(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ── Public API ───────────────────────────────────────────────────────

def generate_khqr(
    *,
    bakong_account_id: str,
    merchant_name: str,
    merchant_city: str = "Phnom Penh",
    amount=None,
    currency: str = "USD",
    bill_number: str = "",
    mobile_number: str = "",
    store_label: str = "",
    terminal_label: str = "",
    acquiring_bank: str = "",
    expire_minutes: int = 15,
) -> dict:
    """
    Build a KHQR payload.

    Returns a dict with ``qr`` (the payload string), ``md5`` (hash used by the
    Bakong API to look up the transaction) and ``expires_at_ms``.
    """
    currency = currency.upper()
    if currency not in CURRENCY_CODES:
        raise ValueError("KHQR currency must be USD or KHR")
    if not bakong_account_id or "@" not in bakong_account_id:
        raise ValueError("A valid Bakong account ID (e.g. name@bank) is required")

    dynamic = amount is not None and Decimal(str(amount)) > 0

    account_info = _tlv("00", bakong_account_id)
    if acquiring_bank:
        account_info += _tlv("02", acquiring_bank[:32])

    additional = ""
    if bill_number:
        additional += _tlv("01", bill_number[:25])
    if mobile_number:
        additional += _tlv("02", mobile_number[:25])
    if store_label:
        additional += _tlv("03", store_label[:25])
    if terminal_label:
        additional += _tlv("07", terminal_label[:25])

    now_ms = int(time.time() * 1000)
    expires_ms = now_ms + expire_minutes * 60 * 1000

    payload = _tlv("00", "01")
    payload += _tlv("01", "12" if dynamic else "11")
    payload += _tlv("29", account_info)
    payload += _tlv("52", "5999")
    payload += _tlv("53", CURRENCY_CODES[currency])
    if dynamic:
        payload += _tlv("54", _format_amount(amount, currency))
    payload += _tlv("58", "KH")
    payload += _tlv("59", merchant_name[:25])
    payload += _tlv("60", merchant_city[:15])
    if additional:
        payload += _tlv("62", additional)
    timestamp = _tlv("00", str(now_ms))
    if dynamic:
        timestamp += _tlv("01", str(expires_ms))
    payload += _tlv("99", timestamp)

    payload += "6304"
    payload += crc16_ccitt(payload)

    return {
        "qr": payload,
        "md5": hashlib.md5(payload.encode("utf-8")).hexdigest(),
        "expires_at_ms": expires_ms,
    }


def verify_crc(payload: str) -> bool:
    """Return True if the trailing CRC of a KHQR payload is valid."""
    if len(payload) < 8 or payload[-8:-4] != "6304":
        return False
    return crc16_ccitt(payload[:-4]) == payload[-4:].upper()


def qr_png_data_uri(payload: str) -> str:
    """Render the payload as a PNG QR code and return it as a data: URI."""
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_Q, box_size=10, border=1)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def check_payment(md5: str, *, token: str, api_url: str, timeout: int = 8) -> dict | None:
    """
    Ask the Bakong Open API whether a transaction for the given KHQR md5 exists.

    Returns the transaction ``data`` dict when paid, ``None`` when not found.
    Raises ``RuntimeError`` on network / API errors.
    """
    req = urllib.request.Request(
        api_url.rstrip("/") + "/v1/check_transaction_by_md5",
        data=json.dumps({"md5": md5}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError(f"Bakong API error: {exc}") from exc

    if body.get("responseCode") == 0 and body.get("data"):
        return body["data"]
    return None
