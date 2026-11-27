"""Local stdio MCP interface for the typed Media Toolkit contract."""

import asyncio
import json
import os
import tempfile
from io import StringIO
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, field_validator, model_validator

from .engines.engine_media_capabilities import media_capabilities
from .engines.engine_media_models import MediaOperation
from .engines.engine_media_naming import validate_output_name_template
from .engines.engine_media_operation_defaults import (
    MediaOperationDefaultsStore,
    MediaOperationDefaultsStoreError,
)
from .engines.engine_media_pipelines import (
    MediaPipelineCreate,
    MediaPipelineRename,
    MediaPipelineStore,
    MediaPipelineStoreError,
)
from .engines.engine_media_preset_zones import (
    MediaPresetZoneCreate,
    MediaPresetZoneRebind,
    MediaPresetZoneRename,
    MediaPresetZoneStore,
    MediaPresetZoneStoreError,
)
from .engines.engine_media_pipeline_triggers import (
    MediaPipelineTriggerBinding,
    MediaPipelineTriggerStore,
    MediaPipelineTriggerStoreError,
)
from .media_cli import _parse_crop_aspect_ratio, run as run_media_cli


class MediaPrepareInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    files: list[StrictStr] = Field(
        min_length=1,
        max_length=30,
        description="One to 30 local media files. Originals are read only.",
    )
    operations: list[dict[str, Any]] = Field(
        min_length=1,
        max_length=8,
        description="One to eight typed Media Toolkit operations, each with operationId and options.",
    )
    output_directory: StrictStr = Field(
        min_length=1,
        max_length=4096,
        description="Local directory for new output copies. Existing outputs are never replaced.",
    )
    watermark_image: StrictStr | None = Field(
        default=None, max_length=4096,
        description="Optional local PNG, JPEG, or WebP logo path for image-watermark-overlay or video-watermark-overlay (up to 5 MiB).",
    )
    output_name_template: StrictStr | None = Field(default=None, max_length=120)

    @field_validator("output_name_template")
    @classmethod
    def validate_name_template(cls, value):
        return validate_output_name_template(value)


class MediaPresetInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    files: list[StrictStr] = Field(min_length=1, max_length=30)
    preset: Literal["optimize-image", "optimize-media", "to-webp", "downscale-image", "downscale-video", "downscale-audio", "crop-aspect", "sort-screenshots", "audio-to-mp3", "video-to-gif", "video-2x-silent", "uncrop-pdf"]
    output_directory: StrictStr = Field(min_length=1, max_length=4096)
    collision_policy: Literal["error", "suffix"] = "error"
    output_name_template: StrictStr | None = Field(default=None, max_length=120)
    factor: StrictFloat | StrictInt | None = Field(default=None, ge=0, le=1)
    aspect_ratio: StrictStr | None = Field(default=None, max_length=15)

    @model_validator(mode="after")
    def validate_factor(self):
        if self.preset in {"downscale-image", "downscale-video", "downscale-audio"}:
            if self.factor is None or not 0 < self.factor <= 1:
                raise ValueError(f"The {self.preset} preset requires a factor greater than 0 and no more than 1")
        elif self.factor is not None:
            raise ValueError("A factor is accepted only by a downscale preset")
        if self.preset == "crop-aspect":
            if self.aspect_ratio is None:
                raise ValueError("The crop-aspect preset requires aspect_ratio")
            _parse_crop_aspect_ratio(self.aspect_ratio)
        elif self.aspect_ratio is not None:
            raise ValueError("aspect_ratio is accepted only by the crop-aspect preset")
        return self

    @field_validator("output_name_template")
    @classmethod
    def validate_name_template(cls, value):
        return validate_output_name_template(value)


server = MCPServer(
    "officekit_media",
    title="OfficeKit Media Toolkit",
    version="1.0.0",
    instructions=(
        "Prepare local image, video, PDF, and audio files using only operations reported available by "
        "officekit_media_list_operations. Twelve built-in typed presets can be run with officekit_media_run_preset. "
        "Typed operation defaults are shared with the desktop app through local settings tools. "
        "Pipelines can be pinned to clipboard and general drop-zone triggers with pipeline trigger tools. "
        "Optional output-name templates support {name}, {ext}, {media}, plus Clop %f/%e, date/time, %r, and %i filename tokens. Always choose an explicit output directory. Originals are "
        "read only; output collisions fail instead of overwriting. Processing stays on this device."
    ),
)


