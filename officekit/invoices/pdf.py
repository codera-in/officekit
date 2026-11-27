"""Local invoice PDF layouts and safe raster logo normalization."""

import io
import os
import sys
from functools import lru_cache
from xml.sax.saxutils import escape

from PIL import Image, UnidentifiedImageError
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image as PdfImage, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.platypus.doctemplate import LayoutError

from .domain import fail, money

MAX_LOGO_BYTES = 5 * 1024 * 1024
MAX_LOGO_PIXELS = 16_000_000
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 100


def normalize_logo(data):
    if len(data) > MAX_LOGO_BYTES:
        fail("LOGO_TOO_LARGE", "Choose a logo no larger than 5 MiB.", 413)
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.width * source.height > MAX_LOGO_PIXELS or source.format not in {"PNG", "JPEG", "WEBP"}:
                fail("INVALID_LOGO", "Choose a PNG, JPEG or WebP logo within the supported dimensions.")
            source.load()
            normalized = source.convert("RGBA")
            output = io.BytesIO()
            normalized.save(output, "PNG")
            payload = output.getvalue()
            if len(payload) > MAX_LOGO_BYTES:
                fail("LOGO_TOO_LARGE", "The normalized logo exceeds 5 MiB.", 413)
            return payload, source.width, source.height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        fail("INVALID_LOGO", "The selected logo could not be decoded.")


def format_currency(value, currency):
    text = money(value, currency["precision"])
    integer, _, fraction = text.partition(".")
    negative = integer.startswith("-")
    integer = integer.lstrip("-")
    groups = []
    if currency["grouping"] != "none":
        width = 3
        while integer:
            groups.insert(0, integer[-width:])
            integer = integer[:-width]
            if currency["grouping"] == "indian":
                width = 2
        integer = currency["grouping_separator"].join(groups)
    text = ("−" if negative else "") + integer + (currency["decimal_separator"] + fraction if currency["precision"] else "")
    if currency["placement"] == "after":
        return text + " " + currency["symbol"]
    if currency["placement"] == "code":
        return currency["code"] + " " + text
    return currency["symbol"] + text


@lru_cache(maxsize=1)
def invoice_font():
    root = getattr(sys, "_MEIPASS", None)
    path = os.path.join(root, "fonts", "NotoSans-Regular.ttf") if root else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "assets", "fonts", "NotoSans-Regular.ttf"))
    if not os.path.isfile(path):
        fail("PDF_FONT_UNAVAILABLE", "The packaged invoice font is unavailable.", 503)
    pdfmetrics.registerFont(TTFont("OfficeKitInvoice", path))
    return "OfficeKitInvoice"


