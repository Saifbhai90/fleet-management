import io
import os
import uuid
from typing import Optional, Tuple

import boto3
from boto3.s3.transfer import TransferConfig
from werkzeug.utils import secure_filename
from botocore.config import Config
from PIL import Image


R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
R2_ENDPOINT_URL = os.environ.get("R2_ENDPOINT_URL", "").strip()
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "").strip()
R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "").strip().rstrip("/")


def _get_s3_client():
    """
    Create a boto3 S3 client for Cloudflare R2.

    We keep this lazy so local dev without R2 creds can still run most of the app.
    """
    if not (R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_ENDPOINT_URL and R2_BUCKET_NAME and R2_PUBLIC_URL):
        raise RuntimeError("Cloudflare R2 environment variables are not fully configured.")

    # Cloudflare R2 S3 API expects region "auto" and sigv4
    session = boto3.session.Session()
    client = session.client(
        "s3",
        region_name="auto",
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
    )
    return client


def _process_image_to_webp(data: bytes, max_width: int = 1000, quality: int = 75) -> bytes:
    """
    Compress + resize image and convert to WebP.

    - Maintains aspect ratio.
    - If image is already smaller than max_width, width is preserved.
    """
    with Image.open(io.BytesIO(data)) as img:
        # Ensure we have RGB / RGBA for WebP
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")

        w, h = img.size
        if w > max_width:
            new_h = int(h * (max_width / float(w)))
            img = img.resize((max_width, new_h), Image.LANCZOS)

        out = io.BytesIO()
        img.save(out, format="WEBP", quality=quality, method=6)
        out.seek(0)
        return out.read()


def upload_image_bytes(data: bytes, folder: str = "attendance", max_retries: int = 3) -> str:
    """
    Upload raw image bytes to R2 after resizing/compressing to WebP.

    Returns the public URL that should be stored in the database.
    """
    client = _get_s3_client()

    processed = _process_image_to_webp(data)
    uid = uuid.uuid4().hex
    key = f"{folder.rstrip('/')}/{uid}.webp"

    last_exc: Exception | None = None
    for _ in range(max_retries):
        try:
            client.put_object(
                Bucket=R2_BUCKET_NAME,
                Key=key,
                Body=processed,
                ContentType="image/webp",
            )
            return f"{R2_PUBLIC_URL}/{key}"
        except Exception as e:
            last_exc = e
    # Agar 3 attempts ke baad bhi fail ho jaye to error bubble up kar do
    raise last_exc or RuntimeError("Unknown error uploading to R2")


def upload_image_file(file_storage, folder: str = "attendance") -> Optional[str]:
    """
    Convenience wrapper for `werkzeug.datastructures.FileStorage` objects
    (Flask `request.files[...]`).

    Reads file into memory, converts to WebP, uploads to R2 and returns the public URL.
    """
    if not file_storage:
        return None
    # Read entire content once; temporary stream is in memory / temp file which
    # Flask/Werkzeug will clean up automatically after request.
    data = file_storage.read()
    if not data:
        return None
    return upload_image_bytes(data, folder=folder)


def delete_file_by_url(public_url: str) -> bool:
    """
    Delete a file from R2 given its full public URL.
    Extracts the object key from the URL and calls delete_object.
    Returns True on success, False if URL doesn't belong to this bucket or on error.
    """
    if not public_url:
        return False
    base = R2_PUBLIC_URL.rstrip("/")
    if not base or not public_url.startswith(base + "/"):
        return False
    key = public_url[len(base) + 1:]
    if not key:
        return False
    try:
        client = _get_s3_client()
        client.delete_object(Bucket=R2_BUCKET_NAME, Key=key)
        return True
    except Exception:
        return False


def upload_pdf_file(file_storage, folder: str = "drivers/documents", max_retries: int = 3) -> Optional[str]:
    """
    Upload a PDF FileStorage object to R2 and return the public URL.
    """
    if not file_storage:
        return None
    data = file_storage.read()
    if not data:
        return None
    client = _get_s3_client()
    uid = uuid.uuid4().hex
    key = f"{folder.rstrip('/')}/{uid}.pdf"
    last_exc: Exception | None = None
    for _ in range(max_retries):
        try:
            client.put_object(
                Bucket=R2_BUCKET_NAME,
                Key=key,
                Body=data,
                ContentType="application/pdf",
            )
            return f"{R2_PUBLIC_URL}/{key}"
        except Exception as e:
            last_exc = e
    raise last_exc or RuntimeError("Unknown error uploading PDF to R2")


_VIDEO_EXT_TO_CT = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
}


def upload_binary_file(
    file_storage,
    folder: str,
    original_filename: str = "",
    max_retries: int = 3,
) -> Optional[str]:
    """
    Upload large binaries (e.g. expense videos) to R2 using multipart streaming.

    Avoids loading the whole file into RAM (important for Render / small workers).
    Returns the public URL, or None if empty input.
    """
    if not file_storage:
        return None
    name_src = (original_filename or getattr(file_storage, "filename", "") or "").strip()
    fn = secure_filename(name_src) or "media"
    ext = os.path.splitext(fn)[1].lower()
    if ext not in _VIDEO_EXT_TO_CT:
        ext = ".mp4"
    content_type = _VIDEO_EXT_TO_CT.get(ext, "application/octet-stream")
    client = _get_s3_client()
    uid = uuid.uuid4().hex
    key = f"{folder.rstrip('/')}/{uid}{ext}"
    xfer = TransferConfig(
        multipart_threshold=8 * 1024 * 1024,
        multipart_chunksize=8 * 1024 * 1024,
        max_concurrency=4,
        use_threads=True,
    )
    last_exc: Exception | None = None
    for _ in range(max_retries):
        try:
            file_storage.seek(0)
            stream = file_storage.stream
            try:
                stream.seek(0)
            except Exception:
                pass
            # Empty body check without reading whole file into RAM
            try:
                end_pos = stream.seek(0, os.SEEK_END)
                if end_pos == 0:
                    return None
                stream.seek(0)
            except Exception:
                file_storage.seek(0)
            client.upload_fileobj(
                stream,
                R2_BUCKET_NAME,
                key,
                ExtraArgs={"ContentType": content_type},
                Config=xfer,
            )
            return f"{R2_PUBLIC_URL}/{key}"
        except Exception as e:
            last_exc = e
    raise last_exc or RuntimeError("Unknown error uploading binary file to R2")

