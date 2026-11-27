"""Bounded upload-reader edge cases without a web framework dependency."""

import unittest

from officekit.engines.engine_uploads import RequestBodyLimitMiddleware, UploadTooLargeError, read_bounded_upload


class FakeAsyncReader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0
        self.requested_sizes = []

    async def read(self, size=-1):
        self.requested_sizes.append(size)
        if self.offset >= len(self.data):
            return b""
        end = len(self.data) if size < 0 else self.offset + size
        chunk = self.data[self.offset:end]
        self.offset += len(chunk)
        return chunk


class BoundedUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_upload_in_bounded_chunks(self):
        source = FakeAsyncReader(b"abcdefghij")
        result = await read_bounded_upload(source, max_bytes=10, chunk_size=4)
        self.assertEqual(result, b"abcdefghij")
        self.assertLessEqual(max(source.requested_sizes), 4)

    async def test_rejects_one_byte_over_limit_with_bounded_overread(self):
        source = FakeAsyncReader(b"x" * 11)
        with self.assertRaises(UploadTooLargeError):
            await read_bounded_upload(source, max_bytes=10, chunk_size=4)
        self.assertLessEqual(source.offset, 11)
        self.assertLessEqual(max(source.requested_sizes), 4)

    async def test_accepts_empty_and_exact_limit_files(self):
        self.assertEqual(await read_bounded_upload(FakeAsyncReader(b""), 1), b"")
        self.assertEqual(await read_bounded_upload(FakeAsyncReader(b"1234"), 4), b"1234")

    async def test_rejects_invalid_limits_and_non_byte_streams(self):
        for limit in (0, -1, 1.5, True):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                await read_bounded_upload(FakeAsyncReader(b""), limit)

        class BadReader:
            async def read(self, size=-1):
                return "not bytes"

        with self.assertRaises(ValueError):
            await read_bounded_upload(BadReader(), 5)


class RequestBodyLimitTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, scope, messages, limit=5):
        received = []
        sent = []
        pending = iter(messages)

        async def receive():
            message = next(pending, {"type": "http.request", "body": b"", "more_body": False})
            received.append(message)
            return message

        async def send(message):
            sent.append(message)

        async def app(inner_scope, inner_receive, inner_send):
            body = bytearray()
            while True:
                message = await inner_receive()
                body.extend(message.get("body", b""))
                if not message.get("more_body", False):
                    break
            await inner_send({"type": "http.response.start", "status": 200, "headers": []})
            await inner_send({"type": "http.response.body", "body": bytes(body)})

        middleware = RequestBodyLimitMiddleware(
            app,
            {
                "/upload": limit,
                **{
                    f"/api/workspaces/*/{route}": limit
                    for route in (
                        "extractions",
                        "hash-reports",
                        "file-type-reports",
                        "folder-comparisons",
                        "rename-previews",
                        "renamed-artifacts",
                        "splits",
                        "joins",
                        "duplicate-reports",
                        "storage-reports",
                        "similar-image-reports",
                    )
                },
            },
        )
        await middleware(scope, receive, send)
        status = next(message["status"] for message in sent if message["type"] == "http.response.start")
        return status, received, sent

    async def test_rejects_oversized_declared_body_before_reading_it(self):
        scope = {"type": "http", "path": "/upload", "headers": [(b"content-length", b"6")]}
        status, received, sent = await self.invoke(scope, [])
        self.assertEqual(status, 413)
        self.assertEqual(received, [])
        self.assertIn(b"route upload limit", sent[1]["body"])

    async def test_rejects_chunked_body_when_no_content_length_is_present(self):
        scope = {"type": "http", "path": "/upload", "headers": []}
        messages = [
            {"type": "http.request", "body": b"123", "more_body": True},
            {"type": "http.request", "body": b"456", "more_body": False},
        ]
        status, received, _ = await self.invoke(scope, messages)
        self.assertEqual(status, 413)
        self.assertEqual(len(received), 2)

    async def test_allows_exact_limit_and_unconfigured_paths(self):
        scope = {"type": "http", "path": "/upload", "headers": [(b"content-length", b"5")]}
        exact, _, sent = await self.invoke(
            scope, [{"type": "http.request", "body": b"12345", "more_body": False}]
        )
        self.assertEqual(exact, 200)
        self.assertEqual(sent[-1]["body"], b"12345")

        leading_zero_length, _, _ = await self.invoke(
            {"type": "http", "path": "/upload", "headers": [(b"content-length", b"0005")]},
            [{"type": "http.request", "body": b"12345", "more_body": False}],
        )
        self.assertEqual(leading_zero_length, 200)

        unconfigured, _, _ = await self.invoke(
            {"type": "http", "path": "/other", "headers": []},
            [{"type": "http.request", "body": b"123456", "more_body": False}],
        )
        self.assertEqual(unconfigured, 200)

    async def test_unlisted_api_routes_are_bounded_before_body_reading(self):
        status, received, _ = await self.invoke(
            {
                "type": "http",
                "path": "/api/future-json-tool",
                "headers": [(b"content-length", str(8 * 1024 * 1024 + 1).encode("ascii"))],
            },
            [],
        )
        self.assertEqual(status, 413)
        self.assertEqual(received, [])

    async def test_explicit_upload_limits_override_the_api_default(self):
        middleware = RequestBodyLimitMiddleware(
            lambda *_: None,
            {"/api/large-upload": 32 * 1024 * 1024},
        )
        self.assertEqual(middleware._path_limit("/api/large-upload"), 32 * 1024 * 1024)
        self.assertEqual(middleware._path_limit("/api/new-json-tool"), 8 * 1024 * 1024)
        self.assertIsNone(middleware._path_limit("/large-upload"))

    async def test_matches_single_dynamic_workspace_segment_for_body_limit(self):
        workspace_id = "a" * 32
        for route in (
            "extractions",
            "hash-reports",
            "file-type-reports",
            "folder-comparisons",
            "rename-previews",
            "renamed-artifacts",
            "splits",
            "joins",
            "duplicate-reports",
            "storage-reports",
            "similar-image-reports",
        ):
            with self.subTest(route=route):
                workspace_path = f"/api/workspaces/{workspace_id}/{route}"
                status, received, _ = await self.invoke(
                    {"type": "http", "path": workspace_path, "headers": [(b"content-length", b"6")]},
                    [],
                )
                self.assertEqual(status, 413)
                self.assertEqual(received, [])

        workspace_path = f"/api/workspaces/{workspace_id}/hash-reports"
        wrong_depth, _, _ = await self.invoke(
            {
                "type": "http",
                "path": workspace_path + "/extra",
                "headers": [(b"content-length", b"6")],
            },
            [],
        )
        self.assertEqual(wrong_depth, 200)

    async def test_rejects_invalid_content_length_and_configuration(self):
        invalid_headers = (
            [(b"content-length", b"bad")],
            [(b"content-length", b"+1")],
            [(b"content-length", b" 1")],
            [(b"content-length", b"1 ")],
            [(b"content-length", b"-1")],
            [(b"content-length", b"1"), (b"content-length", b"1")],
            [(b"content-length", b"1"), (b"transfer-encoding", b"chunked")],
        )
        for headers in invalid_headers:
            with self.subTest(headers=headers):
                scope = {"type": "http", "path": "/upload", "headers": headers}
                status, _, _ = await self.invoke(scope, [])
                self.assertEqual(status, 413)

        with self.assertRaises(ValueError):
            RequestBodyLimitMiddleware(lambda *_: None, {"/upload": True})
        with self.assertRaises(ValueError):
            RequestBodyLimitMiddleware(lambda *_: None, {"/api/*workspace/hash": 5})


if __name__ == "__main__":
    unittest.main()
