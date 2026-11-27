import asyncio
from io import BytesIO
import socket
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from officekit.engines.engine_file_selections import FileSelectionStore
from officekit.engines.engine_media_import import (
    MAX_PREVIEWS_PER_MINUTE,
    MEDIA_IMPORT_TTL_SECONDS,
    MediaImportCancelledError,
    MediaImportRejectedError,
    MediaImportStore,
    MediaImportTooLargeError,
    MediaImportUnavailableError,
    MediaImportUnsafeTargetError,
    PinnedAddressResolver,
    RemoteMedia,
    SafePublicUrlTransport,
    safe_media_filename,
    supported_content_type,
    validate_public_https_url,
)
from officekit.engines.engine_media_jobs import MediaJobStore
from officekit.media_routes import create_media_router


class ImmediateExecutor:
    def submit(self, function, *args):
        function(*args)

    def shutdown(self, **_kwargs):
        return None


class StubTransport:
    def __init__(self, content):
        self.content = content
        self.urls = []

    async def preview(self, url):
        self.urls.append(url)
        return RemoteMedia("media.example", "image/png", len(self.content), "source.png", url)

    async def download(self, grant, cancel_event=None):
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("cancelled")
        self.urls.append(grant.url)
        return self.content, "source.png", "image/png"


def png_bytes():
    output = BytesIO()
    Image.new("RGB", (80, 60), (12, 34, 56)).save(output, format="PNG")
    return output.getvalue()


def test_public_url_validation_canonicalizes_hosts_and_rejects_unsafe_authority():
    assert validate_public_https_url("HTTPS://ExAmPlE.com:443/a%20b.png?key=1#ignored") == "https://example.com/a%20b.png?key=1"
    assert validate_public_https_url("https://bücher.example/a.png").startswith("https://xn--bcher-kva.example/")
    for url in (
        "http://example.com/image.png",
        "https://user:password@example.com/image.png",
        "https://example.com:8443/image.png",
        "https://localhost/image.png",
        "https://127.0.0.1/image.png",
        "https://[::1]/image.png",
        "https://device.local/image.png",
        "https://example.com/a\n.png",
    ):
        with pytest.raises((MediaImportRejectedError, MediaImportUnsafeTargetError)):
            validate_public_https_url(url)


def test_pinned_resolver_returns_only_validated_addresses_and_filters_address_family():
    resolver = PinnedAddressResolver(["8.8.8.8", "2606:4700:4700::1111"])
    v4 = asyncio.run(resolver.resolve("media.example", 443, socket.AF_INET))
    v6 = asyncio.run(resolver.resolve("media.example", 443, socket.AF_INET6))
    assert [entry["host"] for entry in v4] == ["8.8.8.8"]
    assert [entry["host"] for entry in v6] == ["2606:4700:4700::1111"]
    with pytest.raises(OSError):
        asyncio.run(PinnedAddressResolver(["8.8.8.8"]).resolve("media.example", 443, socket.AF_INET6))


def test_transport_rejects_any_private_dns_answer_even_when_public_answer_is_present():
    async def mixed_lookup(_host):
        return ["8.8.8.8", "10.0.0.4"]

    transport = SafePublicUrlTransport(lookup=mixed_lookup)
    with pytest.raises(MediaImportUnsafeTargetError):
        asyncio.run(transport._resolve_public("media.example"))


@pytest.mark.parametrize("address", [
    "::ffff:127.0.0.1",
    "64:ff9b::7f00:1",
    "2002:7f00:1::",
    "2001:0:4136:e378:8000:63bf:3fff:fdd2",
    "64:ff9b:1::808:808",
])
def test_transport_rejects_ipv6_transition_addresses_that_embed_non_public_ipv4(address):
    async def lookup(_host):
        return [address]

    transport = SafePublicUrlTransport(lookup=lookup)
    with pytest.raises(MediaImportUnsafeTargetError):
        asyncio.run(transport._resolve_public("media.example"))