def _pipeline_store() -> MediaPipelineStore:
    """Open the same private local pipeline collection as the desktop app."""
    return MediaPipelineStore()


def _preset_zone_store() -> MediaPresetZoneStore:
    """Open durable named bindings; enabled drop targets remain desktop-session-only."""
    pipelines = _pipeline_store()
    return MediaPresetZoneStore(pipelines)


def _pipeline_trigger_store() -> MediaPipelineTriggerStore:
    return MediaPipelineTriggerStore(_pipeline_store())


def _delete_pipeline_safely(pipeline_id: str) -> bool:
    """Coordinate zone creation/deletion with removal of the referenced pipeline."""
    store = _pipeline_store()
    with store.coordination_lock():
        if _preset_zone_store().uses_pipeline(pipeline_id):
            raise ValueError("Remove or reconfigure preset zones before deleting this pipeline.")
        if _pipeline_trigger_store().uses_pipeline(pipeline_id):
            raise ValueError("Clear pipeline trigger bindings before deleting this pipeline.")
        return store.delete(pipeline_id)


@server.tool(
    name="officekit_media_list_operations",
    title="List available media operations",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False),
)
def list_operations() -> dict[str, Any]:
    """List every Media Toolkit operation with build-specific availability and formats."""
    return media_capabilities()


def _operation_defaults_store() -> MediaOperationDefaultsStore:
    return MediaOperationDefaultsStore()


@server.tool(
    name="officekit_media_list_operation_defaults",
    title="List saved media operation defaults",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False),
)
async def list_operation_defaults() -> dict[str, dict[str, Any]]:
    """Read locally saved, typed option values shared with the desktop workbench."""
    try:
        return await asyncio.to_thread(_operation_defaults_store().list)
    except MediaOperationDefaultsStoreError as error:
        raise ValueError("Saved operation defaults could not be read safely; the file was left unchanged.") from error


