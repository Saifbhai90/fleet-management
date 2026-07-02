"""
Server-side slip OCR service — hybrid fallback engine.

When the browser Tesseract.js path returns low confidence, the slip image is
sent here. This module tries, in order:

  Tier A — PaddleOCR (Urdu + English, highest accuracy, Apache-2.0)
  Tier B — EasyOCR   (80+ languages, Apache-2.0)
  Tier C — Tesseract via pytesseract (fallback of last resort)

Every tier is OPTIONAL. If a backend is not installed, the next is tried. If
none are available, the service reports `available=False` so the caller can
skip server OCR entirely (the browser keeps its result).

No data ever leaves the server. 100% in-house, free, self-hosted.

Install (optional, to enable server OCR):
    pip install paddlepaddle paddleocr      # Tier A
    pip install easyocr                      # Tier B
    pip install pytesseract                  # Tier C (+ system tesseract binary)
"""
from __future__ import annotations

import io
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Backend probes (lazy, memoised)
# ---------------------------------------------------------------------------

_paddle = None          # type: Optional[object]
_paddle_tried = False
_easyocr = None         # type: Optional[object]
_easyocr_tried = False
_pytesseract = None     # type: Optional[object]
_pytesseract_tried = False


def _probe_paddleocr():
    """Lazily import + instantiate PaddleOCR (Urdu + English). Memoised."""
    global _paddle, _paddle_tried
    if _paddle_tried:
        return _paddle
    _paddle_tried = True
    try:
        from paddleocr import PaddleOCR  # type: ignore
        _paddle = PaddleOCR(use_angle_cls=True, lang="ur", show_log=False)
        logger.info("PaddleOCR backend ready (lang=ur)")
    except Exception as exc:  # noqa: BLE001
        _paddle = None
        logger.debug("PaddleOCR unavailable: %s", exc)
    return _paddle


def _probe_easyocr():
    global _easyocr, _easyocr_tried
    if _easyocr_tried:
        return _easyocr
    _easyocr_tried = True
    try:
        import easyocr  # type: ignore
        _easyocr = easyocr.Reader(["en", "ur"], gpu=False)
        logger.info("EasyOCR backend ready (en+ur)")
    except Exception as exc:  # noqa: BLE001
        _easyocr = None
        logger.debug("EasyOCR unavailable: %s", exc)
    return _easyocr


def _probe_pytesseract():
    global _pytesseract, _pytesseract_tried
    if _pytesseract_tried:
        return _pytesseract
    _pytesseract_tried = True
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # noqa: F401  (presence check)
        pytesseract.get_tesseract_version()
        _pytesseract = pytesseract
        logger.info("pytesseract backend ready")
    except Exception as exc:  # noqa: BLE001
        _pytesseract = None
        logger.debug("pytesseract unavailable: %s", exc)
    return _pytesseract


def is_available() -> bool:
    """True if ANY server OCR backend is usable."""
    return bool(_probe_paddleocr() or _probe_easyocr() or _probe_pytesseract())


def available_engine() -> str:
    p = _probe_paddleocr()
    if p:
        return "paddleocr"
    if _probe_easyocr():
        return "easyocr"
    if _probe_pytesseract():
        return "tesseract"
    return "none"


# ---------------------------------------------------------------------------
# Recognition
# ---------------------------------------------------------------------------

def _recognise_paddleocr(img) -> str:
    result = _paddle.ocr(img, cls=True)
    lines = []
    for block in result or []:
        for line in block or []:
            # line = [bbox, (text, confidence)]
            try:
                lines.append(line[1][0])
            except (IndexError, TypeError):
                continue
    return "\n".join(lines)


def _recognise_easyocr(img) -> str:
    raw = _easyocr.readtext(img, detail=0, paragraph=True)
    return "\n".join(raw or [])


def _recognise_pytesseract(img) -> str:
    from PIL import Image
    pil = Image.open(io.BytesIO(img)) if isinstance(img, (bytes, bytearray)) else img
    return _pytesseract.image_to_string(pil)


