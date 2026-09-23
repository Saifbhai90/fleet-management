"""Store expense photos and videos on Cloudflare only after they check out.

A file is accepted when the bytes are a real image or video and, when R2 is
configured, the object on Cloudflare reports the same size as the bytes we
sent. A cut-off or unreadable file is rejected. It is not saved as a success
on the server disk.
"""

import base64
import hashlib
import io
import os
import uuid
from datetime import datetime

from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename

import r2_storage

_IMAGE_MAX_BYTES = 40 * 1024 * 1024
_VIDEO_EXT = {'.mp4', '.webm', '.mov'}
_IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}


class MediaRejected(ValueError):
    """The upload is empty, cut off, or not a readable image/video."""


def _r2_ready():
    return bool(
        r2_storage.R2_PUBLIC_URL
        and r2_storage.R2_ACCESS_KEY_ID
        and r2_storage.R2_SECRET_ACCESS_KEY
        and r2_storage.R2_ENDPOINT_URL
        and r2_storage.R2_BUCKET_NAME
    )


def validate_image_bytes(data):
    """Return an error string when the bytes are not a picture that opens."""
    if not data or len(data) < 32:
        return 'file empty or cut off'
    if len(data) > _IMAGE_MAX_BYTES:
        return 'image larger than 40 MB'
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        return 'image cannot be opened (%s)' % exc
    return None


def validate_video_header(header, filename):
    """Return an error string when the start of the file is not a video."""
    blob = header or b''
    ext = os.path.splitext(filename or '')[1].lower()
    if len(blob) < 12:
        return 'video empty or cut off'
    if ext in ('.mp4', '.mov') or b'ftyp' in blob[:64]:
        if b'ftyp' not in blob[:64]:
            return 'video header missing'
        return None
    if ext == '.webm' or blob[:4] == b'\x1a\x45\xdf\xa3':
        if blob[:4] != b'\x1a\x45\xdf\xa3':
            return 'video header missing'
        return None
    return 'video header missing'


def validate_saved_file(path, file_type, filename):
    """Check a file already written to disk. Return an error string or None."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return 'file missing after save'
    if size <= 0:
        return 'file empty'
    kind = (file_type or '').strip().lower()
    if kind == 'video':
        with open(path, 'rb') as fp:
            header = fp.read(64)
        return validate_video_header(header, filename)
    with open(path, 'rb') as fp:
        data = fp.read(_IMAGE_MAX_BYTES + 1)
    return validate_image_bytes(data)


def _content_type(file_type, filename):
    ext = os.path.splitext(filename or '')[1].lower()
    if (file_type or '').strip().lower() == 'video' or ext in _VIDEO_EXT:
        return {
            '.mp4': 'video/mp4',
            '.webm': 'video/webm',
            '.mov': 'video/quicktime',
        }.get(ext, 'video/mp4')
    return {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
    }.get(ext, 'image/jpeg')


def _ext_for(file_type, filename):
    ext = os.path.splitext(secure_filename(filename or '') or '')[1].lower()
    kind = (file_type or '').strip().lower()
    if kind == 'video':
        return ext if ext in _VIDEO_EXT else '.mp4'
    return ext if ext in _IMAGE_EXT else '.jpg'


def _head_size(public_url):
    base = (r2_storage.R2_PUBLIC_URL or '').rstrip('/')
    if not public_url or not base or not public_url.startswith(base + '/'):
        raise RuntimeError('cloud url is not in this bucket')
    key = public_url[len(base) + 1:]
    client = r2_storage._get_s3_client()
    head = client.head_object(Bucket=r2_storage.R2_BUCKET_NAME, Key=key)
    return int(head['ContentLength'])


def _put_image_bytes(data, folder, filename):
    ext = _ext_for('image', filename)
    content_type = _content_type('image', filename)
    key = '%s/%s%s' % (folder.rstrip('/'), uuid.uuid4().hex, ext)
    client = r2_storage._get_s3_client()
    digest = hashlib.md5(data).digest()
    md5_b64 = base64.b64encode(digest).decode('ascii')
    try:
        client.put_object(
            Bucket=r2_storage.R2_BUCKET_NAME,
            Key=key,
            Body=data,
            ContentType=content_type,
            ContentMD5=md5_b64,
        )
    except Exception:
        client.put_object(
            Bucket=r2_storage.R2_BUCKET_NAME,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
    url = '%s/%s' % (r2_storage.R2_PUBLIC_URL.rstrip('/'), key)
    size = _head_size(url)
    if size != len(data):
        r2_storage.delete_file_by_url(url)
        raise RuntimeError('cloud size %s did not match %s' % (size, len(data)))
    return url


def _put_video_stream(file_storage, folder, filename, expected_size):
    url = r2_storage.upload_binary_file(
        file_storage,
        folder=folder,
        original_filename=filename,
    )
    if not url:
        raise RuntimeError('cloud video upload returned no url')
    size = _head_size(url)
    if size != int(expected_size):
        r2_storage.delete_file_by_url(url)
        raise RuntimeError('cloud size %s did not match %s' % (size, expected_size))
    return url


def _write_local(file_storage, upload_root, rel_prefix, original_name):
    fn = secure_filename(original_name or '') or 'file'
    base, ext = os.path.splitext(fn)
    if not base:
        base = 'file'
    unique = '%s_%s%s' % (base, datetime.now().strftime('%Y%m%d%H%M%S'), ext)
    subdir = os.path.join(upload_root, rel_prefix.replace('/', os.sep))
    os.makedirs(subdir, exist_ok=True)
    path = os.path.join(subdir, unique)
    file_storage.seek(0)
    file_storage.save(path)
    return path, '/'.join((rel_prefix.strip('/'), unique))


def store_verified_media(file_storage, file_type, original_name, folder, upload_root=None, rel_prefix=None):
    """Put a checked file on Cloudflare. Return the URL stored in the database.

    When R2 is not configured (local dev), write the same checked bytes under
    upload_root. A rejected file raises MediaRejected and is not stored.
    """
    if not file_storage:
        raise MediaRejected('empty upload')
    kind = (file_type or '').strip().lower()
    name = original_name or getattr(file_storage, 'filename', None) or 'file'
    file_storage.seek(0)
    if kind == 'video':
        stream = file_storage.stream
        stream.seek(0)
        header = stream.read(64)
        stream.seek(0, os.SEEK_END)
        expected = int(stream.tell() or 0)
        stream.seek(0)
        file_storage.seek(0)
        reason = validate_video_header(header, name)
        if reason:
            raise MediaRejected(reason)
        if expected <= 0:
            raise MediaRejected('video empty')
        if _r2_ready():
            return _put_video_stream(file_storage, folder, name, expected)
        if not upload_root or not rel_prefix:
            raise RuntimeError('R2 is not configured')
        path, rel = _write_local(file_storage, upload_root, rel_prefix, name)
        if os.path.getsize(path) != expected:
            try:
                os.remove(path)
            except OSError:
                pass
            raise MediaRejected('video cut off while saving')
        return rel

    data = file_storage.read()
    reason = validate_image_bytes(data)
    if reason:
        raise MediaRejected(reason)
    if _r2_ready():
        return _put_image_bytes(data, folder, name)
    if not upload_root or not rel_prefix:
        raise RuntimeError('R2 is not configured')
    file_storage.seek(0)
    path, rel = _write_local(file_storage, upload_root, rel_prefix, name)
    if os.path.getsize(path) != len(data):
        try:
            os.remove(path)
        except OSError:
            pass
        raise MediaRejected('image cut off while saving')
    return rel
