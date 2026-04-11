"""
services/storage_service.py

Abstracts file storage so the rest of the app doesn't care whether
it's saving to disk or S3. Switch via STORAGE_BACKEND env var.
"""

import os
import shutil
from pathlib import Path
from uuid import uuid4
from typing import BinaryIO

from config import settings


def save_upload(file_obj: BinaryIO, original_filename: str) -> str:
    """
    Save an uploaded file. Returns a storage key (path or S3 key)
    that can be passed back to load_file() later.
    """
    suffix = Path(original_filename).suffix.lower()
    storage_key = f"{uuid4()}{suffix}"

    if settings.STORAGE_BACKEND == "s3":
        return _save_s3(file_obj, storage_key)
    return _save_local(file_obj, storage_key)


def load_file(storage_key: str) -> str:
    """
    Returns a local filesystem path to the file.
    For S3, downloads to a temp location first.
    """
    if settings.STORAGE_BACKEND == "s3":
        return _download_s3(storage_key)
    return _local_path(storage_key)


def delete_file(storage_key: str) -> None:
    if settings.STORAGE_BACKEND == "s3":
        _delete_s3(storage_key)
    else:
        path = _local_path(storage_key)
        if os.path.exists(path):
            os.remove(path)


# ── Local implementation ──────────────────────────────────────────────────────

def _local_path(storage_key: str) -> str:
    return os.path.join(settings.LOCAL_UPLOAD_DIR, storage_key)


def _save_local(file_obj: BinaryIO, storage_key: str) -> str:
    dest = _local_path(storage_key)
    os.makedirs(settings.LOCAL_UPLOAD_DIR, exist_ok=True)
    with open(dest, "wb") as f:
        shutil.copyfileobj(file_obj, f)
    return storage_key


# ── S3 implementation ─────────────────────────────────────────────────────────

def _get_s3_client():
    import boto3
    return boto3.client("s3", region_name=settings.AWS_REGION)


def _save_s3(file_obj: BinaryIO, storage_key: str) -> str:
    s3 = _get_s3_client()
    s3.upload_fileobj(file_obj, settings.AWS_S3_BUCKET, storage_key)
    return storage_key


def _download_s3(storage_key: str) -> str:
    """Download from S3 to /tmp and return local path."""
    import tempfile
    s3 = _get_s3_client()
    suffix = Path(storage_key).suffix
    tmp = tempfile.mktemp(suffix=suffix)
    s3.download_file(settings.AWS_S3_BUCKET, storage_key, tmp)
    return tmp


def _delete_s3(storage_key: str) -> None:
    s3 = _get_s3_client()
    s3.delete_object(Bucket=settings.AWS_S3_BUCKET, Key=storage_key)