@server.tool(
    name="officekit_media_set_operation_default",
    title="Save a media operation default",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def set_operation_default(
    operation_id: Annotated[StrictStr, Field(min_length=1, max_length=64)],
    options: dict[str, Any],
) -> dict[str, Any]:
    """Save validated option values for a known operation; no paths or media are stored."""
    try:
        saved = await asyncio.to_thread(_operation_defaults_store().put, operation_id, options)
        return {"operationId": operation_id, "options": saved, "state": "saved"}
    except ValueError as error:
        raise ValueError("Operation defaults do not match an available typed operation.") from error
    except OverflowError as error:
        raise ValueError("Saved operation defaults exceed the local configuration limit.") from error
    except MediaOperationDefaultsStoreError as error:
        raise ValueError("Saved operation defaults could not be updated safely; the file was left unchanged.") from error


@server.tool(
    name="officekit_media_clear_operation_defaults",
    title="Clear saved media operation defaults",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
async def clear_operation_defaults() -> dict[str, str]:
    """Clear only local operation settings shared with the desktop app."""
    try:
        await asyncio.to_thread(_operation_defaults_store().clear)
        return {"state": "cleared"}
    except (OverflowError, MediaOperationDefaultsStoreError) as error:
        raise ValueError("Saved operation defaults could not be cleared safely; the file was left unchanged.") from error


@server.tool(
    name="officekit_media_list_pipeline_triggers",
    title="List pinned media pipelines",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False),
)
async def list_pipeline_triggers() -> dict[str, str]:
    """List the saved pipeline ID pinned to clipboard or the general drop target, when set."""
    try:
        return await asyncio.to_thread(_pipeline_trigger_store().list)
    except (MediaPipelineStoreError, MediaPipelineTriggerStoreError) as error:
        raise ValueError("Saved pipeline triggers could not be read safely; the file was left unchanged.") from error


@server.tool(
    name="officekit_media_set_pipeline_trigger",
    title="Pin a media pipeline to a trigger",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def set_pipeline_trigger(
    trigger: Literal["clipboard", "drop-zone"],
    pipeline_id: Annotated[StrictStr, Field(min_length=36, max_length=36)],
) -> dict[str, str]:
    """Pin an existing pipeline; clipboard bindings accept image-only pipelines."""
    try:
        definition = MediaPipelineTriggerBinding.model_validate({"pipelineId": pipeline_id})
        return await asyncio.to_thread(_pipeline_trigger_store().set, trigger, definition)
    except FileNotFoundError as error:
        raise ValueError("Saved pipeline is unavailable.") from error
    except (ValueError, OverflowError) as error:
        raise ValueError(str(error)) from error
    except (MediaPipelineStoreError, MediaPipelineTriggerStoreError) as error:
        raise ValueError("Saved pipeline triggers could not be updated safely; the file was left unchanged.") from error


@server.tool(
    name="officekit_media_clear_pipeline_trigger",
    title="Unpin a media pipeline trigger",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
async def clear_pipeline_trigger(trigger: Literal["clipboard", "drop-zone"]) -> dict[str, str]:
    """Clear one pipeline pin without changing the saved pipeline or media files."""
    try:
        await asyncio.to_thread(_pipeline_trigger_store().clear, trigger)
        return {"trigger": trigger, "state": "cleared"}
    except (MediaPipelineStoreError, MediaPipelineTriggerStoreError) as error:
        raise ValueError("Saved pipeline triggers could not be cleared safely; the file was left unchanged.") from error


@server.tool(
    name="officekit_media_list_pipelines",
    title="List saved media pipelines",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False),
)
async def list_pipelines() -> list[dict[str, Any]]:
    """List private local pipelines. Recipes always load paused and contain typed operations only."""
    try:
        return await asyncio.to_thread(_pipeline_store().list)
    except MediaPipelineStoreError as error:
        raise ValueError("Saved pipelines could not be read safely. The file was left unchanged.") from error


@server.tool(
    name="officekit_media_create_pipeline",
    title="Create a saved media pipeline",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def create_pipeline(definition: MediaPipelineCreate) -> dict[str, Any]:
    """Save a paused local pipeline with one media kind and 1–8 allowlisted operations.

    The definition contains name, media, operation objects with operationId/options, and optional outputNameTemplate.
    Paths, URLs, scripts, and shell commands are not accepted. Duplicate names and configured
    storage bounds are enforced by the same store used by the desktop app.
    """
    try:
        return await asyncio.to_thread(_pipeline_store().create, definition)
    except ValueError as error:
        raise ValueError(str(error)) from error
    except OverflowError as error:
        raise ValueError("The saved pipeline limit or local configuration size has been reached.") from error
    except MediaPipelineStoreError as error:
        raise ValueError("Saved pipelines could not be updated safely. The file was left unchanged.") from error


@server.tool(
    name="officekit_media_rename_pipeline",
    title="Rename a saved media pipeline",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def rename_pipeline(
    pipeline_id: Annotated[StrictStr, Field(min_length=36, max_length=36)],
    name: Annotated[StrictStr, Field(min_length=1, max_length=64)],
) -> dict[str, Any]:
    """Rename a saved recipe without changing its ID, operations, or paused state."""
    definition = MediaPipelineRename.model_validate({"name": name})
    try:
        return await asyncio.to_thread(_pipeline_store().rename, pipeline_id, definition)
    except FileNotFoundError as error:
        raise ValueError("Saved pipeline is unavailable.") from error
    except OverflowError as error:
        raise ValueError("The saved pipeline limit or local configuration size has been reached.") from error
    except ValueError as error:
        raise ValueError(str(error)) from error
    except MediaPipelineStoreError as error:
        raise ValueError("Saved pipelines could not be updated safely. The file was left unchanged.") from error


@server.tool(
    name="officekit_media_update_pipeline",
    title="Update a saved media pipeline",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def update_pipeline(
    pipeline_id: Annotated[StrictStr, Field(min_length=36, max_length=36)],
    definition: MediaPipelineCreate,
) -> dict[str, Any]:
    """Update a saved pipeline's name and allowlisted steps within its existing media kind."""
    try:
        return await asyncio.to_thread(_pipeline_store().update, pipeline_id, definition)
    except FileNotFoundError as error:
        raise ValueError("Saved pipeline is unavailable.") from error
    except OverflowError as error:
        raise ValueError("The saved pipeline limit or local configuration size has been reached.") from error
    except ValueError as error:
        raise ValueError(str(error)) from error
    except MediaPipelineStoreError as error:
        raise ValueError("Saved pipelines could not be updated safely. The file was left unchanged.") from error


@server.tool(
    name="officekit_media_delete_pipeline",
    title="Delete a saved media pipeline",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def delete_pipeline(
    pipeline_id: Annotated[StrictStr, Field(min_length=36, max_length=36)],
) -> dict[str, str]:
    """Delete a recipe setting only; this never deletes media files or prepared results.

    A pipeline bound to a saved preset drop zone must be unbound first. Watched-folder grants
    and enabled native drop targets are session-only and can only be managed in the desktop app.
    Deleting a pipeline currently used by a live watched folder causes that watcher to pause safely
    at its next scan; remove the watch in OfficeKit first to keep the automation active.
    """
    try:
        deleted = await asyncio.to_thread(_delete_pipeline_safely, pipeline_id)
        if not deleted:
            raise ValueError("Saved pipeline is unavailable.")
        return {"id": pipeline_id, "state": "deleted"}
    except MediaPipelineStoreError as error:
        raise ValueError("Saved pipelines could not be updated safely. The file was left unchanged.") from error
    except MediaPresetZoneStoreError as error:
        raise ValueError("Saved automation settings could not be read safely; the file was left unchanged.") from error
    except MediaPipelineTriggerStoreError as error:
        raise ValueError("Saved pipeline triggers could not be read safely; the file was left unchanged.") from error


@server.tool(
    name="officekit_media_list_preset_zones",
    title="List saved preset zone bindings",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False),
)
async def list_preset_zones() -> list[dict[str, str]]:
    """List durable zone names and pipeline IDs without exposing session enablement or file paths."""
    try:
        return await asyncio.to_thread(_preset_zone_store().list_bindings)
    except (MediaPipelineStoreError, MediaPresetZoneStoreError) as error:
        raise ValueError("Saved automation settings could not be read safely. The file was left unchanged.") from error


@server.tool(
    name="officekit_media_create_preset_zone",
    title="Save a preset zone binding",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def create_preset_zone(
    name: Annotated[StrictStr, Field(min_length=1, max_length=48)],
    pipeline_id: Annotated[StrictStr, Field(min_length=36, max_length=36)],
) -> dict[str, Any]:
    """Save a name-to-pipeline automation setting; it starts disabled in desktop sessions.

    This does not enable native drop targets or grant filesystem access. Use OfficeKit to enable
    a saved zone for the current session after reviewing its pipeline.
    """
    try:
        definition = MediaPresetZoneCreate.model_validate({"name": name, "pipelineId": pipeline_id})
        return await asyncio.to_thread(_preset_zone_store().create, definition)
    except FileNotFoundError as error:
        raise ValueError("Saved pipeline is unavailable.") from error
    except (ValueError, OverflowError) as error:
        raise ValueError(str(error)) from error
    except (MediaPipelineStoreError, MediaPresetZoneStoreError) as error:
        raise ValueError("Saved automation settings could not be updated safely. The file was left unchanged.") from error


@server.tool(
    name="officekit_media_rename_preset_zone",
    title="Rename a preset zone binding",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def rename_preset_zone(
    zone_id: Annotated[StrictStr, Field(min_length=36, max_length=36)],
    name: Annotated[StrictStr, Field(min_length=1, max_length=48)],
) -> dict[str, Any]:
    """Rename a saved zone while preserving its pipeline and current session enablement."""
    try:
        definition = MediaPresetZoneRename.model_validate({"name": name})
        renamed = await asyncio.to_thread(_preset_zone_store().rename, zone_id, definition)
        return {key: renamed[key] for key in ("id", "name", "pipelineId")} | {"state": "renamed"}
    except FileNotFoundError as error:
        raise ValueError("Preset zone is unavailable.") from error
    except ValueError as error:
        raise ValueError(str(error)) from error
    except (MediaPipelineStoreError, MediaPresetZoneStoreError) as error:
        raise ValueError("Saved automation settings could not be updated safely. The file was left unchanged.") from error


@server.tool(
    name="officekit_media_rebind_preset_zone",
    title="Change a preset zone pipeline binding",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def rebind_preset_zone(
    zone_id: Annotated[StrictStr, Field(min_length=36, max_length=36)],
    pipeline_id: Annotated[StrictStr, Field(min_length=36, max_length=36)],
) -> dict[str, Any]:
    """Rebind a saved zone to an existing local pipeline without changing its ID or name."""
    try:
        definition = MediaPresetZoneRebind.model_validate({"pipelineId": pipeline_id})
        rebound = await asyncio.to_thread(_preset_zone_store().rebind, zone_id, definition)
        return {key: rebound[key] for key in ("id", "name", "pipelineId")} | {"state": "rebound"}
    except FileNotFoundError as error:
        raise ValueError(str(error)) from error
    except ValueError as error:
        raise ValueError(str(error)) from error
    except (MediaPipelineStoreError, MediaPresetZoneStoreError) as error:
        raise ValueError("Saved automation settings could not be updated safely. The file was left unchanged.") from error


@server.tool(
    name="officekit_media_delete_preset_zone",
    title="Delete a preset zone binding",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def delete_preset_zone(
    zone_id: Annotated[StrictStr, Field(min_length=36, max_length=36)],
) -> dict[str, str]:
    """Delete only the saved zone binding; media files and pipelines are not deleted."""
    try:
        deleted = await asyncio.to_thread(_preset_zone_store().delete, zone_id)
        if not deleted:
            raise ValueError("Preset zone is unavailable.")
        return {"id": zone_id, "state": "deleted"}
    except MediaPresetZoneStoreError as error:
        raise ValueError("Saved automation settings could not be updated safely. The file was left unchanged.") from error


@server.tool(
    name="officekit_media_run_pipeline",
    title="Run a saved media pipeline",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def run_pipeline(
    pipeline_id: Annotated[StrictStr, Field(min_length=36, max_length=36)],
    files: Annotated[list[StrictStr], Field(min_length=1, max_length=30)],
    output_directory: Annotated[StrictStr, Field(min_length=1, max_length=4096)],
    watermark_image: Annotated[StrictStr | None, Field(max_length=4096)] = None,
) -> dict[str, Any]:
    """Run one saved, allowlisted recipe on explicitly supplied local files.

    Choose a pipeline using officekit_media_list_pipelines. The recipe is loaded
    from OfficeKit's private local store; operations are not accepted from the
    caller. Its optional outputNameTemplate is applied to each new copy. Existing
    output files are never replaced.
    """
    try:
        pipeline = next(
            (item for item in await asyncio.to_thread(_pipeline_store().list) if item["id"] == pipeline_id),
            None,
        )
    except MediaPipelineStoreError as error:
        raise ValueError("Saved pipelines could not be read safely. The file was left unchanged.") from error
    if pipeline is None:
        raise ValueError("Saved pipeline is unavailable.")
    request = {
        "files": files,
        "operations": pipeline["operations"],
        "output_directory": output_directory,
        "output_name_template": pipeline.get("outputNameTemplate"),
    }
    if watermark_image is not None:
        request["watermark_image"] = watermark_image
    params = MediaPrepareInput.model_validate(request)
    return await asyncio.to_thread(_prepare_files, params)


def _prepare_files(params: MediaPrepareInput) -> dict[str, Any]:
    """Validate a recipe with the shared DTO and run the no-overwrite local CLI flow."""
    for operation in params.operations:
        MediaOperation.model_validate(operation)
    output_directory = Path(params.output_directory).expanduser()
    recipe_path = None
    try:
        descriptor, recipe_path = tempfile.mkstemp(prefix="officekit-media-mcp-", suffix=".json")
        with os.fdopen(descriptor, "w", encoding="utf-8") as recipe_file:
            json.dump(params.operations, recipe_file, separators=(",", ":"))
            recipe_file.flush()
            os.fsync(recipe_file.fileno())
        standard_output = StringIO()
        standard_error = StringIO()
        arguments = [
            "--recipe", recipe_path,
            "--output-dir", str(output_directory),
        ]
        if params.watermark_image is not None:
            arguments.extend(["--watermark-image", params.watermark_image])
        if params.output_name_template is not None:
            arguments.extend(["--name-template", params.output_name_template])
        arguments.extend(["--", *params.files])
        code = run_media_cli(arguments, stdout=standard_output, stderr=standard_error)
        if code != 0:
            raise ValueError("The local media job failed. Check the files and recipe, then retry.")
        result = json.loads(standard_output.getvalue())
        if result.get("state") != "complete" or not isinstance(result.get("results"), list):
            raise ValueError("The local media job returned an invalid result. Retry with a supported operation.")
        return result
    finally:
        if recipe_path is not None:
            try:
                os.unlink(recipe_path)
            except FileNotFoundError:
                pass


@server.tool(
    name="officekit_media_prepare_files",
    title="Prepare local media files",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def prepare_files(
    files: Annotated[list[str], Field(min_length=1, max_length=30)],
    operations: Annotated[list[dict[str, Any]], Field(min_length=1, max_length=8)],
    output_directory: Annotated[str, Field(min_length=1, max_length=4096)],
    watermark_image: Annotated[str | None, Field(max_length=4096)] = None,
    output_name_template: Annotated[str | None, Field(max_length=120)] = None,
) -> dict[str, Any]:
    """Prepare 1–30 local files with 1–8 allowlisted operations into a chosen output directory.

    The recipe uses the same strict operationId/options DTO as OfficeKit's local API and CLI. An optional output_name_template supports {name}, {ext}, {media}, plus bounded Clop %f/%e, date/time, %r, and %i filename tokens.
    Unsupported or malformed operations fail before processing. Existing files are never replaced.
    """
    request = {
        "files": files,
        "operations": operations,
        "output_directory": output_directory,
    }
    if watermark_image is not None:
        request["watermark_image"] = watermark_image
    if output_name_template is not None:
        request["output_name_template"] = output_name_template
    params = MediaPrepareInput.model_validate(request)
    return await asyncio.to_thread(_prepare_files, params)


def _prepare_preset(params: MediaPresetInput) -> dict[str, Any]:
    """Run one fixed built-in preset without exposing arbitrary operation strings."""
    standard_output = StringIO()
    standard_error = StringIO()
    arguments = [
        "--preset", params.preset,
        "--output-dir", str(Path(params.output_directory).expanduser()),
        "--collision-policy", params.collision_policy,
    ]
    if params.output_name_template is not None:
        arguments.extend(["--name-template", params.output_name_template])
    if params.factor is not None:
        arguments.extend(["--factor", str(params.factor)])
    if params.aspect_ratio is not None:
        arguments.extend(["--aspect-ratio", params.aspect_ratio])
    arguments.extend(["--", *params.files])
    code = run_media_cli(arguments, stdout=standard_output, stderr=standard_error)
    if code != 0:
        raise ValueError("The local preparation preset failed. Check the input types and output conflicts, then retry.")
    result = json.loads(standard_output.getvalue())
    if result.get("state") != "complete" or not isinstance(result.get("results"), list):
        raise ValueError("The local preparation preset returned an invalid result.")
    return result


@server.tool(
    name="officekit_media_run_preset",
    title="Run a built-in media preset",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def prepare_preset(
    files: Annotated[list[str], Field(min_length=1, max_length=30)],
    preset: Literal["optimize-image", "optimize-media", "to-webp", "downscale-image", "downscale-video", "downscale-audio", "crop-aspect", "sort-screenshots", "audio-to-mp3", "video-to-gif", "video-2x-silent", "uncrop-pdf"],
    output_directory: Annotated[str, Field(min_length=1, max_length=4096)],
    collision_policy: Literal["error", "suffix"] = "error",
    output_name_template: Annotated[str | None, Field(max_length=120)] = None,
    factor: Annotated[float | int | None, Field(ge=0, le=1)] = None,
    aspect_ratio: Annotated[str | None, Field(max_length=15)] = None,
) -> dict[str, Any]:
    """Run a fixed local preset; inputs are allowlisted, bounded, and never modified."""
    params = MediaPresetInput.model_validate({
        "files": files,
        "preset": preset,
        "output_directory": output_directory,
        "collision_policy": collision_policy,
        "output_name_template": output_name_template,
        "factor": factor,
        "aspect_ratio": aspect_ratio,
    })
    return await asyncio.to_thread(_prepare_preset, params)


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
