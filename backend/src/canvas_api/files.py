"""Where media files live, and the signed links that serve them.

Files are named by key, e.g. "assets/ast_x.png" or "global/gas_x.jpg":
- LocalFiles keeps them under a folder (data/assets, data/global), served by
  the API itself;
- GcsFiles keeps them in a Cloud Storage bucket; the API answers a media link
  with a redirect to a short-lived Cloud Storage link, so the bytes never pass
  through the API.

Media links carry a signature (see UrlSigner) instead of a sign-in header,
because <img> and <video> tags can't send one.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import logging
import secrets
import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

# Media never changes once written, so browsers may keep it for good.
IMMUTABLE = "private, max-age=31536000, immutable"


class FileMissing(Exception):
    """No file under that key."""


class Files(Protocol):
    def write(self, key: str, data: bytes, mime: str) -> None: ...

    def read(self, key: str) -> bytes: ...

    def copy(self, source: str, target: str) -> None: ...

    def delete(self, key: str) -> None:
        """Remove it; a missing file is fine."""
        ...

    def local_path(self, key: str) -> Path | None:
        """The file on disk, if files live on disk."""
        ...

    def download_url(self, key: str) -> str | None:
        """A short-lived direct link, if files live in a bucket."""
        ...


def delete_all(files: Files, keys: list[str]) -> None:
    for key in keys:
        try:
            files.delete(key)
        except Exception:  # noqa: BLE001 - a leftover file is not worth failing over
            log.warning("could not delete file %s", key, exc_info=True)


class LocalFiles:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError(f"bad file key {key!r}")
        return path

    def write(self, key: str, data: bytes, mime: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError as exc:
            raise FileMissing(key) from exc

    def copy(self, source: str, target: str) -> None:
        self.write(target, self.read(source), "")

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def local_path(self, key: str) -> Path | None:
        return self._path(key)

    def download_url(self, key: str) -> str | None:
        return None


class GcsFiles:
    """A Cloud Storage bucket. On Cloud Run, links are signed through the
    service account's IAM signBlob (it needs Service Account Token Creator on
    itself), since there is no private key file."""

    LINK_TTL = timedelta(hours=1)

    def __init__(self, bucket: str) -> None:
        import google.auth
        from google.auth.transport.requests import Request
        from google.cloud import storage

        self._request = Request()
        self._credentials, project = google.auth.default()
        self._bucket = storage.Client(credentials=self._credentials, project=project).bucket(
            bucket
        )
        self._lock = threading.Lock()

    def write(self, key: str, data: bytes, mime: str) -> None:
        blob = self._bucket.blob(key)
        blob.cache_control = IMMUTABLE
        blob.upload_from_string(data, content_type=mime)

    def read(self, key: str) -> bytes:
        from google.api_core.exceptions import NotFound

        try:
            return self._bucket.blob(key).download_as_bytes()
        except NotFound as exc:
            raise FileMissing(key) from exc

    def copy(self, source: str, target: str) -> None:
        """Server-side: the bytes never leave Cloud Storage."""
        from google.api_core.exceptions import NotFound

        try:
            self._bucket.copy_blob(self._bucket.blob(source), self._bucket, target)
        except NotFound as exc:
            raise FileMissing(source) from exc

    def delete(self, key: str) -> None:
        from google.api_core.exceptions import NotFound

        with contextlib.suppress(NotFound):
            self._bucket.blob(key).delete()

    def local_path(self, key: str) -> Path | None:
        return None

    def download_url(self, key: str) -> str | None:
        from google.oauth2 import service_account

        kwargs = {}
        if not isinstance(self._credentials, service_account.Credentials):
            # No private key here (Cloud Run): sign through IAM instead.
            with self._lock:
                if not self._credentials.valid:
                    self._credentials.refresh(self._request)
                kwargs = {
                    "service_account_email": self._credentials.service_account_email,
                    "access_token": self._credentials.token,
                }
        return self._bucket.blob(key).generate_signed_url(
            version="v4", expiration=self.LINK_TTL, method="GET", **kwargs
        )


class UrlSigner:
    """Signs media links: /api/<kind>/<id>/content?e=<expiry>&s=<signature>.

    The expiry is rounded to a day boundary (valid 1-2 days), so a link stays
    the same all day and browsers can cache what it points at.
    """

    DAY = 86400

    def __init__(self, secret: str) -> None:
        if not secret:
            # Fine for local work; links stop working when the API restarts.
            secret = secrets.token_urlsafe(32)
        self._key = secret.encode()

    def _sig(self, kind: str, id_: str, expires: int) -> str:
        msg = f"{kind}:{id_}:{expires}".encode()
        digest = hmac.new(self._key, msg, hashlib.sha256).digest()[:18]
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    def url(self, kind: str, id_: str) -> str:
        expires = (int(time.time()) // self.DAY + 2) * self.DAY
        return f"/api/{kind}/{id_}/content?e={expires}&s={self._sig(kind, id_, expires)}"

    def check(self, kind: str, id_: str, expires: int, sig: str) -> bool:
        if expires < time.time():
            return False
        return hmac.compare_digest(sig, self._sig(kind, id_, expires))


def make_files(storage: str, bucket: str, data_dir: Path) -> Files:
    if storage == "gcs":
        return GcsFiles(bucket)
    return LocalFiles(data_dir)
