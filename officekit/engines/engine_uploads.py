"""Bounded streaming reads and request-body guards for file-processing APIs."""

import json
from typing import Protocol


DEFAULT_API_REQUEST_BODY_LIMIT_BYTES = 8 * 1024 * 1024


class AsyncByteReader(Protocol):
    async def read(self, size: int = -1) -> bytes: ...


class UploadTooLargeError(ValueError):
    """The incoming file exceeded its configured processing limit."""


class RequestBodyLimitMiddleware:
    """Reject oversized HTTP bodies before multipart parsing spools uploaded files."""

    def __init__(self, app, path_limits: dict[str, int]):
        if any(type(limit) is not int or limit <= 0 for limit in path_limits.values()):
            raise ValueError("Request body limits must be positive integers")
        if any(
            any("*" in segment and segment != "*" for segment in path.split("/"))
            for path in path_limits
        ):
            raise ValueError("Request body path wildcards must occupy a full path segment")
        self.app = app
        self.path_limits = dict(path_limits)

    def _path_limit(self, path: str) -> int | None:
        exact = self.path_limits.get(path)
        if exact is not None:
            return exact
        path_parts = path.strip("/").split("/")
        for pattern, limit in self.path_limits.items():
            if "*" not in pattern:
                continue
            pattern_parts = pattern.strip("/").split("/")
            if len(pattern_parts) == len(path_parts) and all(
                expected == "*" or expected == actual
                for expected, actual in zip(pattern_parts, path_parts)
            ):
                return limit
        if path.startswith("/api/"):
            return DEFAULT_API_REQUEST_BODY_LIMIT_BYTES
        return None

    @staticmethod
    async def _reject(send, message: str) -> None:
        body = json.dumps({"detail": message}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body, "more_body": False})

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        limit = self._path_limit(scope.get("path", ""))
        if limit is None:
            await self.app(scope, receive, send)
            return

        headers = [(key.lower(), value) for key, value in scope.get("headers", ())]
        lengths = [value for key, value in headers if key == b"content-length"]
        transfer_encoded = any(key == b"transfer-encoding" for key, _ in headers)
        if len(lengths) > 1 or (lengths and transfer_encoded):
            await self._reject(send, "Request framing headers are invalid.")
            return
        raw_length = lengths[0] if lengths else None
        if raw_length is not None:
            if not raw_length or not raw_length.isdigit():
                await self._reject(send, "Content-Length header is invalid.")
                return
            try:
                declared_length = int(raw_length)
            except (TypeError, ValueError):
                await self._reject(send, "Content-Length header is invalid.")
                return
            if declared_length < 0:
                await self._reject(send, "Content-Length header is invalid.")
                return
            if declared_length > limit:
                await self._reject(send, "Request body exceeds the route upload limit.")
                return

        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise UploadTooLargeError("Request body exceeds the route upload limit.")
            return message

        response_started = False

        async def track_response(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, bounded_receive, track_response)
        except UploadTooLargeError:
            if not response_started:
                await self._reject(send, "Request body exceeds the route upload limit.")


async def read_bounded_upload(
    source: AsyncByteReader, max_bytes: int, chunk_size: int = 65_536
) -> bytes:
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("Upload limit must be a positive integer")
    if type(chunk_size) is not int or chunk_size <= 0:
        raise ValueError("Read chunk size must be a positive integer")

    output = bytearray()
    while True:
        remaining_with_overflow_probe = max_bytes + 1 - len(output)
        chunk = await source.read(min(chunk_size, remaining_with_overflow_probe))
        if not chunk:
            return bytes(output)
        if not isinstance(chunk, bytes):
            raise ValueError("Upload stream must return bytes")
        output.extend(chunk)
        if len(output) > max_bytes:
            raise UploadTooLargeError(f"File exceeds the {max_bytes}-byte processing limit")
