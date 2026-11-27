"""Upload limits and fixed public messages shared by ``app.py`` and slice routers.

Slice routers import from here instead of from ``app`` (which would be a
circular import) or copying the values.
"""

from fastapi import HTTPException, UploadFile

from officekit.engines.engine_uploads import UploadTooLargeError, read_bounded_upload

MAX_API_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_MULTIPART_OVERHEAD_BYTES = 4 * 1024 * 1024
PDF_INPUT_ERROR_MESSAGE = "The PDF file is invalid or the requested operation is unsupported."


async def read_api_upload(file: UploadFile) -> bytes:
    try:
        return await read_bounded_upload(file, MAX_API_UPLOAD_BYTES)
    except UploadTooLargeError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