def render_pdf(document, repository=None):
    template, currency = document["template"], document["currency"]
    font = invoice_font()
    chars = pdfmetrics.getFont(font).face.charWidths
    normal = ParagraphStyle("invoice", fontName=font, fontSize=9, leading=13, spaceAfter=5)
    title = ParagraphStyle("title", parent=normal, fontSize=26 if template["layout"] == "Bold" else 20, leading=30, textColor=colors.HexColor(template["accent"]), spaceAfter=14)
    heading = ParagraphStyle("heading", parent=normal, fontSize=13, leading=18, spaceBefore=12, spaceAfter=7)

    def paragraph(value, style=normal):
        value = str(value)
        if any(ord(character) not in chars and character not in "\n\r\t" for character in value):
            fail("PDF_UNSUPPORTED_GLYPH", "The invoice contains characters unsupported by the packaged font.")
        return Paragraph(escape(value).replace("\n", "<br/>"), style)

    page_size = A4 if template["paper"] == "A4" else letter
    margin = 30 if template["layout"] == "Compact" else 42
    width = page_size[0] - 2 * margin
    output = io.BytesIO()
    pdf = SimpleDocTemplate(output, pagesize=page_size, leftMargin=margin, rightMargin=margin, topMargin=margin, bottomMargin=margin, title=document["number"], author=document["business"]["name"], invariant=1)
    flow = []
    if template["logo_id"]:
        data = repository.read_asset(template["logo_id"])
        with Image.open(io.BytesIO(data)) as image:
            size = {"small": 36, "medium": 54, "large": 78}[template["logo_size"]]
            logo = PdfImage(io.BytesIO(data), width=size, height=size * image.height / image.width)
        logo.hAlign = {"left": "LEFT", "center": "CENTER", "right": "RIGHT"}[template["logo_placement"]]
        flow.extend([logo, Spacer(1, 8)])
    business, client, draft = document["business"], document["client"], document["draft"]
    flow.extend([paragraph(business["name"], heading), paragraph(business["address"]), paragraph(business["contact"])])
    for registration in business["registrations"]:
        if registration["visible"]:
            flow.append(paragraph(registration["label"] + ": " + registration["value"]))
    labels = template["labels"]
    default_title = document["kind"].upper()
    flow.extend([Spacer(1, 10), paragraph(labels.get("title", default_title), title), paragraph(document["number"] + (" · DRAFT" if document["state"] == "draft" else ""))])
    flow.append(paragraph(labels.get("bill_to", "Bill to"), heading))
    flow.extend([paragraph(client["name"]), paragraph(client["address"]), paragraph(client["contact"])])
    if client["customer_reference"]:
        flow.append(paragraph(client["customer_reference"]))
    flow.append(paragraph(labels.get("issue_date", "Issue date") + ": " + draft["issue_date"]))
    for key, label in (("due_date", "Due date"), ("valid_until", "Valid until")):
        if draft[key]:
            flow.append(paragraph(labels.get(key, label) + ": " + draft[key]))
    flow.append(Spacer(1, 12))
    columns = template["columns"]
    table_rows = [[paragraph(labels.get(column, column.replace("_", " ").title())) for column in columns]]
    previous_section = None
    for index, line in enumerate(draft["lines"]):
        if line["section"] and line["section"] != previous_section:
            table_rows.append([paragraph(line["section"], heading)] + [""] * (len(columns) - 1))
            previous_section = line["section"]
        values = {**line, "date": line["date"] or "", "rate": format_currency(line["rate"], currency), "amount": format_currency(document["totals"]["lines"][index]["total"], currency)}
        table_rows.append([paragraph(values[column]) for column in columns])
    weights = [4 if column == "description" else 1.4 for column in columns]
    table = Table(table_rows, colWidths=[width * weight / sum(weights) for weight in weights], repeatRows=1, hAlign="LEFT", splitByRow=1, splitInRow=1)
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3f6")), ("LINEBELOW", (0, 0), (-1, 0), .5, colors.HexColor(template["accent"])), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    flow.extend([table, Spacer(1, 12)])
    totals = document["totals"]
    rows = [("Subtotal", totals["subtotal"]), ("Discount", totals["discount"])]
    rows.extend((tax["label"] + " · " + tax["rate"] + "%" + (" · " + tax["registration_label"] + " " + tax["registration_number"] if tax["registration_number"] else ""), tax["amount"]) for tax in totals["taxes"])
    rows.extend([("Total", totals["total"]), ("Paid", document["paid"]), ("Balance due", document["balance"])])
    summary = Table([[paragraph(labels.get(label.lower().replace(" ", "_"), label)), paragraph(format_currency(value, currency))] for label, value in rows], colWidths=[width * .35, width * .3], hAlign="RIGHT")
    summary.setStyle(TableStyle([("LINEABOVE", (0, -3), (-1, -3), .5, colors.HexColor(template["accent"])), ("ALIGN", (1, 0), (1, -1), "RIGHT")]))
    flow.append(summary)
    for method in document["payment_methods"]:
        flow.append(paragraph(method["label"], heading))
        for field in method["fields"]:
            if field["visible"]:
                flow.append(paragraph(field["label"] + ": " + field["value"]))
        flow.extend([paragraph(method["link"]), paragraph(method["instructions"])])
        if method["qr_payload"]:
            import qrcode
            qr = qrcode.make(method["qr_payload"])
            image = io.BytesIO()
            qr.save(image, "PNG")
            flow.append(PdfImage(io.BytesIO(image.getvalue()), width=72, height=72))
    for label, value in (("Notes", draft["notes"]), ("Payment terms", draft["terms"]), ("", template["footer"])):
        if value:
            flow.extend([paragraph(label, heading), paragraph(value)])

    def page_footer(canvas, doc):
        if doc.page > MAX_PDF_PAGES:
            raise ValueError("invoice-page-limit")
        canvas.setFont(font, 8)
        canvas.drawRightString(page_size[0] - margin, 18, str(doc.page))

    try:
        pdf.build(flow, onFirstPage=page_footer, onLaterPages=page_footer)
    except (ValueError, LayoutError) as error:
        if "invoice-page-limit" in str(error):
            fail("PDF_TOO_LARGE", "The invoice exceeds the supported PDF page limit.", 413)
        fail("PDF_LAYOUT_UNAVAILABLE", "The invoice could not fit the selected PDF layout.")
    result = output.getvalue()
    if len(result) > MAX_PDF_BYTES:
        fail("PDF_TOO_LARGE", "The invoice exceeds the supported PDF size.", 413)
    return result
