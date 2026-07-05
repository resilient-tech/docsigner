"""File-backed blob store with TTL sweep on access.

# ponytail: file-based sessions, swap for redis if multi-node
"""

import re
import secrets
import time
from pathlib import Path


class Missing(KeyError):
    pass


class Expired(KeyError):
    pass


_KEY_RE = re.compile(r"[A-Za-z0-9_-]+")


class FileStore:
    def __init__(self, directory, ttl_seconds: int):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds

    def put(self, data: bytes) -> str:
        key = secrets.token_urlsafe(24)  # 32 urlsafe chars
        (self.directory / key).write_bytes(data)
        self.sweep()
        return key

    def get(self, key: str) -> bytes:
        # Keys come from URLs; the pattern check keeps path tricks out.
        if not key or not _KEY_RE.fullmatch(key):
            raise Missing(key)
        path = self.directory / key
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            raise Missing(key) from None
        if self._expired(mtime):
            path.unlink(missing_ok=True)
            raise Expired(key)
        data = path.read_bytes()
        self.sweep()
        return data

    def delete(self, key: str) -> None:
        if key and _KEY_RE.fullmatch(key):
            (self.directory / key).unlink(missing_ok=True)

    def sweep(self) -> None:
        for path in self.directory.iterdir():
            try:
                if self._expired(path.stat().st_mtime):
                    path.unlink(missing_ok=True)
            except OSError:
                pass

    def _expired(self, mtime: float) -> bool:
        return time.time() - mtime > self.ttl_seconds