def _run_recognition(image_bytes: bytes) -> tuple:
    """Try each backend; return (text, engine). (text may be '')"""
    try:
        img_obj = image_bytes
        if _probe_paddleocr():
            try:
                text = _recognise_paddleocr(img_obj)
                if text.strip():
                    return text, "paddleocr"
            except Exception as exc:  # noqa: BLE001
                logger.debug("paddleocr run failed: %s", exc)
        if _probe_easyocr():
            try:
                text = _recognise_easyocr(img_obj)
                if text.strip():
                    return text, "easyocr"
            except Exception as exc:  # noqa: BLE001
                logger.debug("easyocr run failed: %s", exc)
        if _probe_pytesseract():
            try:
                text = _recognise_pytesseract(img_obj)
                if text.strip():
                    return text, "tesseract"
            except Exception as exc:  # noqa: BLE001
                logger.debug("pytesseract run failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("server OCR recognition error: %s", exc)
    return "", "none"


# ---------------------------------------------------------------------------
# Parsing — Python port of the browser 04_parser.js "Hunter"
# ---------------------------------------------------------------------------

# Accept BOTH Western grouping (150,000) AND Indic lakh/crore (1,50,000).
# `\d{2,3}` groups cover both — numerically stripping all commas yields the
# correct value either way.
_AMOUNT_NUM = r"(\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d{2})?"
_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
AMOUNT_MIN = 10
AMOUNT_MAX = 10_000_000_000


def _fix_digits(text: str) -> str:
    text = re.sub(r"([OoD])(?=[\d,])", "0", text)
    text = re.sub(r"(?<=[\d,])[OoD]", "0", text)
    text = re.sub(r"([lI|])(?=[\d,])", "1", text)
    text = re.sub(r"(?<=[\d,])[lI|]", "1", text)
    return text


def _normalise_amount(val: str) -> Optional[str]:
    if not val:
        return None
    cleaned = _fix_digits(val).replace(" ", "").replace(",", "")
    if re.match(r"^\d+\.\d{2}$", cleaned):
        pass  # decimal cents
    else:
        cleaned = re.sub(r"\.(?=.*\.)", "", cleaned)
    try:
        num = float(cleaned)
    except ValueError:
        return None
    if num < AMOUNT_MIN or num > AMOUNT_MAX:
        return None
    return str(round(num)) if num % 1 == 0 else f"{num:.2f}"


def _hunt_amount(text: str) -> Optional[str]:
    if not text:
        return None
    raw = _fix_digits(text)
    patterns = [
        (re.compile(r"Rs\.\s*" + _AMOUNT_NUM, re.I), 135),
        (re.compile(r"(?:PKR|RS\.?)\s*" + _AMOUNT_NUM, re.I), 120),
        (re.compile(r"(?:TRANSFERRED\s*AMOUNT|AMOUNT\s*PAID|AMOUNT)\s*[:\-]?\s*(?:PKR|RS\.?)?\s*([\d,]+(?:\.\d{2})?)", re.I), 115),
        (re.compile(r"\b(\d{1,3}(?:,\d{3})+(?:\.\d{2})?)\b"), 70),
    ]
    best = None
    best_score = 0
    for pat, bonus in patterns:
        for m in pat.finditer(raw):
            val = _normalise_amount(m.group(1))
            if not val:
                continue
            score = bonus
            if re.search(r"(?:RS\.|PKR\.?)", raw, re.I):
                score += 8
            if score > best_score or (score == best_score and val == best):
                best_score = score
                best = val
    if not best:
        plain = re.search(r"\b(\d{3,7}(?:\.\d{2})?)\b", raw)
        if plain:
            best = _normalise_amount(plain.group(1))
    return best


def _month_from_name(name: str) -> int:
    c = re.sub(r"[^a-z]", "", (name or "").lower())
    if not c:
        return 0
    if c in _MONTHS:
        return _MONTHS[c]
    return _MONTHS.get(c[:3], 0)


def _pad2(n: int) -> str:
    return f"{n:02d}"


def _hunt_date(text: str, date_format: str = "") -> Optional[str]:
    if not text:
        return None
    forced = (date_format or "").upper()
    month_re = r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    patterns = [
        (re.compile(r"\b(?:On\s+)?(" + month_re + r")[a-z]*\s+(\d{1,2}),?\s+(\d{4})\b", re.I), "mdy4"),
        (re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b"), "ymd"),
        (re.compile(r"\b(\d{1,2})[/\-.](Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[/\-.](\d{4})\b", re.I), "dmy4"),
        (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "numeric"),
        (re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b"), "numeric"),
    ]
    best = None
    best_score = -1
    for pat, kind in patterns:
        for m in pat.finditer(text):
            score = 80
            try:
                if kind == "mdy4":
                    mo = _month_from_name(m.group(1)); d = int(m.group(2)); y = int(m.group(3))
                elif kind == "ymd":
                    y = int(m.group(1).replace("O", "0")); mo = int(m.group(2)); d = int(m.group(3))
                elif kind == "dmy4":
                    d = int(m.group(1)); mo = _month_from_name(m.group(2)); y = int(m.group(3))
                else:
                    n1 = int(m.group(1)); n2 = int(m.group(2)); y = int(m.group(3))
                    if forced == "MDY":
                        mo, d = n1, n2
                    elif forced == "YMD":
                        mo, d = n1, n2
                    else:
                        d, mo = n1, n2
            except ValueError:
                continue
            if y < 100:
                y += 2000
            if not (1 <= d <= 31 and 1 <= mo <= 12 and 2000 <= y <= 2100):
                continue
            if score > best_score:
                best_score = score
                best = f"{_pad2(d)}-{_pad2(mo)}-{y}"
    return best


def _hunt_reference(text: str) -> Optional[str]:
    if not text:
        return None
    label_res = [
        re.compile(r"\bTID\s*:\s*(\d{5,})", re.I),
        re.compile(r"Reference\s*Number\s*#\s*(\d{5,})", re.I),
        re.compile(r"\bRef\s*#\s*(\d{5,})", re.I),
        re.compile(r"(?:Transaction\s*ID|TID|Txn)\s*[:\-#]?\s*(\d{6,})", re.I),
        re.compile(r"(?:TRANSACTION\s*ID|TID|TXN|REF(?:ERENCE)?)\s*[:\-#]?\s*(\d{6,})", re.I),
    ]
    for rx in label_res:
        for m in rx.finditer(text):
            digits = _fix_digits(m.group(1)).replace(" ", "")
            digits = re.sub(r"\D", "", digits)
            if _is_plausible_ref(digits):
                return digits
    h = re.search(r"#\s*(\d{5,})", text)
    if h and _is_plausible_ref(re.sub(r"\D", "", h.group(1))):
        return re.sub(r"\D", "", h.group(1))
    runs = re.findall(r"\b\d{6,}\b", text)
    for r in runs:
        if _is_plausible_ref(r):
            return r
    return None


def _is_plausible_ref(digits: str) -> bool:
    if not digits or len(digits) < 5 or len(digits) > 20:
        return False
    if re.match(r"^20\d{6}$", digits):
        return False
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ocr_slip_image(image_bytes: bytes, date_format: str = "") -> dict:
    """
    Run server-side OCR on a slip image and extract structured fields.

    Returns:
        {
            "ok": bool,            # True if any text was recognised
            "available": bool,     # True if a backend engine exists
            "engine": str,         # paddleocr|easyocr|tesseract|none
            "raw_text": str,       # full OCR text
            "date": str|None,
            "amount": str|None,
            "reference_no": str|None,
            "confidence": float,   # heuristic 0..1
        }
    """
    if not is_available():
        return {
            "ok": False, "available": False, "engine": "none",
            "raw_text": "", "date": None, "amount": None,
            "reference_no": None, "confidence": 0.0,
        }
    text, engine = _run_recognition(image_bytes)
    if not text.strip():
        return {
            "ok": False, "available": True, "engine": engine,
            "raw_text": "", "date": None, "amount": None,
            "reference_no": None, "confidence": 0.0,
        }
    date = _hunt_date(text, date_format)
    amount = _hunt_amount(text)
    reference_no = _hunt_reference(text)
    found = sum(1 for v in (date, amount, reference_no) if v)
    confidence = round(0.6 + 0.12 * found, 3) if found else 0.45
    return {
        "ok": True, "available": True, "engine": engine,
        "raw_text": text[:4000],
        "date": date, "amount": amount, "reference_no": reference_no,
        "confidence": min(0.95, confidence),
    }