def test_https_transport_revalidates_and_pins_each_redirect_hop(monkeypatch):
    pinned = []
    requests = []
    responses = [
        {"status": 302, "headers": {"Location": "https://cdn.example/photo.png"}},
        {"status": 206, "headers": {
            "Content-Type": "image/png",
            "Content-Length": "1",
            "Content-Range": "bytes 0-0/256",
        }},
    ]

    class FakeConnector:
        def __init__(self, resolver, **_kwargs):
            self.resolver = resolver

    class FakeContent:
        async def read(self, _limit):
            return b"x"

        async def iter_chunked(self, _size):
            yield b"png-content"

    class FakeResponse:
        def __init__(self, response, resolver, host):
            self.status = response["status"]
            self.headers = response["headers"]
            self.content = FakeContent()
            self.resolver = resolver
            self.host = host

        async def __aenter__(self):
            pinned.append((self.host, await self.resolver.resolve(self.host, 443, socket.AF_UNSPEC)))
            return self

        async def __aexit__(self, *_args):
            return None

    class FakeSession:
        def __init__(self, connector, **kwargs):
            self.connector = connector
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def get(self, url, **kwargs):
            host = urlsplit(url).hostname
            requests.append((url, kwargs, self.kwargs))
            response = responses.pop(0)
            return FakeResponse(response, self.connector.resolver, host)

    import officekit.engines.engine_media_import as module

    monkeypatch.setattr(module.aiohttp, "TCPConnector", FakeConnector)
    monkeypatch.setattr(module.aiohttp, "ClientSession", FakeSession)

    async def lookup(host):
        return {"origin.example": ["8.8.8.8"], "cdn.example": ["1.1.1.1"]}[host]

    result = asyncio.run(SafePublicUrlTransport(lookup=lookup).preview("https://origin.example/photo.png"))
    assert result.host == "cdn.example"
    assert result.size_bytes == 256
    assert result.content_type == "image/png"
    assert [(host, entries[0]["host"]) for host, entries in pinned] == [
        ("origin.example", "8.8.8.8"), ("cdn.example", "1.1.1.1"),
    ]
    assert all(request[1]["allow_redirects"] is False for request in requests)
    assert all(request[2]["trust_env"] is False for request in requests)
    assert all(request[2]["cookie_jar"].__class__.__name__ == "DummyCookieJar" for request in requests)


def test_https_media_download_streams_to_exclusive_file(monkeypatch, tmp_path):
    content = b"video-stream-chunks"

    class FakeConnector:
        def __init__(self, resolver, **_kwargs):
            self.resolver = resolver

    class FakeContent:
        async def iter_chunked(self, _size):
            yield content[:7]
            yield content[7:]

    class FakeResponse:
        def __init__(self):
            self.status = 200
            self.headers = {"Content-Type": "video/quicktime", "Content-Length": str(len(content))}
            self.content = FakeContent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class FakeSession:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def get(self, *_args, **_kwargs):
            return FakeResponse()

    import officekit.engines.engine_media_import as module
    monkeypatch.setattr(module.aiohttp, "TCPConnector", FakeConnector)
    monkeypatch.setattr(module.aiohttp, "ClientSession", FakeSession)

    async def lookup(_host):
        return ["8.8.8.8"]

    grant = module.MediaImportGrant(
        "https://media.example/clip.mov", "media.example", "video/quicktime",
        len(content), "clip.mov", 100,
    )
    destination = tmp_path / "clip.bin"
    result = asyncio.run(SafePublicUrlTransport(lookup=lookup).download_to_file(grant, destination))
    assert result == ("clip.mov", "video/quicktime", len(content))
    assert destination.read_bytes() == content
    with pytest.raises(FileExistsError):
        asyncio.run(SafePublicUrlTransport(lookup=lookup).download_to_file(grant, destination))
    assert destination.read_bytes() == content


