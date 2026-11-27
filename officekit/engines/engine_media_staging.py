"""Short-lived private staging for explicit Screenshot Editor handoffs."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import stat
import tempfile
import threading
import time
import uuid

from PIL import Image, UnidentifiedImageError

from .engine_conversion_errors import ConversionInputError


MAX_STAGED_IMAGE_BYTES = 64 * 1024 * 1024
MAX_STAGED_IMAGE_PIXELS = 40_000_000
STAGED_IMAGE_TTL = 300
MAX_STAGED_IMAGES = 5
_FORMATS = {"PNG": ("png", "image/png"), "JPEG": ("jpg", "image/jpeg"), "WEBP": ("webp", "image/webp")}


class StagedImageUnavailableError(FileNotFoundError):
    """The image staging grant expired, was consumed, or is unknown."""


class StagedImageTooLargeError(ValueError):
    """The image exceeds the bounded staging size."""


class StagedImageCapacityError(RuntimeError):
    """The short-lived edited-image staging area is full."""


class StagedImageConflictError(RuntimeError):
    """The image grant has already been consumed by a job."""


@dataclass(frozen=True)
class StagedImageGrant:
    id: str
    path: str
    filename: str
    size_bytes: int
    device: int
    inode: int
    max_bytes: int = MAX_STAGED_IMAGE_BYTES


class MediaStagingStore:
    """Stores an explicit edited image in an app-private directory for one job."""

    def __init__(self, clock=time.monotonic, root=None, max_image_bytes=None, max_images=None):
        self.clock = clock
        self.max_image_bytes = max_image_bytes
        self.max_images = max_images
        self.root = root or tempfile.mkdtemp(prefix="officekit-media-staging-")
        os.makedirs(self.root, mode=0o700, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.records = {}
        self.lock = threading.RLock()
        self._stop_cleanup = threading.Event()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="officekit-media-image-staging-cleanup",
            daemon=True,
        )
        self._cleanup_thread.start()

    async def create(self, upload, raw_filename):
        maximum_bytes = self.max_image_bytes or MAX_STAGED_IMAGE_BYTES
        grant_id = str(uuid.uuid4())
        safe_name = _safe_stem(raw_filename)
        path = os.path.join(self.root, f"{grant_id}.upload")
        size_bytes = 0
        stored = False
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as destination:
                while chunk := await upload.read(1024 * 1024):
                    size_bytes += len(chunk)
                    if size_bytes > maximum_bytes:
                        raise StagedImageTooLargeError()
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())
                _image_format, extension, media_type, width, height = _inspect_image(path)
            final_path = os.path.join(self.root, f"{grant_id}.{extension}")
            os.replace(path, final_path)
            metadata = os.stat(final_path, follow_symlinks=False)
            record = StagedImageGrant(
                grant_id, final_path, f"{safe_name}.{extension}", size_bytes,
                metadata.st_dev, metadata.st_ino, maximum_bytes,
            )
            with self.lock:
                self._prune()
                if len(self.records) >= (self.max_images or MAX_STAGED_IMAGES):
                    raise StagedImageCapacityError()
                self.records[grant_id] = (record, self.clock() + STAGED_IMAGE_TTL, False)
            stored = True
            return {
                "stagingId": grant_id,
                "filename": record.filename,
                "sizeBytes": size_bytes,
                "mediaType": media_type,
                "width": width,
                "height": height,
                "expiresInSeconds": STAGED_IMAGE_TTL,
            }
        except StagedImageTooLargeError:
            raise
        except (ConversionInputError, StagedImageUnavailableError):
            raise
        except OSError:
            raise ConversionInputError() from None
        finally:
            try:
                await upload.close()
            except Exception:
                pass
            if not stored:
                for candidate in (path, locals().get("final_path")):
                    if candidate:
                        _unlink(candidate)

    def claim(self, grant_id):
        try:
            canonical = str(uuid.UUID(grant_id))
        except (ValueError, TypeError, AttributeError):
            raise StagedImageUnavailableError() from None
        with self.lock:
            self._prune()
            entry = self.records.get(canonical)
            if entry is None or entry[2]:
                raise StagedImageUnavailableError()
            self.records[canonical] = (entry[0], entry[1], True)
            return entry[0]

    def read(self, grant):
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(grant.path, flags)
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_dev != grant.device
                or metadata.st_ino != grant.inode
                or metadata.st_size != grant.size_bytes
                or metadata.st_size > grant.max_bytes
            ):
                os.close(descriptor)
                raise StagedImageUnavailableError()
            chunks = []
            remaining = grant.max_bytes
            with os.fdopen(descriptor, "rb") as source:
                while chunk := source.read(min(1024 * 1024, remaining + 1)):
                    remaining -= len(chunk)
                    if remaining < 0:
                        raise StagedImageTooLargeError()
                    chunks.append(chunk)
            data = b"".join(chunks)
            if len(data) != grant.size_bytes:
                raise StagedImageUnavailableError()
            return data
        except (StagedImageUnavailableError, StagedImageTooLargeError):
            raise
        except OSError:
            raise StagedImageUnavailableError() from None

    def discard(self, grant_id):
        try:
            canonical = str(uuid.UUID(grant_id))
        except (ValueError, TypeError, AttributeError):
            raise StagedImageUnavailableError() from None
        with self.lock:
            self._prune()
            entry = self.records.get(canonical)
            if entry is None:
                raise StagedImageUnavailableError()
            if entry[2]:
                raise StagedImageConflictError()
            self.records.pop(canonical, None)
        _unlink(entry[0].path)

    def release(self, grant):
        with self.lock:
            self.records.pop(grant.id, None)
        _unlink(grant.path)

    def _prune(self):
        now = self.clock()
        for grant_id, (grant, expires, claimed) in tuple(self.records.items()):
            if expires <= now and not claimed:
                self.records.pop(grant_id, None)
                _unlink(grant.path)

    def _cleanup_loop(self):
        while not self._stop_cleanup.wait(15):
            with self.lock:
                self._prune()

    def close(self):
        self._stop_cleanup.set()
        self._cleanup_thread.join(timeout=1)
        with self.lock:
            self.records.clear()
        shutil.rmtree(self.root, ignore_errors=True)


def _inspect_image(path):
    try:
        with Image.open(path) as image:
            format_name = (image.format or "").upper()
            info = _FORMATS.get(format_name)
            width, height = image.size
            if (
                info is None or width < 1 or height < 1
                or width > 10_000 or height > 10_000
                or width * height > MAX_STAGED_IMAGE_PIXELS
                or getattr(image, "n_frames", 1) != 1
            ):
                raise ConversionInputError()
            image.verify()
            return format_name, info[0], info[1], width, height
    except ConversionInputError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        raise ConversionInputError() from None


def _safe_stem(filename):
    if not isinstance(filename, str) or len(filename) > 255:
        return "screenshot"
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    stem = Path(name).stem
    safe = "".join(character for character in stem if character.isalnum() or character in " _.-")
    safe = safe.strip(" .")[:100]
    return safe or "screenshot"


def _unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass
