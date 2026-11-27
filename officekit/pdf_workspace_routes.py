"""Typed HTTP boundary for the local PDF workspace."""
import json
import os
import stat
import platform
import struct
import sys
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .engines.engine_file_responses import content_disposition_attachment
from .engines.engine_file_selections import checked_path, identity
from .engines.engine_pdf_workspace import PdfWorkspaceError
from .engines.engine_uploads import read_bounded_upload, UploadTooLargeError
from .engines.pdf_editor_models import RevisionCreate, OcrCreate


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Geometry(BaseModel):
    page: int
    width: float
    height: float
    rotation: int
    crop_box: list[float]


class Permissions(BaseModel):
    can_edit: bool
    can_sign: bool


class DocumentResponse(BaseModel):
    id: str
    name: str
    revision: int
    page_count: int
    pages: list[Geometry]
    signatures: list[dict]
    permissions: Permissions
    capabilities: dict[str, bool]
    expires_at: float
    warnings: list[str] = Field(default_factory=list)


class ObjectResponse(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: str
    kind: str
    page: int
    x: float
    y: float
    width: float
    height: float


class ObjectsResponse(BaseModel):
    revision: int
    page: int
    objects: list[ObjectResponse]
    has_more: bool = False


class JobResponse(BaseModel):
    id: str
    state: str
    phase: str = ''
    error: str | None = None
    error_code: str | None = None
    result_ref: str | None = None
    result: dict | list | None = None


class ProviderResponse(BaseModel):
    id: str
    kind: Literal['pkcs12', 'pkcs11']
    certificates: list[dict]


class ExportRequest(StrictModel):
    revision: int = Field(ge=0)


class RestoreRequest(StrictModel):
    base_revision: int = Field(ge=0)
    restore_revision: int = Field(ge=0)


class Placement(StrictModel):
    page: int = Field(ge=1, le=2000)
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)
    width: float = Field(gt=0, le=20000, allow_inf_nan=False)
    height: float = Field(gt=0, le=20000, allow_inf_nan=False)


class SignRequest(ExportRequest):
    provider_id: str = Field(min_length=1, max_length=100)
    certificate_id: str = Field(min_length=1, max_length=200)
    secret: SecretStr
    placement: Placement | None = None
    reason: str | None = Field(default=None, max_length=300)


class VerificationRequest(ExportRequest):
    network_consent: bool = False


class EmptyRequest(StrictModel):
    pass


class CancellationResponse(BaseModel):
    id: str
    state: str


class NativeProviderRequest(StrictModel):
    path: str = Field(min_length=1, max_length=4096)


def public_error(error):
    if isinstance(error, PdfWorkspaceError):
        return HTTPException(error.status, str(error))
    if isinstance(error, PermissionError):
        return HTTPException(403, 'Native file authorization is required.')
    if isinstance(error, FileNotFoundError):
        return HTTPException(404, 'The selected file is no longer available. Choose it again.')
    if isinstance(error, UploadTooLargeError):
        return HTTPException(413, 'The selected file exceeds its processing limit.')
    # Public messages belong to explicit engine exception types only; raw parser
    # and provider exceptions may contain filenames, keys or credentials.
    from .engines.engine_pdf_editor import PdfEditorError
    from .engines.engine_pdf_signing import PdfSigningError
    if isinstance(error, PdfEditorError):
        return HTTPException(error.status_code, error.public_message)
    if isinstance(error, PdfSigningError):
        return HTTPException(422, str(error))
    return HTTPException(422, 'The PDF operation could not be completed. Check the document and try again.')


