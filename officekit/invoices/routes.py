"""Typed authenticated-local invoice resource router; no filesystem paths from web callers."""

import io
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import Field

from . import models as m
from .domain import InvoiceError, InvoiceService, report_csv
from .pdf import normalize_logo, render_pdf
from .storage import InvoiceStorageError

PREFIX = "/api/invoice-libraries"
BODY_LIMITS = {
    PREFIX: 4096,
    "/api/invoice-restorations": 4096,
    PREFIX + "/{library_id}/businesses": 1024 * 1024,
    PREFIX + "/{library_id}/businesses/{identifier}": 1024 * 1024,
    PREFIX + "/{library_id}/clients": 16384,
    PREFIX + "/{library_id}/clients/{identifier}": 16384,
    PREFIX + "/{library_id}/items": 16384,
    PREFIX + "/{library_id}/items/{identifier}": 16384,
    PREFIX + "/{library_id}/documents": 2 * 1024 * 1024,
    PREFIX + "/{library_id}/documents/{identifier}": 2 * 1024 * 1024,
    PREFIX + "/{library_id}/schedules": 2 * 1024 * 1024,
    PREFIX + "/{library_id}/schedules/{identifier}": 2 * 1024 * 1024,
    PREFIX + "/{library_id}/document-previews": 2 * 1024 * 1024,
    PREFIX + "/{library_id}/documents/{identifier}/transitions": 4096,
    PREFIX + "/{library_id}/documents/{identifier}/payments": 4096,
    PREFIX + "/{library_id}/documents/{identifier}/payment-corrections": 8192,
    PREFIX + "/{library_id}/document-conversions": 4096,
    PREFIX + "/{library_id}/recurring-draft-batches": 32768,
    PREFIX + "/{library_id}/assets": 4096,
    PREFIX + "/{library_id}/reconnections": 4096,
    PREFIX + "/{library_id}/reloads": 4096,
    PREFIX + "/{library_id}/backups": 4096,
    PREFIX + "/{library_id}/documents/{identifier}/archives": 4096,
}
EXPOSE_HEADERS = ("Content-Disposition", "Content-Length")


class Empty(m.Model):
    pass


class Restoration(m.Model):
    selection_id: m.Identifier
    backup_selection_id: m.Identifier


class HistoryEntry(m.Model):
    revision: int
    changed_at: str
    action: str = ""
    summary: str = ""
    business_id: str | None = None
    document_id: str | None = None


class History(m.Model):
    items: list[HistoryEntry]
    next_cursor: str | None = None


class InvoiceRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def invoice_handler(request):
            try:
                return await handler(request)
            except (InvoiceError, InvoiceStorageError) as error:
                return JSONResponse({"error": {"code": error.code, "message": str(error), "details": []}}, status_code=error.status)
            except PermissionError:
                return JSONResponse({"error": {"code": "NATIVE_AUTHORIZATION_REQUIRED", "message": "Choose or reconnect this folder through OfficeKit.", "details": []}}, status_code=403)
            except (RequestValidationError, ValueError):
                return JSONResponse({"error": {"code": "INVALID_INVOICE_INPUT", "message": "Invoice input is invalid or exceeds supported limits.", "details": []}}, status_code=422)
        return invoice_handler