@pytest.mark.parametrize("failure", ["cancelled", "overflow", "length-mismatch", "grant-mismatch"])
def test_https_media_file_download_removes_partial_file_on_failure(monkeypatch, tmp_path, failure):
    content = b"streamed-payload"
    cancellation = None

    class FakeConnector:
        def __init__(self, resolver, **_kwargs): self.resolver = resolver

    class FakeContent:
        async def iter_chunked(self, _size):
            yield content[:5]
            if cancellation is not None: cancellation.cancelled = True
            yield content[5:]

    class FakeResponse:
        status = 200
        content = FakeContent()

        def __init__(self):
            size = len(content) + 1 if failure == "length-mismatch" else len(content)
            self.headers = {"Content-Type": "video/quicktime"}
            if failure != "overflow": self.headers["Content-Length"] = str(size)

        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return None

    class FakeSession:
        def __init__(self, **_kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return None
        def get(self, *_args, **_kwargs): return FakeResponse()

    class Cancel:
        cancelled = False
        def is_set(self): return self.cancelled

    import officekit.engines.engine_media_import as module
    monkeypatch.setattr(module.aiohttp, "TCPConnector", FakeConnector)
    monkeypatch.setattr(module.aiohttp, "ClientSession", FakeSession)
    if failure == "overflow": monkeypatch.setattr(module, "MAX_MEDIA_IMPORT_BYTES", 8)

    async def lookup(_host): return ["8.8.8.8"]

    declared_size = len(content) + 1 if failure == "grant-mismatch" else len(content)
    grant = module.MediaImportGrant(
        "https://media.example/clip.mov", "media.example", "video/quicktime",
        declared_size, "clip.mov", 100,
    )
    destination = tmp_path / f"{failure}.bin"
    expected_error = {
        "cancelled": MediaImportCancelledError,
        "overflow": MediaImportTooLargeError,
        "length-mismatch": MediaImportRejectedError,
        "grant-mismatch": MediaImportRejectedError,
    }[failure]
    if failure == "cancelled": cancellation = Cancel()
    with pytest.raises(expected_error):
        asyncio.run(SafePublicUrlTransport(lookup=lookup).download_to_file(
            grant, destination, cancel_event=cancellation,
        ))
    assert not destination.exists()


def test_content_type_and_download_filename_are_limited_to_supported_media():
    assert supported_content_type("application/octet-stream", "photo.png") == "image/png"
    assert safe_media_filename("https://media.example/folder/unsafe%2Fphoto.png", "image/png") == "photo.png"
    assert safe_media_filename("https://media.example/file", "application/pdf") == "file.pdf"
    with pytest.raises(MediaImportRejectedError):
        supported_content_type("text/html", "page.html")


def test_import_preview_grants_expire_and_are_single_use():
    ticks = [10.0]
    store = MediaImportStore(StubTransport(png_bytes()), clock=lambda: ticks[0])
    preview = asyncio.run(store.preview("https://media.example/source.png"))
    assert preview["host"] == "media.example"
    assert preview["contentType"] == "image/png"
    assert preview["expiresInSeconds"] == MEDIA_IMPORT_TTL_SECONDS
    grant = store.claim(preview["importId"])
    assert grant.filename == "source.png"
    with pytest.raises(FileNotFoundError):
        store.claim(preview["importId"])
    expired = asyncio.run(store.preview("https://media.example/again.png"))
    ticks[0] += MEDIA_IMPORT_TTL_SECONDS + 1
    with pytest.raises(FileNotFoundError):
        store.claim(expired["importId"])


def test_import_preview_rate_is_bounded_before_network_access():
    transport = StubTransport(png_bytes())
    store = MediaImportStore(transport)
    for _ in range(MAX_PREVIEWS_PER_MINUTE):
        asyncio.run(store.preview("https://media.example/source.png"))
    with pytest.raises(MediaImportUnavailableError):
        asyncio.run(store.preview("https://media.example/source.png"))
    assert len(transport.urls) == MAX_PREVIEWS_PER_MINUTE


def test_preview_api_imported_job_and_artifact_are_one_use_and_preserve_no_remote_original(tmp_path):
    content = png_bytes()
    imports = MediaImportStore(StubTransport(content))
    selections = FileSelectionStore(native_token="native")
    jobs = MediaJobStore(
        selections,
        executor=ImmediateExecutor(),
        staging_root=str(tmp_path / "staging"),
        import_store=imports,
    )
    app = FastAPI()
    app.include_router(create_media_router(jobs, imports))
    client = TestClient(app)

    preview = client.post("/api/media-import-previews", json={"url": "https://media.example/source.png"})
    assert preview.status_code == 200
    assert preview.json()["sizeBytes"] == len(content)
    assert "url" not in preview.json()
    request = {"items": [{
        "source": {"kind": "import", "importId": preview.json()["importId"]},
        "operations": [{"operationId": "image-resize", "options": {"maxWidth": 40, "maxHeight": 30}}],
    }]}
    response = client.post("/api/media-jobs", json=request)
    assert response.status_code == 202
    status = client.get(response.headers["location"]).json()
    assert status["state"] == "ready"
    assert status["items"][0]["name"] == "source.png"
    with Image.open(BytesIO(client.get(f"/api/media-artifacts/{status['items'][0]['artifactId']}").content)) as output:
        assert output.size == (40, 30)
    assert client.post("/api/media-jobs", json=request).status_code == 404
    assert len(imports.transport.urls) == 2
    jobs.close()
    imports.close()
    selections.close()


def test_preview_api_rejects_private_targets_before_transport_call(tmp_path):
    imports = MediaImportStore(StubTransport(png_bytes()))
    selections = FileSelectionStore(native_token="native")
    jobs = MediaJobStore(selections, executor=ImmediateExecutor(), staging_root=str(tmp_path / "staging"))
    app = FastAPI()
    app.include_router(create_media_router(jobs, imports))
    response = TestClient(app).post("/api/media-import-previews", json={"url": "https://192.168.0.1/photo.png"})
    assert response.status_code == 403
    assert imports.transport.urls == []
    jobs.close()
    imports.close()
    selections.close()