def validate_provider_binary(path):
    """Reject a mismatched provider before giving it to the native loader."""
    with open(path, 'rb') as stream:
        header = stream.read(1024 * 1024)
    arm = platform.machine().lower() in {'arm64', 'aarch64'}
    compatible = False
    if sys.platform == 'darwin' and len(header) >= 8:
        cpu = 0x0100000C if arm else 0x01000007
        if header[:4] == b'\xcf\xfa\xed\xfe':
            compatible = struct.unpack_from('<I', header, 4)[0] == cpu
        elif header[:4] in (b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'):
            count = struct.unpack_from('>I', header, 4)[0]
            stride = 32 if header[:4] == b'\xca\xfe\xba\xbf' else 20
            compatible = 1 <= count <= 16 and len(header) >= 8 + count * stride and any(
                struct.unpack_from('>I', header, 8 + index * stride)[0] == cpu for index in range(count))
    elif sys.platform == 'win32' and len(header) >= 64 and header[:2] == b'MZ':
        offset = struct.unpack_from('<I', header, 60)[0]
        compatible = offset + 6 <= len(header) and header[offset:offset + 4] == b'PE\x00\x00' and struct.unpack_from('<H', header, offset + 4)[0] == (0xAA64 if arm else 0x8664)
    elif sys.platform.startswith('linux') and len(header) >= 20 and header[:6] == b'\x7fELF\x02\x01':
        compatible = struct.unpack_from('<H', header, 18)[0] == (183 if arm else 62)
    if not compatible:
        raise PdfWorkspaceError('The provider library does not match this operating system and processor.', 422)


def create_pdf_router(store, selections):
    router = APIRouter()

    def source(selection_id, max_bytes=None):
        maximum = store.MAX_BYTES if max_bytes is None else max_bytes
        selection = selections.get(selection_id)
        if len(selection.roots) != 1 or selection.roots[0][2]:
            raise PdfWorkspaceError('Choose exactly one original PDF file.')
        item = next(selections.iter_files(selection_id))
        def check():
            with selections.open_file(item):
                pass
        with selections.open_file(item) as stream:
            data = stream.read(maximum + 1)
        if len(data) > maximum:
            raise PdfWorkspaceError('The selected file exceeds its processing limit.', 413)
        return data, item.name, check

    @router.post('/api/pdf-documents', status_code=201, response_model=DocumentResponse)
    async def create_document(request: Request, file: UploadFile | None = File(default=None), selection_id: str | None = Form(default=None)):
        try:
            if bool(file) == bool(selection_id):
                raise PdfWorkspaceError('Choose exactly one PDF source.')
            if file:
                # Packaged desktops must select originals through the native picker.
                if os.environ.get('OFFICEKIT_API_TOKEN'):
                    raise PdfWorkspaceError('Choose the original PDF using the desktop file picker.', 403)
                data = await read_bounded_upload(file, store.MAX_BYTES)
                result = store.create(data, file.filename or 'document.pdf')
            else:
                data, name, check = source(selection_id)
                result = store.create(data, name, check)
            dto = DocumentResponse.model_validate(result)
            return JSONResponse(dto.model_dump(), status_code=201, headers={'Location': '/api/pdf-documents/' + dto.id})
        except Exception as error:
            raise public_error(error) from None

    @router.get('/api/pdf-documents/{document_id}', response_model=DocumentResponse)
    def document(document_id: str):
        try:
            return store.get(document_id)
        except Exception as error:
            raise public_error(error) from None

    @router.get('/api/pdf-documents/{document_id}/revisions/{revision}', response_model=DocumentResponse)
    def revision(document_id: str, revision: int):
        try:
            return store.get(document_id, revision)
        except Exception as error:
            raise public_error(error) from None

    @router.delete('/api/pdf-documents/{document_id}', status_code=204)
    def delete(document_id: str):
        try:
            store.delete(document_id)
            return Response(status_code=204)
        except Exception as error:
            raise public_error(error) from None

    @router.get('/api/pdf-documents/{document_id}/previews/{page}', responses={200: {'content': {'image/png': {}}}}, response_class=Response)
    def preview(document_id: str, page: int, revision: int = Query(default=0, ge=0), scale: float = Query(default=1, ge=.1, le=4, allow_inf_nan=False)):
        try:
            image, geometry = store.preview(document_id, page, revision, scale)
            return Response(image, media_type='image/png', headers={'X-PDF-Geometry': json.dumps(geometry), 'Cache-Control': 'no-store'})
        except Exception as error:
            raise public_error(error) from None

    @router.get('/api/pdf-documents/{document_id}/objects', response_model=ObjectsResponse)
    def objects(document_id: str, page: int = Query(default=1, ge=1), revision: int = Query(default=0, ge=0), offset: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=200)):
        try:
            return store.objects(document_id, page, revision, offset, limit)
        except Exception as error:
            raise public_error(error) from None

    @router.post('/api/pdf-documents/{document_id}/revisions', status_code=201, response_model=DocumentResponse)
    def revise(document_id: str, body: RevisionCreate | RestoreRequest, response: Response):
        try:
            result = (store.restore(document_id, body.base_revision, body.restore_revision)
                      if isinstance(body, RestoreRequest) else store.revise(document_id, body.base_revision, body.operations))
            response.headers['Location'] = f"/api/pdf-documents/{document_id}/revisions/{result['revision']}"
            return result
        except Exception as error:
            raise public_error(error) from None

    @router.post('/api/pdf-documents/{document_id}/exports', status_code=202, response_model=JobResponse)
    def export(document_id: str, body: ExportRequest):
        try:
            return store.export(document_id, body.revision)
        except Exception as error:
            raise public_error(error) from None

    @router.post('/api/pdf-documents/{document_id}/ocr-reviews', status_code=202, response_model=JobResponse)
    def ocr(document_id: str, body: OcrCreate):
        try:
            return store.ocr(document_id, body.base_revision, body.pages, body.language, body.mode)
        except Exception as error:
            raise public_error(error) from None

    @router.get('/api/pdf-documents/{document_id}/ocr-reviews/{review_id}', response_model=JobResponse)
    def ocr_review(document_id: str, review_id: str):
        try:
            result = store.ocr_review(document_id, review_id)
            return {'id': review_id, 'state': 'ready', 'phase': 'review', 'result': result}
        except Exception as error:
            raise public_error(error) from None

    @router.post('/api/pdf-signing-providers', status_code=201, response_model=ProviderResponse)
    async def provider(request: Request, kind: str = Form(default='pkcs12'), file: UploadFile | None = File(default=None), password: str = Form(default='', max_length=1024), selection_id: str | None = Form(default=None)):
        try:
            if kind != 'pkcs12' or bool(file) == bool(selection_id):
                raise PdfWorkspaceError('Choose a .p12 or .pfx certificate file.')
            if selection_id:
                data, _, _ = source(selection_id, 2 * 1024 * 1024)
            else:
                if os.environ.get('OFFICEKIT_API_TOKEN'):
                    raise PdfWorkspaceError('Choose the certificate with the desktop file picker.', 403)
                data = await read_bounded_upload(file, 2 * 1024 * 1024)
            return store.provider_file(data, password)
        except Exception as error:
            raise public_error(error) from None

    @router.post('/api/pdf-signing-providers/native', status_code=201, response_model=ProviderResponse)
    def native_provider(body: NativeProviderRequest, request: Request):
        try:
            selections.authorize(request.headers.get('X-OfficeKit-Native-Grant', ''))
            path = checked_path(body.path)
            value = os.lstat(path)
            if not stat.S_ISREG(value.st_mode) or Path(path).suffix.lower() not in {'.dylib', '.dll', '.so'}:
                raise PdfWorkspaceError('Choose an installed PKCS#11 provider library.')
            if os.name != 'nt' and value.st_mode & 0o022:
                raise PdfWorkspaceError('Provider libraries must not be writable by other users.', 403)
            validate_provider_binary(path)
            expected = identity(value)
            def check():
                checked_path(path)
                if identity(os.lstat(path)) != expected:
                    raise PdfWorkspaceError('Provider library changed. Choose it again.', 409)
            return store.provider_native(Path(path), check)
        except Exception as error:
            raise public_error(error) from None

    @router.post('/api/pdf-documents/{document_id}/signatures', status_code=202, response_model=JobResponse)
    def sign(document_id: str, body: SignRequest):
        try:
            secret = body.secret.get_secret_value()
            if len(secret) > 1024:
                raise PdfWorkspaceError('Credential exceeds its input limit.')
            return store.sign(document_id, body.revision, body.provider_id, body.certificate_id, secret, body.placement, body.reason)
        except Exception as error:
            raise public_error(error) from None

    @router.get('/api/pdf-documents/{document_id}/signatures/{job_id}', response_model=JobResponse)
    def signature(document_id: str, job_id: str):
        try:
            store.get(document_id)
            if store.jobs.get(job_id, {}).get('document') != document_id:
                raise PdfWorkspaceError('Signature job is unavailable.', 404)
            return store.job(job_id)
        except Exception as error:
            raise public_error(error) from None

    @router.post('/api/pdf-documents/{document_id}/verifications', status_code=202, response_model=JobResponse)
    def verify(document_id: str, body: VerificationRequest):
        try:
            if body.network_consent:
                raise PdfWorkspaceError('Online trust checks are unavailable. Offline integrity verification is supported.', 503)
            return store.verify(document_id, body.revision)
        except Exception as error:
            raise public_error(error) from None

    @router.get('/api/pdf-workspace-jobs/{job_id}', response_model=JobResponse)
    def job(job_id: str):
        try:
            return store.job(job_id)
        except Exception as error:
            raise public_error(error) from None

    @router.post('/api/pdf-workspace-jobs/{job_id}/cancellations', status_code=202, response_model=CancellationResponse)
    def cancel(job_id: str, body: EmptyRequest):
        try:
            return store.cancel(job_id)
        except Exception as error:
            raise public_error(error) from None

    @router.get('/api/pdf-workspace-artifacts/{artifact_id}', response_class=Response, responses={200: {'content': {'application/pdf': {}}}})
    def artifact(artifact_id: str):
        try:
            data, name = store.artifact(artifact_id)
            return Response(data, media_type='application/pdf', headers={'Content-Disposition': content_disposition_attachment(name), 'Cache-Control': 'no-store'})
        except Exception as error:
            raise public_error(error) from None

    return router
