"""Public HTTPS media import with DNS pinning, strict redirects, and one-use grants."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
import ipaddress
import os
from pathlib import PurePosixPath
import re
import socket
import time
import threading
from typing import Callable
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
import uuid

import aiohttp


MAX_MEDIA_IMPORT_BYTES = 64 * 1024 * 1024
MAX_MEDIA_IMPORT_URL_LENGTH = 2048
MAX_MEDIA_IMPORT_REDIRECTS = 3
MAX_MEDIA_IMPORT_SECONDS = 15
MEDIA_IMPORT_TTL_SECONDS = 300
MEDIA_IMPORT_CHUNK_BYTES = 256 * 1024
MAX_PREVIEWS_PER_MINUTE = 10

CONTENT_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/bmp": "bmp",
    "image/tiff": "tiff",
    "image/gif": "gif",
    "image/x-icon": "ico",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/x-m4v": "m4v",
    "video/m4v": "m4v",
    "video/webm": "webm",
    "video/x-matroska": "mkv",
    "video/x-msvideo": "avi",
    "application/pdf": "pdf",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "application/x-m4a": "m4a",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/aiff": "aiff",
    "audio/x-aiff": "aiff",
    "audio/flac": "flac",
    "audio/ogg": "ogg",
    "audio/opus": "opus",
}
EXTENSION_TYPES = {extension: content_type for content_type, extension in CONTENT_TYPES.items()}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class MediaImportUnavailableError(RuntimeError):
    """The requested import operation is unavailable or no longer valid."""


class MediaImportUnsafeTargetError(PermissionError):
    """The URL or a redirect resolves to a non-public destination."""


class MediaImportTooLargeError(ValueError):
    """The remote media exceeds the bounded import size."""


class MediaImportCancelledError(RuntimeError):
    """An active media download was cancelled."""


class MediaImportRejectedError(ValueError):
    """The remote target or response does not match supported media policy."""


class MediaImportRemoteUnavailableError(RuntimeError):
    """The public host could not be reached before its bounded request timeout."""


@dataclass(frozen=True)
class RemoteMedia:
    host: str
    content_type: str
    size_bytes: int | None
    filename: str
    final_url: str = field(repr=False)


@dataclass(frozen=True)
class MediaImportGrant:
    url: str = field(repr=False)
    host: str
    content_type: str
    size_bytes: int | None
    filename: str
    expires: float


class PinnedAddressResolver(aiohttp.abc.AbstractResolver):
    """Return only the IP addresses validated immediately before connection."""

    def __init__(self, addresses):
        self.addresses = tuple(addresses)

    async def resolve(self, host, port=0, family=socket.AF_INET):
        results = []
        for raw_address in self.addresses:
            address = ipaddress.ip_address(raw_address)
            if not _is_public_address(address):
                raise OSError("Only validated public addresses may be connected")
            address_family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
            if family not in (socket.AF_UNSPEC, address_family):
                continue
            results.append({
                "hostname": host,
                "host": str(address),
                "port": port,
                "family": address_family,
                "proto": 0,
                "flags": socket.AI_NUMERICHOST,
            })
        if not results:
            raise OSError("No validated address for this host")
        return results

    async def close(self):
        return None


class SafePublicUrlTransport:
    """HTTPS client that pins each redirect hop to its validated public DNS answers."""

    def __init__(self, lookup: Callable | None = None, timeout_seconds=MAX_MEDIA_IMPORT_SECONDS):
        self.lookup = lookup or self._lookup_system
        self.timeout_seconds = timeout_seconds

    async def preview(self, url: str):
        result, _body = await self._request(url, preview=True)
        return result

    async def download(self, grant: MediaImportGrant, cancel_event=None):
        result, body = await self._request(grant.url, preview=False, cancel_event=cancel_event)
        self._verify_grant(grant, result)
        return body, result.filename, result.content_type

    async def download_to_file(self, grant: MediaImportGrant, destination, cancel_event=None):
        result, _body = await self._request(
            grant.url, preview=False, cancel_event=cancel_event, output_path=destination,
        )
        try:
            self._verify_grant(grant, result)
            return result.filename, result.content_type, result.size_bytes
        except Exception:
            try:
                os.unlink(destination)
            except OSError:
                pass
            raise

    @staticmethod
    def _verify_grant(grant, result):
        if (
            result.host != grant.host
            or result.content_type != grant.content_type
            or result.filename != grant.filename
        ):
            raise MediaImportRejectedError("The media response changed after preview. Preview the URL again.")
        if grant.size_bytes is not None and result.size_bytes != grant.size_bytes:
            raise MediaImportRejectedError("The media size changed after preview. Preview the URL again.")

    async def _request(self, url, preview, cancel_event=None, output_path=None):
        current_url = validate_public_https_url(url)
        for redirect_count in range(MAX_MEDIA_IMPORT_REDIRECTS + 1):
            if cancel_event is not None and cancel_event.is_set():
                raise MediaImportCancelledError()
            parsed = urlsplit(current_url)
            addresses = await self._resolve_public(parsed.hostname)
            resolver = PinnedAddressResolver(addresses)
            timeout = aiohttp.ClientTimeout(total=self.timeout_seconds, connect=5, sock_read=5)
            connector = aiohttp.TCPConnector(resolver=resolver, use_dns_cache=False, limit=1)
            output_stream = None
            output_created = False
            download_complete = False
            try:
                async with aiohttp.ClientSession(
                    connector=connector,
                    timeout=timeout,
                    cookie_jar=aiohttp.DummyCookieJar(),
                    trust_env=False,
                    auto_decompress=False,
                    headers={"User-Agent": "OfficeKit-Media-Import/1", "Accept-Encoding": "identity"},
                ) as session:
                    async with session.get(
                        current_url,
                        allow_redirects=False,
                        headers={"Range": "bytes=0-0"} if preview else {},
                        ssl=True,
                    ) as response:
                        if response.status in REDIRECT_STATUSES:
                            location = response.headers.get("Location")
                            if not location or redirect_count >= MAX_MEDIA_IMPORT_REDIRECTS:
                                raise MediaImportRejectedError("The URL has too many or invalid redirects.")
                            current_url = validate_public_https_url(urljoin(current_url, location))
                            continue
                        if response.status not in ({200, 206} if preview else {200}):
                            raise MediaImportRejectedError("The remote server did not provide a supported media file.")
                        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                            raise MediaImportRejectedError("Compressed HTTP responses are not accepted for media import.")
                        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                        filename = safe_media_filename(current_url, content_type)
                        content_type = supported_content_type(content_type, filename)
                        size_bytes = _response_size(response.headers, response.status)
                        if size_bytes is not None and size_bytes > MAX_MEDIA_IMPORT_BYTES:
                            raise MediaImportTooLargeError()
                        if preview:
                            await response.content.read(1)
                            return RemoteMedia(parsed.hostname, content_type, size_bytes, filename, current_url), b""
                        body = bytearray() if output_path is None else None
                        output_stream = open(output_path, "xb") if output_path is not None else None
                        output_created = output_stream is not None
                        received = 0
                        async for chunk in response.content.iter_chunked(MEDIA_IMPORT_CHUNK_BYTES):
                            if cancel_event is not None and cancel_event.is_set():
                                if output_stream is not None:
                                    output_stream.close()
                                raise MediaImportCancelledError()
                            received += len(chunk)
                            if received > MAX_MEDIA_IMPORT_BYTES:
                                if output_stream is not None:
                                    output_stream.close()
                                raise MediaImportTooLargeError()
                            if output_stream is None:
                                body.extend(chunk)
                            else:
                                output_stream.write(chunk)
                        if output_stream is not None:
                            output_stream.flush()
                            os.fsync(output_stream.fileno())
                            output_stream.close()
                        if received == 0:
                            raise MediaImportRejectedError("The remote media file is empty.")
                        if size_bytes is not None and received != size_bytes:
                            raise MediaImportRejectedError("The media response length did not match its headers.")
                        final_host = urlsplit(current_url).hostname
                        download_complete = True
                        return RemoteMedia(final_host, content_type, received, filename, current_url), bytes(body) if body is not None else b""
            except (MediaImportUnsafeTargetError, MediaImportTooLargeError, MediaImportRejectedError, MediaImportCancelledError):
                raise
            except asyncio.TimeoutError:
                raise MediaImportRemoteUnavailableError() from None
            except FileExistsError:
                raise
            except (aiohttp.ClientError, OSError):
                raise MediaImportRemoteUnavailableError() from None
            finally:
                if output_stream is not None and not output_stream.closed:
                    output_stream.close()
                if output_created and not download_complete:
                    try:
                        os.unlink(output_path)
                    except OSError:
                        pass
        raise MediaImportRejectedError("The URL has too many redirects.")

    async def _resolve_public(self, host):
        try:
            addresses = await self.lookup(host)
        except Exception:
            raise MediaImportUnsafeTargetError("The media host could not be resolved as a public address.") from None
        normalized = set()
        for raw in addresses:
            try:
                address = ipaddress.ip_address(raw)
            except ValueError:
                raise MediaImportUnsafeTargetError("The media host resolved to an invalid address.") from None
            if not _is_public_address(address):
                raise MediaImportUnsafeTargetError("The media host must resolve only to public addresses.")
            normalized.add(address.compressed)
        if not normalized:
            raise MediaImportUnsafeTargetError("The media host has no public address.")
        return tuple(sorted(normalized))

    @staticmethod
    async def _lookup_system(host):
        loop = asyncio.get_running_loop()
        records = await loop.getaddrinfo(host, 443, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
        return tuple(record[4][0] for record in records)


class MediaImportStore:
    """Short-lived preview grants consumed once by a queued local media job."""

    def __init__(self, transport=None, clock=time.monotonic):
        self.transport = transport or SafePublicUrlTransport()
        self.clock = clock
        self.grants: dict[str, MediaImportGrant] = {}
        self.lock = threading.RLock()
        self.preview_timestamps = deque()

    async def preview(self, url: str):
        canonical = validate_public_https_url(url)
        now = self.clock()
        with self.lock:
            while self.preview_timestamps and self.preview_timestamps[0] <= now - 60:
                self.preview_timestamps.popleft()
            if len(self.preview_timestamps) >= MAX_PREVIEWS_PER_MINUTE:
                raise MediaImportUnavailableError("Too many URL previews. Wait a minute and try again.")
            self.preview_timestamps.append(now)
        remote = await self.transport.preview(canonical)
        grant_id = str(uuid.uuid4())
        expires = self.clock() + MEDIA_IMPORT_TTL_SECONDS
        with self.lock:
            self._prune()
            if len(self.grants) >= MAX_PREVIEWS_PER_MINUTE * 5:
                raise MediaImportUnavailableError("Too many active URL previews. Wait for one to expire.")
            self.grants[grant_id] = MediaImportGrant(
                url=canonical,
                host=remote.host,
                content_type=remote.content_type,
                size_bytes=remote.size_bytes,
                filename=remote.filename,
                expires=expires,
            )
        return {
            "importId": grant_id,
            "host": remote.host,
            "contentType": remote.content_type,
            "sizeBytes": remote.size_bytes,
            "filename": remote.filename,
            "expiresInSeconds": MEDIA_IMPORT_TTL_SECONDS,
        }

    def claim(self, import_id: str):
        with self.lock:
            self._prune()
            try:
                canonical = str(uuid.UUID(import_id))
            except (ValueError, TypeError, AttributeError):
                raise FileNotFoundError("Media import preview is unavailable") from None
            grant = self.grants.pop(canonical, None)
            if grant is None or grant.expires <= self.clock():
                raise FileNotFoundError("Media import preview is unavailable")
            return grant

    def download(self, grant: MediaImportGrant, cancel_event=None):
        return asyncio.run(self.transport.download(grant, cancel_event))

    def download_to_file(self, grant: MediaImportGrant, destination, cancel_event=None):
        downloader = getattr(self.transport, "download_to_file", None)
        if downloader is None:
            content, filename, content_type = self.download(grant, cancel_event)
            if len(content) > MAX_MEDIA_IMPORT_BYTES:
                raise MediaImportTooLargeError()
            with open(destination, "xb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            return filename, content_type, len(content)
        return asyncio.run(downloader(grant, destination, cancel_event))

    def _prune(self):
        now = self.clock()
        for grant_id, grant in tuple(self.grants.items()):
            if grant.expires <= now:
                del self.grants[grant_id]

    def close(self):
        with self.lock:
            self.grants.clear()
            self.preview_timestamps.clear()


def validate_public_https_url(value: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_MEDIA_IMPORT_URL_LENGTH:
        raise MediaImportRejectedError("Enter an HTTPS media URL up to 2048 characters.")
    if any(ord(char) < 0x21 or ord(char) == 0x7F for char in value):
        raise MediaImportRejectedError("The media URL contains invalid characters.")
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() != "https" or parsed.username is not None or parsed.password is not None:
            raise MediaImportRejectedError("Media import accepts credential-free HTTPS URLs only.")
        if parsed.port not in (None, 443):
            raise MediaImportRejectedError("Media import accepts HTTPS on port 443 only.")
        host = parsed.hostname
        if not host:
            raise MediaImportRejectedError("The media URL has no host.")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            host = host.rstrip(".").encode("idna").decode("ascii").lower()
            if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".home", ".test", ".invalid")):
                raise MediaImportUnsafeTargetError("The media URL must use a public host.")
        else:
            if not _is_public_address(address):
                raise MediaImportUnsafeTargetError("The media URL must use a public host.")
            host = address.compressed
        authority_host = f"[{host}]" if ":" in host else host
        netloc = authority_host
        if parsed.port not in (None, 443):
            netloc += f":{parsed.port}"
        path = quote(unquote(parsed.path or "/"), safe="/%:@!$&'()*+,;=-._~")
        query = quote(unquote(parsed.query), safe="/?@!$&'()*+,;=:-._~%")
        return urlunsplit(("https", netloc, path, query, ""))
    except MediaImportUnsafeTargetError:
        raise
    except MediaImportRejectedError:
        raise
    except (UnicodeError, ValueError):
        raise MediaImportRejectedError("The media URL is invalid.") from None


def supported_content_type(content_type: str, filename: str):
    if content_type in CONTENT_TYPES:
        return content_type
    extension = PurePosixPath(filename).suffix.lower().lstrip(".")
    inferred = EXTENSION_TYPES.get(extension)
    if content_type in {"application/octet-stream", "binary/octet-stream", ""} and inferred:
        return inferred
    raise MediaImportRejectedError("The URL does not identify a supported image, video, PDF, or audio file.")


def safe_media_filename(url: str, content_type: str):
    path_name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    name = PurePosixPath(path_name).name
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._-")[:160]
    extension = PurePosixPath(name).suffix.lower().lstrip(".")
    if extension not in EXTENSION_TYPES:
        extension = CONTENT_TYPES.get(content_type.lower().split(";", 1)[0], "")
        base = PurePosixPath(name).stem[:120] or "imported-media"
        name = f"{base}.{extension}" if extension else "imported-media"
    return name or "imported-media"


def _response_size(headers, status):
    raw_length = headers.get("Content-Length")
    size = None
    if raw_length is not None:
        try:
            size = int(raw_length)
        except (TypeError, ValueError):
            raise MediaImportRejectedError("The server returned an invalid media length.") from None
        if size < 0:
            raise MediaImportRejectedError("The server returned an invalid media length.")
    content_range = headers.get("Content-Range", "")
    match = re.search(r"/([0-9]+|\*)\s*$", content_range)
    if status == 206:
        size = int(match.group(1)) if match and match.group(1) != "*" else None
    return size


def _is_public_address(address):
    if not address.is_global or address.is_multicast or address.is_unspecified or address.is_loopback:
        return False
    if address.version == 4:
        return True
    local_nat64 = ipaddress.ip_network("64:ff9b:1::/48")
    well_known_nat64 = ipaddress.ip_network("64:ff9b::/96")
    if address in local_nat64:
        return False
    embedded = []
    if address.ipv4_mapped:
        embedded.append(address.ipv4_mapped)
    if address.sixtofour:
        embedded.append(address.sixtofour)
    if address.teredo:
        embedded.extend(address.teredo)
    if address in well_known_nat64:
        embedded.append(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
    return all(item.is_global for item in embedded)
