import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from officekit.engines.engine_conversion_errors import ConversionInputError
from officekit.engines.engine_file_selections import FileSelectionStore
from officekit.engines.engine_media_jobs import MediaJobStore
from officekit.engines.engine_media_staging import (
    MediaStagingStore,
    StagedImageConflictError,
    StagedImageTooLargeError,
    StagedImageUnavailableError,
)


class Upload:
    def __init__(self, data):
        self.stream = BytesIO(data)
        self.closed = False

    async def read(self, size):
        return self.stream.read(size)

    async def close(self):
        self.closed = True


class QueueExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, function, *args):
        self.calls.append((function, args))

    def run_all(self):
        while self.calls:
            function, args = self.calls.pop(0)
            function(*args)

    def shutdown(self, **_kwargs):
        self.calls.clear()


def png_bytes(width=8, height=6):
    output = BytesIO()
    Image.new("RGB", (width, height), (40, 90, 130)).save(output, "PNG")
    return output.getvalue()


def test_staged_image_is_private_verified_single_use_and_deleted_after_release(tmp_path):
    upload = Upload(png_bytes())
    store = MediaStagingStore(root=tmp_path / "private")
    response = asyncio.run(store.create(upload, "../private/screenshot.png"))
    assert upload.closed
    assert response["filename"] == "screenshot.png"
    assert response["mediaType"] == "image/png"
    assert response["width"] == 8 and response["height"] == 6
    record, expiry, claimed = store.records[response["stagingId"]]
    assert claimed is False
    assert Path(record.path).stat().st_mode & 0o077 == 0
    grant = store.claim(response["stagingId"])
    assert store.read(grant) == png_bytes()
    with pytest.raises(StagedImageUnavailableError):
        store.claim(response["stagingId"])
    with pytest.raises(StagedImageConflictError):
        store.discard(response["stagingId"])
    store.release(grant)
    assert not Path(record.path).exists()
    assert response["stagingId"] not in store.records
    store.close()


def test_unclaimed_staging_expires_and_invalid_or_oversized_images_are_removed(tmp_path, monkeypatch):
    current_time = [10.0]
    store = MediaStagingStore(clock=lambda: current_time[0], root=tmp_path / "private")
    created = asyncio.run(store.create(Upload(png_bytes()), "shot.png"))
    path = store.records[created["stagingId"]][0].path
    current_time[0] += 301
    with pytest.raises(StagedImageUnavailableError):
        store.claim(created["stagingId"])
    assert not Path(path).exists()
    assert not store.records

    invalid = Upload(b"not an image")
    with pytest.raises(ConversionInputError):
        asyncio.run(store.create(invalid, "bad.png"))
    assert invalid.closed
    assert not store.records

    monkeypatch.setattr("officekit.engines.engine_media_staging.MAX_STAGED_IMAGE_BYTES", 16)
    oversized = Upload(png_bytes())
    with pytest.raises(StagedImageTooLargeError):
        asyncio.run(store.create(oversized, "large.png"))
    assert oversized.closed
    assert not store.records
    assert not list((tmp_path / "private").iterdir())
    store.close()


def test_queued_job_cancellation_releases_the_claimed_screenshot_handoff(tmp_path):
    image_store = MediaStagingStore(root=tmp_path / "image-staging")
    source = asyncio.run(image_store.create(Upload(png_bytes()), "edited.png"))
    executor = QueueExecutor()
    selections = FileSelectionStore(native_token="native")
    jobs = MediaJobStore(
        selections,
        executor=executor,
        staging_root=str(tmp_path / "jobs"),
        image_staging_store=image_store,
    )
    created = jobs.submit({"items": [{
        "source": {"kind": "staged-image", "stagingId": source["stagingId"]},
        "operations": [{"operationId": "image-optimize", "options": {"quality": 70}}],
    }]})
    grant = jobs.jobs[created["id"]].items[0].staged_image
    assert Path(grant.path).exists()
    assert jobs.cancel(created["id"])["cancellationRequested"] is True
    executor.run_all()
    assert jobs.status(created["id"])["state"] == "cancelled"
    assert not Path(grant.path).exists()
    assert source["stagingId"] not in image_store.records
    jobs.close()
    selections.close()