def binary_response(data, filename, mime, inline=False):
    return Response(data, media_type=mime, headers={"Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{filename}"', "Content-Length": str(len(data)), "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


def create_invoice_router(libraries, release_profile="development"):
    service = InvoiceService(libraries)

    def available():
        if release_profile == "private-beta":
            raise InvoiceError("INVOICES_UNAVAILABLE", "Invoices are not available in this release profile.", 403)

    router = APIRouter(route_class=InvoiceRoute, dependencies=[Depends(available)])

    def library_state(library_id):
        state = libraries.get(library_id).read()
        binding = next(item for item in libraries.list_bindings() if item["id"] == library_id)
        return {**binding, "status": "ready", "revision": state["revision"], "businesses": list(state["businesses"].values()), "capabilities": {"write": True, "direct_folder": True, "sync": False}}

    @router.get(PREFIX, response_model=m.Page)
    def bindings():
        return {"items": libraries.list_bindings(), "next_cursor": None}

    @router.post(PREFIX, status_code=201, response_model=m.LibraryState)
    def attach(body: m.Attachment, response: Response):
        result = libraries.attach(body.selection_id)
        response.headers["Location"] = PREFIX + "/" + result["id"]
        return result

    @router.post("/api/invoice-restorations", status_code=201, response_model=m.LibraryState)
    def restore(body: Restoration, response: Response):
        result = libraries.restore(body.selection_id, body.backup_selection_id)
        response.headers["Location"] = PREFIX + "/" + result["id"]
        return result

    @router.get(PREFIX + "/{library_id}", response_model=m.LibraryState)
    def state(library_id: m.Identifier):
        return library_state(library_id)

    @router.post(PREFIX + "/{library_id}/reconnections", response_model=m.LibraryState)
    def reconnect(library_id: m.Identifier, body: Empty, request: Request):
        return libraries.reconnect(library_id, request.headers.get("X-OfficeKit-Native-Grant", ""))

    @router.post(PREFIX + "/{library_id}/reloads", response_model=m.LibraryState)
    def reload(library_id: m.Identifier, body: Empty):
        libraries.get(library_id).reload()
        return library_state(library_id)

    @router.get(PREFIX + "/{library_id}/history", response_model=History)
    def history(library_id: m.Identifier):
        return {"items": libraries.get(library_id).history(), "next_cursor": None}

    @router.post(PREFIX + "/{library_id}/backups", responses={200: {"content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}}}, response_class=Response)
    def backup(library_id: m.Identifier, body: Empty):
        return binary_response(libraries.get(library_id).backup(), "officekit-invoices-backup.zip", "application/zip")

    def resource(collection, body_model, record_model):
        path = PREFIX + "/{library_id}/" + collection

        def page(library_id: m.Identifier, business_id: m.Identifier | None = None, search: str = Query(default="", max_length=160), limit: int = Query(default=50, ge=1, le=100), cursor: str | None = Query(default=None, max_length=512)):
            return service.page(library_id, collection, business_id, search, limit=limit, cursor=cursor)

        def create(library_id: m.Identifier, body: body_model, response: Response):
            result = service.save(library_id, collection, body)
            response.headers["Location"] = PREFIX + "/" + library_id + "/" + collection + "/" + result["id"]
            return result

        def read(library_id: m.Identifier, identifier: m.Identifier):
            return service.record(library_id, collection, identifier)

        def update(library_id: m.Identifier, identifier: m.Identifier, body: body_model):
            return service.save(library_id, collection, body, identifier)

        router.add_api_route(path, page, methods=["GET"], response_model=m.Page, name=f"invoice_{collection}_page")
        router.add_api_route(path, create, methods=["POST"], status_code=201, response_model=record_model, name=f"invoice_{collection}_create")
        router.add_api_route(path + "/{identifier}", read, methods=["GET"], response_model=record_model, name=f"invoice_{collection}_read")
        router.add_api_route(path + "/{identifier}", update, methods=["PUT"], response_model=record_model, name=f"invoice_{collection}_update")

    resource("businesses", m.BusinessWrite, m.BusinessRecord)
    resource("clients", m.ClientWrite, m.ClientRecord)
    resource("items", m.ItemWrite, m.ItemRecord)
    resource("schedules", m.ScheduleWrite, m.ScheduleRecord)

    @router.get(PREFIX + "/{library_id}/documents", response_model=m.Page)
    def documents(library_id: m.Identifier, business_id: m.Identifier | None = None, search: str = Query(default="", max_length=160), status: str | None = Query(default=None, max_length=40), kind: Literal["invoice", "quote", "estimate"] | None = None, start: date | None = None, end: date | None = None, sort: Literal["date", "amount"] = "date", order: Literal["asc", "desc"] = "desc", limit: int = Query(default=50, ge=1, le=100), cursor: str | None = Query(default=None, max_length=512)):
        return service.page(library_id, "documents", business_id, search, status, kind, start.isoformat() if start else None, end.isoformat() if end else None, sort, order, limit, cursor)

    @router.post(PREFIX + "/{library_id}/documents", status_code=201, response_model=m.DocumentRecord)
    def new_document(library_id: m.Identifier, body: m.DraftWrite, response: Response):
        result = service.save(library_id, "documents", body)
        response.headers["Location"] = PREFIX + "/" + library_id + "/documents/" + result["id"]
        return result

    @router.get(PREFIX + "/{library_id}/documents/{identifier}", response_model=m.DocumentRecord)
    def document(library_id: m.Identifier, identifier: m.Identifier):
        return service.record(library_id, "documents", identifier)

    @router.put(PREFIX + "/{library_id}/documents/{identifier}", response_model=m.DocumentRecord)
    def update_document(library_id: m.Identifier, identifier: m.Identifier, body: m.DraftWrite):
        return service.save(library_id, "documents", body, identifier)

    @router.post(PREFIX + "/{library_id}/documents/{identifier}/transitions", response_model=m.DocumentRecord)
    def transition(library_id: m.Identifier, identifier: m.Identifier, body: m.Transition):
        return service.transition(library_id, identifier, body)

    @router.post(PREFIX + "/{library_id}/documents/{identifier}/archives", response_model=m.DocumentRecord)
    def archive(library_id: m.Identifier, identifier: m.Identifier, body: m.Revision):
        return service.archive(library_id, identifier, body.expected_revision)

    @router.post(PREFIX + "/{library_id}/document-conversions", status_code=201, response_model=m.ConversionResult)
    def conversion(library_id: m.Identifier, body: m.Conversion):
        return service.convert(library_id, body)

    @router.get(PREFIX + "/{library_id}/documents/{identifier}/payments", response_model=m.PaymentPage)
    def payments(library_id: m.Identifier, identifier: m.Identifier):
        return service.payments(library_id, identifier)

    @router.post(PREFIX + "/{library_id}/documents/{identifier}/payments", status_code=201, response_model=m.PaymentResult)
    def payment(library_id: m.Identifier, identifier: m.Identifier, body: m.Payment):
        return service.payment(library_id, identifier, body)

    @router.post(PREFIX + "/{library_id}/documents/{identifier}/payment-corrections", status_code=201, response_model=m.PaymentResult)
    def correction(library_id: m.Identifier, identifier: m.Identifier, body: m.PaymentCorrection):
        return service.payment(library_id, identifier, body, correction=True)

    @router.post(PREFIX + "/{library_id}/recurring-draft-batches", response_model=m.RecurringResult)
    def recurring(library_id: m.Identifier, body: m.RecurringBatch):
        return service.recurring(library_id, body)

    @router.post(PREFIX + "/{library_id}/document-previews", response_class=Response, responses={200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}})
    def preview(library_id: m.Identifier, body: m.Preview):
        return binary_response(render_pdf(service.preview(library_id, body), libraries.get(library_id)), "invoice-preview.pdf", "application/pdf", inline=True)

    @router.get(PREFIX + "/{library_id}/documents/{identifier}/pdf", response_class=Response, responses={200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}})
    def pdf(library_id: m.Identifier, identifier: m.Identifier):
        value = service.record(library_id, "documents", identifier)
        return binary_response(render_pdf(value, libraries.get(library_id)), "invoice-" + identifier + ".pdf", "application/pdf")

    @router.post(PREFIX + "/{library_id}/assets", status_code=201, response_model=m.AssetRecord)
    def asset(library_id: m.Identifier, body: m.AssetWrite, response: Response):
        repo = libraries.get(library_id)
        selection = libraries.selections.get(body.selection_id)
        if len(selection.roots) != 1 or selection.roots[0][2]:
            raise InvoiceError("INVALID_LOGO_SELECTION", "Choose one logo image.")
        selected = next(libraries.selections.iter_files(body.selection_id))
        with libraries.selections.open_file(selected) as source:
            raw, width, height = normalize_logo(source.read(5 * 1024 * 1024 + 1))
        identifier = repo.put_asset(raw)
        result = repo.transaction(body.expected_revision, lambda state: {"id": identifier, "width": width, "height": height, "mime": "image/png", "bytes": len(raw)})
        response.headers["Location"] = PREFIX + "/" + library_id + "/assets/" + identifier
        return result

    @router.get(PREFIX + "/{library_id}/assets/{identifier}", response_class=Response, responses={200: {"content": {"image/png": {"schema": {"type": "string", "format": "binary"}}}}})
    def read_asset(library_id: m.Identifier, identifier: str = Path(pattern=r"^[0-9a-f]{64}$")):
        return binary_response(libraries.get(library_id).read_asset(identifier), "logo.png", "image/png", inline=True)

    @router.get(PREFIX + "/{library_id}/reports", response_model=m.InvoiceReport)
    def report(library_id: m.Identifier, business_id: m.Identifier, currency_id: m.Identifier, start: date, end: date, client_id: m.Identifier | None = None):
        return service.report(library_id, business_id, currency_id, start, end, client_id)

    @router.get(PREFIX + "/{library_id}/reports.csv", response_class=Response, responses={200: {"content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}}}})
    def csv_report(library_id: m.Identifier, business_id: m.Identifier, currency_id: m.Identifier, start: date, end: date, client_id: m.Identifier | None = None):
        return binary_response(report_csv(service.report(library_id, business_id, currency_id, start, end, client_id)), "invoice-report.csv", "text/csv")

    return router
