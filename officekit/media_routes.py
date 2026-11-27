"""Local Media Toolkit job and private artifact routes."""

from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from officekit.engines.engine_file_responses import content_disposition_attachment
from officekit.engines.engine_media_jobs import (
    MediaImportUnavailableError,
    MediaInputTooLargeError,
    MediaJobCapacityError,
    MediaJobConflictError,
    MediaJobNotFoundError,
    MediaJobStore,
)
from officekit.engines.engine_media_import import (
    MAX_MEDIA_IMPORT_URL_LENGTH,
    MediaImportRejectedError,
    MediaImportRemoteUnavailableError,
    MediaImportStore,
    MediaImportTooLargeError,
    MediaImportUnavailableError,
    MediaImportUnsafeTargetError,
)
from officekit.engines.engine_media_optimizer import MediaOperationUnavailableError
from officekit.engines.engine_media_preview import (
    MAX_PREVIEW_SOURCE_BYTES,
    MediaPreviewEngine,
    MediaPreviewLockedError,
    MediaPreviewUnavailableError,
)
from officekit.engines.engine_conversion_errors import ConversionInputError
from officekit.engines.engine_media_models import MediaJobCreate
from officekit.engines.engine_media_operation_defaults import (
    MediaOperationDefaultsStore,
    MediaOperationDefaultsStoreError,
)
from officekit.engines.engine_media_pipelines import (
    MediaPipelineCreate,
    MediaPipelineRename,
    MediaPipelineStore,
    MediaPipelineStoreError,
)
from officekit.engines.engine_media_pipeline_triggers import (
    MediaPipelineTriggerBinding,
    MediaPipelineTriggerStore,
    MediaPipelineTriggerStoreError,
    TRIGGER_TARGETS,
)
from officekit.engines.engine_media_folder_automation import MediaFolderAutomationStore
from officekit.engines.engine_media_preset_zones import (
    MediaPresetZoneCreate,
    MediaPresetZoneRebind,
    MediaPresetZoneRename,
    MediaPresetZoneResponse,
    MediaPresetZoneStore,
    MediaPresetZoneStoreError,
    MediaPresetZoneUpdate,
)
from officekit.engines.engine_media_capabilities import MediaCapabilitiesResponse, media_capabilities
from officekit.engines.engine_media_staging import (
    MediaStagingStore,
    StagedImageCapacityError,
    StagedImageConflictError,
    StagedImageTooLargeError,
    StagedImageUnavailableError,
)
from officekit.engines.engine_conversion_errors import ConversionInputError


class MediaJobAccepted(BaseModel):
    id: str
    state: Literal["queued"]


class MediaJobItemStatus(BaseModel):
    fileId: str
    name: str
    state: Literal["queued", "running", "ready", "failed", "cancelled"]
    artifactId: str | None
    outputName: str | None
    outputType: str | None
    outputBytes: int | None
    inputBytes: int | None = None
    attributes: dict = Field(default_factory=dict)
    errorCode: str | None


class MediaJobStatus(BaseModel):
    id: str
    state: Literal["queued", "running", "ready", "partial", "failed", "cancelled"]
    progress: int
    total: int
    phase: str
    items: list[MediaJobItemStatus]


class MediaCancellationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class MediaCancellationResponse(BaseModel):
    id: str
    state: Literal["queued", "running"]
    cancellationRequested: bool


class MediaImportPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    url: StrictStr = Field(min_length=1, max_length=MAX_MEDIA_IMPORT_URL_LENGTH)


class MediaImportPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    importId: StrictStr
    host: StrictStr
    contentType: StrictStr
    sizeBytes: int | None
    filename: StrictStr
    expiresInSeconds: int


class MediaFilePreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["image", "pdf", "video", "audio"]
    width: int | None = None
    height: int | None = None
    contentType: Literal["image/jpeg", "image/png"] | None = None
    dataBase64: StrictStr | None = None
    durationSeconds: float | None = None
    pageCount: int | None = None
    page: int | None = None
    peaks: list[int] | None = None
    locked: bool | None = None


class MediaStagedImageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    stagingId: StrictStr
    filename: StrictStr
    sizeBytes: int
    mediaType: StrictStr
    width: int
    height: int
    expiresInSeconds: int


class MediaPipelineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: StrictStr
    name: StrictStr
    media: Literal["image", "video", "pdf", "audio"]
    operations: list[dict]
    outputNameTemplate: StrictStr | None
    state: Literal["paused"]


class MediaOperationDefaultUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    options: dict[str, Any]


class MediaFolderWatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    selectionId: StrictStr
    pipelineId: StrictStr


class MediaFolderWatchUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    paused: bool


class MediaFolderWatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: StrictStr
    folderName: StrictStr
    pipelineId: StrictStr
    pipelineName: StrictStr
    state: Literal["watching", "paused"]
    processedCount: int
    lastOutcome: dict | None
    recentOutcomes: list[dict]


def _stream_artifact(stream):
    try:
        while chunk := stream.read(1024 * 1024):
            yield chunk
    finally:
        stream.close()


def create_media_router(
    store: MediaJobStore,
    import_store: MediaImportStore | None = None,
    image_staging_store: MediaStagingStore | None = None,
    pipeline_store: MediaPipelineStore | None = None,
    folder_store: MediaFolderAutomationStore | None = None,
    watermark_staging_store: MediaStagingStore | None = None,
    preset_zone_store: MediaPresetZoneStore | None = None,
    operation_defaults_store: MediaOperationDefaultsStore | None = None,
    pipeline_trigger_store: MediaPipelineTriggerStore | None = None,
):
    router = APIRouter()

    @router.get("/api/media-operation-defaults", response_model=dict[str, dict[str, Any]])
    def list_operation_defaults():
        if operation_defaults_store is None:
            raise HTTPException(status_code=503, detail="Operation defaults are not available in this build.")
        try:
            return operation_defaults_store.list()
        except MediaOperationDefaultsStoreError as error:
            raise HTTPException(status_code=503, detail="Saved operation defaults could not be read safely; the file was left unchanged.") from error

    @router.put("/api/media-operation-defaults/{operation_id}", response_model=dict[str, Any])
    def save_operation_default(operation_id: str, body: MediaOperationDefaultUpdate):
        if operation_defaults_store is None:
            raise HTTPException(status_code=503, detail="Operation defaults are not available in this build.")
        try:
            return {"operationId": operation_id, "options": operation_defaults_store.put(operation_id, body.options)}
        except ValueError as error:
            raise HTTPException(status_code=422, detail="Operation defaults do not match an available typed operation.") from error
        except OverflowError as error:
            raise HTTPException(status_code=413, detail="Saved operation defaults exceed the local configuration limit.") from error
        except MediaOperationDefaultsStoreError as error:
            raise HTTPException(status_code=503, detail="Saved operation defaults could not be updated safely; the file was left unchanged.") from error

    @router.delete("/api/media-operation-defaults", status_code=204)
    def clear_operation_defaults():
        if operation_defaults_store is None:
            raise HTTPException(status_code=503, detail="Operation defaults are not available in this build.")
        try:
            operation_defaults_store.clear()
        except (OverflowError, MediaOperationDefaultsStoreError) as error:
            raise HTTPException(status_code=503, detail="Saved operation defaults could not be cleared safely; the file was left unchanged.") from error
        return Response(status_code=204)

    @router.get("/api/media-pipeline-triggers", response_model=dict[str, str])
    def list_pipeline_triggers():
        if pipeline_trigger_store is None:
            raise HTTPException(status_code=503, detail="Pipeline triggers are not available in this build.")
        try:
            return pipeline_trigger_store.list()
        except (MediaPipelineTriggerStoreError, MediaPipelineStoreError) as error:
            raise HTTPException(status_code=503, detail="Saved pipeline triggers could not be read safely; the file was left unchanged.") from error

    @router.put("/api/media-pipeline-triggers/{trigger}", response_model=dict[str, str])
    def set_pipeline_trigger(trigger: str, body: MediaPipelineTriggerBinding):
        if pipeline_trigger_store is None:
            raise HTTPException(status_code=503, detail="Pipeline triggers are not available in this build.")
        if trigger not in TRIGGER_TARGETS:
            raise HTTPException(status_code=422, detail="Unsupported media pipeline trigger.")
        try:
            return pipeline_trigger_store.set(trigger, body)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="Saved pipeline is unavailable.") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except OverflowError as error:
            raise HTTPException(status_code=413, detail="Saved pipeline triggers exceed the local configuration limit.") from error
        except (MediaPipelineTriggerStoreError, MediaPipelineStoreError) as error:
            raise HTTPException(status_code=503, detail="Saved pipeline triggers could not be updated safely; the file was left unchanged.") from error

    @router.delete("/api/media-pipeline-triggers/{trigger}", status_code=204)
    def clear_pipeline_trigger(trigger: str):
        if pipeline_trigger_store is None:
            raise HTTPException(status_code=503, detail="Pipeline triggers are not available in this build.")
        if trigger not in TRIGGER_TARGETS:
            raise HTTPException(status_code=422, detail="Unsupported media pipeline trigger.")
        try:
            pipeline_trigger_store.clear(trigger)
        except (MediaPipelineTriggerStoreError, MediaPipelineStoreError) as error:
            raise HTTPException(status_code=503, detail="Saved pipeline triggers could not be cleared safely; the file was left unchanged.") from error
        return Response(status_code=204)

    @router.get("/api/media-preset-zones", response_model=list[MediaPresetZoneResponse])
    def list_preset_zones():
        if preset_zone_store is None:
            raise HTTPException(status_code=503, detail="Preset drop zones are not available in this build.")
        try:
            return preset_zone_store.list()
        except (MediaPresetZoneStoreError, MediaPipelineStoreError) as error:
            raise HTTPException(status_code=503, detail="Saved preset zones could not be read safely; the file was left unchanged.") from error

    @router.post("/api/media-preset-zones", status_code=201, response_model=MediaPresetZoneResponse)
    def create_preset_zone(body: MediaPresetZoneCreate):
        if preset_zone_store is None:
            raise HTTPException(status_code=503, detail="Preset drop zones are not available in this build.")
        try:
            return preset_zone_store.create(body)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="Saved pipeline is unavailable.") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except OverflowError as error:
            raise HTTPException(status_code=413, detail="The saved preset-zone list reached its local limit.") from error
        except (MediaPresetZoneStoreError, MediaPipelineStoreError) as error:
            raise HTTPException(status_code=503, detail="Saved preset zones could not be updated safely; the file was left unchanged.") from error

    @router.patch("/api/media-preset-zones/{zone_id}", response_model=MediaPresetZoneResponse)
    def update_preset_zone(zone_id: str, body: MediaPresetZoneUpdate):
        if preset_zone_store is None:
            raise HTTPException(status_code=503, detail="Preset drop zones are not available in this build.")
        try:
            return preset_zone_store.set_enabled(zone_id, body.enabled)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="Preset zone or saved pipeline is unavailable.") from error
        except (MediaPresetZoneStoreError, MediaPipelineStoreError) as error:
            raise HTTPException(status_code=503, detail="Saved preset zones could not be read safely; the file was left unchanged.") from error

    @router.put("/api/media-preset-zones/{zone_id}/name", response_model=MediaPresetZoneResponse)
    def rename_preset_zone(zone_id: str, body: MediaPresetZoneRename):
        if preset_zone_store is None:
            raise HTTPException(status_code=503, detail="Preset drop zones are not available in this build.")
        try:
            return preset_zone_store.rename(zone_id, body)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="Preset zone is unavailable.") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except OverflowError as error:
            raise HTTPException(status_code=413, detail="The saved preset-zone list reached its local configuration size limit.") from error
        except MediaPresetZoneStoreError as error:
            raise HTTPException(status_code=503, detail="Saved preset zones could not be updated safely; the file was left unchanged.") from error

    @router.put("/api/media-preset-zones/{zone_id}/pipeline", response_model=MediaPresetZoneResponse)
    def rebind_preset_zone(zone_id: str, body: MediaPresetZoneRebind):
        if preset_zone_store is None:
            raise HTTPException(status_code=503, detail="Preset-zone storage is unavailable")
        try:
            return preset_zone_store.rebind(zone_id, body)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except OverflowError as error:
            raise HTTPException(status_code=413, detail="The saved preset-zone list reached its local configuration size limit.") from error
        except (MediaPipelineStoreError, MediaPresetZoneStoreError) as error:
            raise HTTPException(status_code=503, detail="Saved preset zones could not be updated safely; the file was left unchanged.") from error

    @router.delete("/api/media-preset-zones/{zone_id}", status_code=204)
    def delete_preset_zone(zone_id: str):
        if preset_zone_store is None:
            raise HTTPException(status_code=503, detail="Preset drop zones are not available in this build.")
        try:
            if not preset_zone_store.delete(zone_id):
                raise HTTPException(status_code=404, detail="Preset zone is unavailable.")
        except MediaPresetZoneStoreError as error:
            raise HTTPException(status_code=503, detail="Saved preset zones could not be updated safely; the file was left unchanged.") from error
        return Response(status_code=204)

    @router.get("/api/media-folder-watches", response_model=list[MediaFolderWatchResponse])
    def list_folder_watches():
        if folder_store is None:
            raise HTTPException(status_code=503, detail="Watched folders are not available in this build.")
        return folder_store.list()

    @router.post("/api/media-folder-watches", status_code=201, response_model=MediaFolderWatchResponse)
    def add_folder_watch(body: MediaFolderWatchCreate, request: Request):
        if folder_store is None:
            raise HTTPException(status_code=503, detail="Watched folders are not available in this build.")
        try:
            folder_store.selections.authorize(request.headers.get("X-OfficeKit-Native-Grant", ""))
            return folder_store.add(body.selectionId, body.pipelineId)
        except PermissionError as error:
            raise HTTPException(status_code=403, detail="A native folder grant is required.") from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="The selected folder or saved pipeline is unavailable.") from error
        except OverflowError as error:
            raise HTTPException(status_code=429, detail="The watched-folder limit has been reached.") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail="Choose one granted folder and a valid saved pipeline.") from error
        except MediaPipelineStoreError as error:
            raise HTTPException(status_code=503, detail="Saved pipeline settings are unavailable; the file was left unchanged.") from error

    @router.patch("/api/media-folder-watches/{watch_id}", response_model=MediaFolderWatchResponse)
    def update_folder_watch(watch_id: str, body: MediaFolderWatchUpdate):
        if folder_store is None:
            raise HTTPException(status_code=503, detail="Watched folders are not available in this build.")
        try:
            return folder_store.set_paused(watch_id, body.paused)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="Watched folder is unavailable.") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail="The watched-folder state is invalid.") from error

    @router.delete("/api/media-folder-watches/{watch_id}", status_code=204)
    def delete_folder_watch(watch_id: str):
        if folder_store is None:
            raise HTTPException(status_code=503, detail="Watched folders are not available in this build.")
        try:
            folder_store.remove(watch_id)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="Watched folder is unavailable.") from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail="Wait for active folder jobs to finish before removing this folder.") from error
        return Response(status_code=204)

    @router.get("/api/media-pipelines", response_model=list[MediaPipelineResponse])
    def list_pipelines():
        if pipeline_store is None:
            raise HTTPException(status_code=503, detail="Saved media pipelines are not available in this build.")
        try:
            return pipeline_store.list()
        except MediaPipelineStoreError as error:
            raise HTTPException(status_code=503, detail="Saved pipelines could not be read safely; the file was left unchanged.") from error

    @router.post("/api/media-pipelines", status_code=201, response_model=MediaPipelineResponse)
    def create_pipeline(body: MediaPipelineCreate):
        if pipeline_store is None:
            raise HTTPException(status_code=503, detail="Saved media pipelines are not available in this build.")
        try:
            return pipeline_store.create(body)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except OverflowError as error:
            raise HTTPException(status_code=413, detail="The saved pipeline list reached its local limit.") from error
        except MediaPipelineStoreError as error:
            raise HTTPException(status_code=503, detail="Saved pipelines could not be updated safely; the file was left unchanged.") from error

    @router.patch("/api/media-pipelines/{pipeline_id}", response_model=MediaPipelineResponse)
    def rename_pipeline(pipeline_id: str, body: MediaPipelineRename):
        if pipeline_store is None:
            raise HTTPException(status_code=503, detail="Saved media pipelines are not available in this build.")
        try:
            return pipeline_store.rename(pipeline_id, body)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="Saved pipeline is unavailable.") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except OverflowError as error:
            raise HTTPException(status_code=413, detail="The saved pipeline reached its local configuration size limit.") from error
        except MediaPipelineStoreError as error:
            raise HTTPException(status_code=503, detail="Saved pipelines could not be updated safely; the file was left unchanged.") from error

    @router.put("/api/media-pipelines/{pipeline_id}", response_model=MediaPipelineResponse)
    def update_pipeline(pipeline_id: str, body: MediaPipelineCreate):
        if pipeline_store is None:
            raise HTTPException(status_code=503, detail="Saved media pipelines are not available in this build.")
        try:
            return pipeline_store.update(pipeline_id, body)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="Saved pipeline is unavailable.") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except OverflowError as error:
            raise HTTPException(status_code=413, detail="The saved pipeline reached its local configuration size limit.") from error
        except MediaPipelineStoreError as error:
            raise HTTPException(status_code=503, detail="Saved pipelines could not be updated safely; the file was left unchanged.") from error

    @router.delete("/api/media-pipelines/{pipeline_id}", status_code=204)
    def delete_pipeline(pipeline_id: str):
        if pipeline_store is None:
            raise HTTPException(status_code=503, detail="Saved media pipelines are not available in this build.")
        try:
            with pipeline_store.coordination_lock():
                if folder_store is not None and folder_store.uses_pipeline(pipeline_id):
                    raise HTTPException(status_code=409, detail="Remove or reconfigure watched folders before deleting this pipeline.")
                if preset_zone_store is not None and preset_zone_store.uses_pipeline(pipeline_id):
                    raise HTTPException(status_code=409, detail="Remove or reconfigure preset zones before deleting this pipeline.")
                if pipeline_trigger_store is not None and pipeline_trigger_store.uses_pipeline(pipeline_id):
                    raise HTTPException(status_code=409, detail="Clear pipeline trigger bindings before deleting this pipeline.")
                if not pipeline_store.delete(pipeline_id):
                    raise HTTPException(status_code=404, detail="Saved pipeline is unavailable.")
        except MediaPipelineStoreError as error:
            raise HTTPException(status_code=503, detail="Saved pipelines could not be updated safely; the file was left unchanged.") from error
        except MediaPresetZoneStoreError as error:
            raise HTTPException(status_code=503, detail="Saved preset zones could not be read safely; the pipeline was left unchanged.") from error
        except MediaPipelineTriggerStoreError as error:
            raise HTTPException(status_code=503, detail="Saved pipeline triggers could not be read safely; the pipeline was left unchanged.") from error
        return Response(status_code=204)

    @router.get("/api/media-capabilities", response_model=MediaCapabilitiesResponse)
    def get_capabilities():
        return media_capabilities()

    @router.post(
        "/api/media-import-previews",
        response_model=MediaImportPreviewResponse,
    )
    async def create_import_preview(body: MediaImportPreviewRequest):
        if import_store is None:
            raise HTTPException(status_code=503, detail="Public URL import is not available in this build.")
        try:
            return await import_store.preview(body.url)
        except MediaImportTooLargeError as error:
            raise HTTPException(status_code=413, detail="The remote media exceeds the 64 MiB import limit.") from error
        except MediaImportUnsafeTargetError as error:
            raise HTTPException(status_code=403, detail="The media URL must resolve only to public addresses.") from error
        except MediaImportUnavailableError as error:
            raise HTTPException(status_code=429, detail="Too many active URL previews. Wait and try again.") from error
        except MediaImportRemoteUnavailableError as error:
            raise HTTPException(status_code=502, detail="The public media URL could not be reached in time.") from error
        except MediaImportRejectedError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail="Enter a valid public HTTPS media URL.") from error

    @router.post("/api/media-image-stagings", response_model=MediaStagedImageResponse)
    async def create_image_staging(file: UploadFile = File(...)):
        if image_staging_store is None:
            raise HTTPException(status_code=503, detail="Edited-image handoff is not available in this build.")
        try:
            return await image_staging_store.create(file, file.filename or "screenshot.png")
        except StagedImageTooLargeError as error:
            raise HTTPException(status_code=413, detail="The edited image exceeds the 64 MiB handoff limit.") from error
        except StagedImageCapacityError as error:
            raise HTTPException(status_code=429, detail="Too many edited images are waiting. Clear one or wait for expiry.") from error
        except ConversionInputError as error:
            raise HTTPException(status_code=422, detail="The edited image is invalid or uses an unsupported format.") from error

    @router.delete("/api/media-image-stagings/{staging_id}", status_code=204)
    def delete_image_staging(staging_id: str):
        if image_staging_store is None:
            raise HTTPException(status_code=503, detail="Edited-image handoff is not available in this build.")
        try:
            image_staging_store.discard(staging_id)
        except StagedImageUnavailableError as error:
            raise HTTPException(status_code=404, detail="The edited image is unavailable or expired.") from error
        except StagedImageConflictError as error:
            raise HTTPException(status_code=409, detail="The edited image is already part of a media job.") from error
        return Response(status_code=204)

    @router.post("/api/media-watermark-stagings", response_model=MediaStagedImageResponse)
    async def create_watermark_staging(file: UploadFile = File(...)):
        if watermark_staging_store is None:
            raise HTTPException(status_code=503, detail="Image watermarking is not available in this build.")
        try:
            return await watermark_staging_store.create(file, file.filename or "watermark.png")
        except StagedImageTooLargeError as error:
            raise HTTPException(status_code=413, detail="The watermark image exceeds the 5 MiB limit.") from error
        except StagedImageCapacityError as error:
            raise HTTPException(status_code=429, detail="Too many watermark images are waiting. Remove one or wait for expiry.") from error
        except ConversionInputError as error:
            raise HTTPException(status_code=422, detail="Choose a single PNG, JPEG, or WebP watermark image.") from error

    @router.delete("/api/media-watermark-stagings/{staging_id}", status_code=204)
    def delete_watermark_staging(staging_id: str):
        if watermark_staging_store is None:
            raise HTTPException(status_code=503, detail="Image watermarking is not available in this build.")
        try:
            watermark_staging_store.discard(staging_id)
        except StagedImageUnavailableError as error:
            raise HTTPException(status_code=404, detail="The watermark image is unavailable or expired.") from error
        except StagedImageConflictError as error:
            raise HTTPException(status_code=409, detail="The watermark image is already part of a media job.") from error
        return Response(status_code=204)

    @router.get(
        "/api/media-previews/{selection_id}/{file_id}",
        response_model=MediaFilePreviewResponse,
        response_model_exclude_none=True,
    )
    def get_file_preview(
        selection_id: str,
        file_id: str,
        size: int = Query(default=192, ge=32, le=2048),
        page: int = Query(default=1, ge=1, le=100_000),
        position: int = Query(default=10, ge=0, le=100),
    ):
        """A local preview of one selected image, PDF page, video frame or audio waveform; the original is only read."""
        try:
            selected = next((entry for entry in store.selections.iter_files(selection_id) if entry.id == file_id), None)
            if selected is None:
                raise FileNotFoundError("Selected file is unavailable")
            kind = MediaPreviewEngine.kind(selected.name)
            if kind is None:
                raise MediaPreviewUnavailableError()
            with store.selections.open_file(selected) as source:
                if kind in {"video", "audio"}:
                    return MediaPreviewEngine.render_av(source, selected.name, kind, size, position)
                data = source.read(MAX_PREVIEW_SOURCE_BYTES + 1)
            if len(data) > MAX_PREVIEW_SOURCE_BYTES:
                raise HTTPException(status_code=413, detail="This file is too large to preview.")
            if kind == "pdf":
                return MediaPreviewEngine.render_pdf(data, size, page)
            return MediaPreviewEngine.render(data, selected.name, size)
        except PermissionError as error:
            raise HTTPException(status_code=403, detail="OfficeKit does not have permission to read this selection.") from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="The selected file is unavailable. Select it again.") from error
        except MediaPreviewLockedError:
            # A password is a state of the file, not a failure: the client shows a lock tile.
            return {"kind": "pdf", "locked": True}
        except MediaPreviewUnavailableError as error:
            raise HTTPException(status_code=415, detail="No preview is available for this file type.") from error
        except (ConversionInputError, ValueError) as error:
            raise HTTPException(status_code=422, detail="This file could not be previewed.") from error

    @router.post("/api/media-jobs", status_code=202, response_model=MediaJobAccepted)
    def create_job(body: MediaJobCreate, response: Response):
        try:
            job = store.submit(body)
        except MediaJobCapacityError as error:
            raise HTTPException(status_code=503, detail="The media queue is full. Try again when a job finishes.") from error
        except MediaOperationUnavailableError as error:
            raise HTTPException(status_code=503, detail="This media operation is not available in this workbench yet.") from error
        except MediaInputTooLargeError as error:
            raise HTTPException(status_code=413, detail="This media adapter currently supports files up to 64 MiB.") from error
        except MediaImportUnavailableError as error:
            raise HTTPException(status_code=503, detail="Public URL import is not available in this build.") from error
        except PermissionError as error:
            raise HTTPException(status_code=403, detail="OfficeKit does not have permission to read this selection.") from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="The selected file or URL preview is unavailable. Select or preview it again.") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail="The selected media request is invalid.") from error
        response.headers["Location"] = f"/api/media-jobs/{job['id']}"
        return job

    @router.get("/api/media-jobs/{job_id}", response_model=MediaJobStatus)
    def get_job(job_id: str):
        try:
            return store.status(job_id)
        except MediaJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="Media job is unavailable.") from error

    @router.post(
        "/api/media-jobs/{job_id}/cancellations",
        status_code=202,
        response_model=MediaCancellationResponse,
    )
    def cancel_job(job_id: str, _body: MediaCancellationRequest):
        try:
            return store.cancel(job_id)
        except MediaJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="Media job is unavailable.") from error
        except MediaJobConflictError as error:
            raise HTTPException(status_code=409, detail="This media job can no longer be cancelled.") from error

    @router.get(
        "/api/media-artifacts/{artifact_id}",
        response_class=StreamingResponse,
        responses={
            200: {
                "description": "Prepared media artifact bytes.",
                "content": {
                    media_type: {"schema": {"type": "string", "format": "binary"}}
                    for media_type in (
                        "image/jpeg", "image/png", "image/webp", "image/bmp",
                        "image/tiff", "image/gif", "image/x-icon", "application/pdf",
                        "video/x-m4v", "video/quicktime", "audio/mp4", "audio/wav",
                        "audio/aiff", "audio/flac",
                    )
                },
            },
            404: {"description": "Media artifact is unavailable."},
        },
    )
    def get_artifact(artifact_id: str):
        try:
            artifact = store.artifact(artifact_id)
        except MediaJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="Media artifact is unavailable.") from error
        return StreamingResponse(
            _stream_artifact(artifact["file"]),
            media_type=artifact["mediaType"],
            headers={
                "Content-Length": str(artifact["sizeBytes"]),
                "Content-Disposition": content_disposition_attachment(artifact["displayName"]),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router
