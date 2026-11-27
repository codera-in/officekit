"""Bounded exports for immutable calculator and tool-result snapshots."""

import csv as csv_module
from datetime import datetime
import html
import io
import json
import math
import os
import re
import sys
import threading
import unicodedata
import zipfile
from io import BytesIO
from xml.sax.saxutils import escape

from openpyxl import Workbook


class ResultExportEngine:
    MAX_TEXT_BYTES = 1_048_576
    MAX_ROWS = 10_000
    MAX_COLUMNS = 40
    MAX_XLSX_CELLS = 100_000
    MAX_XLSX_BYTES = 8 * 1_048_576
    MAX_PPTX_SLIDES = 200
    MAX_PPTX_BYTES = 8 * 1_048_576
    MAX_PDF_PAGES = 200
    MAX_PDF_BYTES = 8 * 1_048_576
    MAX_IMAGE_BYTES = 8 * 1_048_576
    TOOL_ID = re.compile(r"[a-z0-9][a-z0-9_.-]{0,79}\Z")
    SNAPSHOT_KEYS = frozenset(("tool_id", "title", "created_at", "inputs", "results", "assumptions", "tables"))
    _PDF_FONT_LOCK = threading.Lock()
    _PDF_FONTS = None

    @classmethod
    def pdf(cls, snapshot, exported_at: datetime, include_attribution: bool = False) -> bytes:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import Paragraph as ReportLabParagraph
        from reportlab.platypus import (
            PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
        )

        report = cls._validated_snapshot(snapshot, exported_at, include_attribution)

        row_work = sum(max(1, (len(table["rows"]) + 19) // 20) * ((len(table["columns"]) + 5) // 6)
                       for table in report["tables"])
        detail_work = sum((len(items) + 23) // 24 for items in (report["inputs"], report["results"], report["assumptions"]))
        if 1 + row_work + detail_work > cls.MAX_PDF_PAGES:
            raise ValueError(f"PDF report exceeds the supported page limit of {cls.MAX_PDF_PAGES}")

        with cls._PDF_FONT_LOCK:
            if cls._PDF_FONTS is None:
                font_candidates = []
                if getattr(sys, "_MEIPASS", None):
                    bundled_tamil = os.path.join(sys._MEIPASS, "fonts", "NotoSansTamil-Regular.ttf")
                else:
                    bundled_tamil = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "fonts", "NotoSansTamil-Regular.ttf")
                if sys.platform == "darwin":
                    font_candidates = [
                        ("OfficeKitText", "/System/Library/Fonts/Supplemental/Arial.ttf", 0),
                        ("OfficeKitTextBold", "/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0),
                        ("OfficeKitTamil", bundled_tamil, 0),
                        ("OfficeKitTamil", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 0),
                    ]
                elif os.name == "nt":
                    font_candidates = [
                        ("OfficeKitText", r"C:\Windows\Fonts\arial.ttf", 0),
                        ("OfficeKitTextBold", r"C:\Windows\Fonts\arialbd.ttf", 0),
                        ("OfficeKitTamil", bundled_tamil, 0),
                        ("OfficeKitTamil", r"C:\Windows\Fonts\l_10646.ttf", 0),
                    ]
                else:
                    font_candidates = [
                        ("OfficeKitText", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
                        ("OfficeKitTextBold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
                        ("OfficeKitTamil", bundled_tamil, 0),
                        ("OfficeKitTamil", "/usr/share/fonts/truetype/noto/NotoSansTamil-Regular.ttf", 0),
                    ]
                registered = []
                for name, path, subfont_index in font_candidates:
                    if not os.path.isfile(path):
                        continue
                    try:
                        pdfmetrics.registerFont(TTFont(name, path, subfontIndex=subfont_index))
                    except Exception:
                        continue
                    registered.append(name)
                if "OfficeKitText" not in registered:
                    raise ValueError("PDF fonts are unavailable on this computer")
                cls._PDF_FONTS = tuple(registered)

        fonts = {name: pdfmetrics.getFont(name) for name in cls._PDF_FONTS}
        regular = fonts["OfficeKitText"]

        def safe_text(value):
            return cls._xlsx_safe_text(value if isinstance(value, str) else cls._display(value))

        def paragraph_markup(value):
            text = safe_text(value)
            runs = []
            last_font = None
            segment = []
            for character in text:
                codepoint = ord(character)
                selected = next((name for name in cls._PDF_FONTS if codepoint in fonts[name].face.charWidths), None)
                if selected is None:
                    raise ValueError("PDF fonts cannot display one or more result characters")
                if selected != last_font and segment:
                    runs.append((last_font, "".join(segment)))
                    segment = []
                last_font = selected
                segment.append(character)
            if segment:
                runs.append((last_font, "".join(segment)))
            return "".join(
                f'<font name="{name}">{escape(value, {"\\\"": "&quot;", "\\\'": "&apos;"})}</font>'
                for name, value in runs
            )

        styles = getSampleStyleSheet()
        body_style = ParagraphStyle(
            "OfficeKitBody", parent=styles["BodyText"], fontName="OfficeKitText", fontSize=9,
            leading=12, alignment=TA_LEFT, shaping=1,
        )
        title_style = ParagraphStyle("OfficeKitTitle", parent=body_style, fontSize=20, leading=25, spaceAfter=12)
        heading_style = ParagraphStyle("OfficeKitHeading", parent=body_style, fontSize=13, leading=17, spaceBefore=10, spaceAfter=6)
        small_style = ParagraphStyle("OfficeKitSmall", parent=body_style, fontSize=8, leading=10)

        class SearchableParagraph(ReportLabParagraph):
            """Keep shaped glyphs visible and add an invisible Unicode search layer."""

            def __init__(self, text, style, **kwargs):
                super().__init__(text, style, **kwargs)
                plain_style = ParagraphStyle(
                    f"{style.name}Unshaped", parent=style, shaping=0,
                )
                self.unicode_layer = ReportLabParagraph(text, plain_style, **kwargs)

            def wrap(self, available_width, available_height):
                shaped = super().wrap(available_width, available_height)
                self.unicode_layer.wrap(available_width, available_height)
                return shaped

            def drawOn(self, canvas, x, y, _sW=0):
                super().drawOn(canvas, x, y, _sW)
                canvas.saveState()
                canvas._code.append("3 Tr")
                self.unicode_layer.drawOn(canvas, x, y, _sW)
                canvas._code.append("0 Tr")
                canvas.restoreState()

        def paragraph(text, style):
            return SearchableParagraph(text, style)
        output = BytesIO()

        def draw_footer(canvas, document):
            canvas.saveState()
            canvas.setFont("OfficeKitText", 8)
            canvas.setFillColor(colors.HexColor("#64748b"))
            canvas.drawString(0.55 * inch, 0.36 * inch, f"Page {document.page}")
            if report["include_attribution"]:
                canvas.drawRightString(7.95 * inch, 0.36 * inch, "Generated with OfficeKit · officekit.app")
            canvas.restoreState()

        document = SimpleDocTemplate(
            output, pagesize=letter, rightMargin=0.55 * inch, leftMargin=0.55 * inch,
            topMargin=0.55 * inch, bottomMargin=0.62 * inch,
            title=safe_text(report["title"]), author="OfficeKit" if report["include_attribution"] else "",
            subject=f"{report['tool_id']} result", creator="OfficeKit" if report["include_attribution"] else "",
        )
        story = [paragraph(paragraph_markup(report["title"]), title_style)]
        metadata = [
            ("Tool", report["tool_id"]),
            ("Operation time", f"Operation time: {report['created_at']}"),
            ("Exported", f"Exported: {report['exported_at']}"),
        ]
        story.extend(paragraph(paragraph_markup(value), body_style) for _, value in metadata)

        def add_values(title, values):
            if not values:
                return
            story.extend((Spacer(1, 8), Paragraph(paragraph_markup(title), heading_style)))
            for item in values:
                value = safe_text(item["value"])
                unit = f" {safe_text(item['unit'])}" if item["unit"] is not None else ""
                story.append(paragraph(
                    f"<b>{paragraph_markup(item['name'])}</b>: {paragraph_markup(value + unit)}", body_style,
                ))

        add_values("Inputs", report["inputs"])
        add_values("Results", report["results"])
        if report["assumptions"]:
            story.extend((Spacer(1, 8), Paragraph("Assumptions", heading_style)))
            for assumption in report["assumptions"]:
                story.append(paragraph(f"• {paragraph_markup(assumption)}", body_style))

        for table in report["tables"]:
            for column_start in range(0, len(table["columns"]), 6):
                column_end = min(column_start + 6, len(table["columns"]))
                if story:
                    story.append(PageBreak())
                suffix = f" — Columns {column_start + 1}-{column_end}" if len(table["columns"]) > 6 else ""
                story.append(paragraph(paragraph_markup(table["title"] + suffix), heading_style))
                selected_columns = table["columns"][column_start:column_end]
                data = [[paragraph(f"<b>{paragraph_markup(value)}</b>", small_style) for value in selected_columns]]
                for row in table["rows"]:
                    data.append([
                        paragraph(paragraph_markup(cls._display(value)), small_style)
                        for value in row[column_start:column_end]
                    ])
                table_width = letter[0] - document.leftMargin - document.rightMargin
                report_table = Table(data, colWidths=[table_width / len(selected_columns)] * len(selected_columns), repeatRows=1, splitByRow=1)
                report_table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef8")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#17365d")),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]))
                story.append(report_table)

        document.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
        content = output.getvalue()
        if len(content) > cls.MAX_PDF_BYTES:
            raise ValueError("PDF output exceeds the 8 MiB export limit")
        from pypdf import PdfReader
        if len(PdfReader(BytesIO(content)).pages) > cls.MAX_PDF_PAGES:
            raise ValueError(f"PDF report exceeds the supported page limit of {cls.MAX_PDF_PAGES}")
        return content

    @classmethod
    def image(cls, snapshot, exported_at: datetime, include_attribution: bool = False, target_format="png") -> bytes:
        """Render a one-page, white-background summary image from the result snapshot."""
        if not isinstance(target_format, str) or target_format.casefold() not in {"png", "jpeg", "jpg"}:
            raise ValueError("Result image format must be PNG or JPEG")
        image_format = "jpeg" if target_format.casefold() in {"jpeg", "jpg"} else "png"
        cls._validated_snapshot(snapshot, exported_at, include_attribution)
        # Keep the original input shape expected by ``pdf`` while omitting
        # tables from the shareable one-page summary image.
        summary = dict(snapshot)
        summary["tables"] = []

        pdf_content = cls.pdf(summary, exported_at, include_attribution)
        from pypdf import PdfReader
        if len(PdfReader(BytesIO(pdf_content)).pages) != 1:
            raise ValueError("Result summary is too long for a one-page image; export it as PDF or HTML")

        from officekit.engines.engine_pdf_images import PdfImageExportEngine
        archive_content, page_count = PdfImageExportEngine.render_pdf(
            pdf_content, image_format, dpi=150, quality=90,
        )
        if page_count != 1:
            raise ValueError("Result summary is too long for a one-page image; export it as PDF or HTML")
        with zipfile.ZipFile(BytesIO(archive_content)) as archive:
            expected_name = "page-001.jpg" if image_format == "jpeg" else "page-001.png"
            if archive.namelist() != [expected_name]:
                raise ValueError("Result summary image could not be generated")
            rendered = archive.read(expected_name)

        from PIL import Image, PngImagePlugin
        output = BytesIO()
        with Image.open(BytesIO(rendered)) as image:
            if image_format == "jpeg" and image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            if image_format == "png":
                options = {}
                if include_attribution:
                    png_info = PngImagePlugin.PngInfo()
                    png_info.add_text("Software", "OfficeKit")
                    png_info.add_text("Description", "Generated with OfficeKit · officekit.app")
                    png_info.add_text("Creation Time", exported_at.isoformat().replace("+00:00", "Z"))
                    options["pnginfo"] = png_info
                image.save(output, format="PNG", optimize=True, **options)
            else:
                options = {"quality": 90, "optimize": True}
                if include_attribution:
                    exif = Image.Exif()
                    exif[270] = "Generated with OfficeKit - officekit.app"
                    exif[305] = "OfficeKit"
                    options["exif"] = exif
                image.save(output, format="JPEG", **options)

        content = output.getvalue()
        if len(content) > cls.MAX_IMAGE_BYTES:
            raise ValueError("Result image exceeds the 8 MiB export limit")
        return content

    @classmethod
    def markdown(cls, snapshot, exported_at: datetime, include_attribution: bool = False) -> str:
        report = cls._validated_snapshot(snapshot, exported_at, include_attribution)
        lines = [
            f"# {cls._markdown_text(report['title'])}",
            "",
            f"**Tool:** `{report['tool_id']}`  ",
            f"**Operation time:** {report['created_at']}  ",
            f"**Exported:** {report['exported_at']}",
        ]
        cls._append_values(lines, "Inputs", report["inputs"])
        cls._append_values(lines, "Results", report["results"])
        if report["assumptions"]:
            lines.extend(("", "## Assumptions", ""))
            lines.extend(f"- {cls._markdown_text(item)}" for item in report["assumptions"])
        for table in report["tables"]:
            lines.extend(("", f"## {cls._markdown_text(table['title'])}", ""))
            lines.append("| " + " | ".join(cls._markdown_text(column) for column in table["columns"]) + " |")
            lines.append("| " + " | ".join("---" for _ in table["columns"]) + " |")
            for row in table["rows"]:
                lines.append("| " + " | ".join(cls._markdown_text(cls._display(value)) for value in row) + " |")
        if report["include_attribution"]:
            lines.extend(("", "---", "Generated with OfficeKit · officekit.app"))
        return cls._bounded_output("\n".join(lines) + "\n", "Markdown")

    @classmethod
    def html(cls, snapshot, exported_at: datetime, include_attribution: bool = False) -> str:
        report = cls._validated_snapshot(snapshot, exported_at, include_attribution)
        pieces = [
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
            f"<title>{cls._html_text(report['title'])}</title>",
            "<style>body{margin:0;background:#fff;color:#1f2937;font:16px/1.5 system-ui,sans-serif}main{max-width:900px;margin:40px auto;padding:0 24px}h1{font-size:2rem}h2{margin-top:2rem}table{border-collapse:collapse;width:100%;margin:12px 0 24px}caption{text-align:left;font-weight:700;margin:0 0 8px}th,td{border:1px solid #d1d5db;padding:8px;text-align:left;overflow-wrap:anywhere}th{background:#f3f4f6}footer{border-top:1px solid #d1d5db;margin-top:32px;padding-top:16px;color:#4b5563}.meta{color:#4b5563;font-size:.9rem}</style></head><body><main>",
            f"<header><h1>{cls._html_text(report['title'])}</h1><p class=\"meta\">Tool: {cls._html_text(report['tool_id'])}<br>Operation time: {cls._html_text(report['created_at'])}<br>Exported: {cls._html_text(report['exported_at'])}</p></header>",
        ]
        cls._append_html_values(pieces, "Inputs", report["inputs"])
        cls._append_html_values(pieces, "Results", report["results"])
        if report["assumptions"]:
            pieces.append("<section><h2>Assumptions</h2><ul>")
            pieces.extend(f"<li>{cls._html_text(item)}</li>" for item in report["assumptions"])
            pieces.append("</ul></section>")
        for table in report["tables"]:
            pieces.append("<section><table><caption>" + cls._html_text(table["title"]) + "</caption><thead><tr>")
            pieces.extend(f"<th scope=\"col\">{cls._html_text(column)}</th>" for column in table["columns"])
            pieces.append("</tr></thead><tbody>")
            for row in table["rows"]:
                pieces.append("<tr>" + "".join(
                    f"<td>{cls._html_text(cls._display(value))}</td>" for value in row
                ) + "</tr>")
            pieces.append("</tbody></table></section>")
        if report["include_attribution"]:
            pieces.append("<footer>Generated with OfficeKit · officekit.app</footer>")
        pieces.append("</main></body></html>\n")
        return cls._bounded_output("".join(pieces), "HTML")

    @classmethod
    def json(cls, snapshot, exported_at: datetime, include_attribution: bool = False) -> str:
        report = cls._validated_snapshot(snapshot, exported_at, include_attribution)
        payload = {
            "schema_version": "officekit.result.v1",
            "tool_id": report["tool_id"],
            "title": report["title"],
            "created_at": report["created_at"],
            "exported_at": report["exported_at"],
            "inputs": report["inputs"],
            "results": report["results"],
            "assumptions": report["assumptions"],
            "tables": report["tables"],
        }
        if report["include_attribution"]:
            payload["metadata"] = {"attribution": "Generated with OfficeKit · officekit.app"}
        output = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
        return cls._bounded_output(output, "JSON")

    @classmethod
    def csv(cls, snapshot, exported_at: datetime, include_attribution: bool = False) -> str:
        report = cls._validated_snapshot(snapshot, exported_at, include_attribution)
        output = io.StringIO(newline="")
        writer = csv_module.writer(output, lineterminator="\r\n")
        writer.writerow(("record_type", "section", "name", "value", "unit", "value_type", "row_index", "column_index"))
        for name, value in (
            ("tool_id", report["tool_id"]),
            ("title", report["title"]),
            ("operation_time", report["created_at"]),
            ("exported_at", report["exported_at"]),
        ):
            cls._write_csv_row(writer, "metadata", "report", name, value, None, "string")
        for section, values in (("inputs", report["inputs"]), ("results", report["results"])):
            record_type = "input" if section == "inputs" else "result"
            for item in values:
                cls._write_csv_row(
                    writer, record_type, section, item["name"], item["value"], item["unit"],
                    cls._value_type(item["value"]),
                )
        for assumption in report["assumptions"]:
            cls._write_csv_row(writer, "assumption", "assumptions", "assumption", assumption, None, "string")
        for table in report["tables"]:
            if not table["rows"]:
                for column_index, column in enumerate(table["columns"], start=1):
                    cls._write_csv_row(
                        writer, "table_column", table["title"], column, "", "", "header", 0, column_index,
                    )
            for row_index, row in enumerate(table["rows"], start=1):
                for column_index, (column, value) in enumerate(zip(table["columns"], row), start=1):
                    cls._write_csv_row(
                        writer, "table_cell", table["title"], column, value, None,
                        cls._value_type(value), row_index, column_index,
                    )
        if report["include_attribution"]:
            cls._write_csv_row(
                writer, "metadata", "report", "attribution",
                "Generated with OfficeKit · officekit.app", None, "string",
            )
        return cls._bounded_output(output.getvalue(), "CSV")

    @classmethod
    def xlsx(cls, snapshot, exported_at: datetime, include_attribution: bool = False) -> bytes:
        report = cls._validated_snapshot(snapshot, exported_at, include_attribution)
        cell_count = 7 + (2 if report["include_attribution"] else 0)
        cell_count += (4 + 4 * len(report["inputs"])) if report["inputs"] else 0
        cell_count += (4 + 4 * len(report["results"])) if report["results"] else 0
        cell_count += (2 + 2 * len(report["assumptions"])) if report["assumptions"] else 0
        cell_count += sum(
            len(table["columns"]) + 1 + len(table["rows"]) * (len(table["columns"]) + 1)
            for table in report["tables"]
        )
        if cell_count > cls.MAX_XLSX_CELLS:
            raise ValueError(f"XLSX result exceeds the {cls.MAX_XLSX_CELLS:,}-cell export limit")

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Result"
        workbook.properties.creator = "OfficeKit"
        workbook.properties.title = cls._xlsx_safe_text(report["title"])
        workbook.properties.subject = f"{report['tool_id']} result"

        def append(values, *, header=False):
            safe_values = tuple(
                cls._xlsx_safe_text(value) if isinstance(value, str) else value
                for value in values
            )
            sheet.append(safe_values)
            row_index = sheet.max_row
            for cell in sheet[row_index]:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                if header:
                    cell.style = "Headline 2"

        append(("OfficeKit result",), header=True)
        append(("Tool", report["tool_id"]))
        append(("Operation time", report["created_at"]))
        append(("Exported", report["exported_at"]))
        if report["include_attribution"]:
            append(("Attribution", "Generated with OfficeKit · officekit.app"))
        for section, items in (("Input", report["inputs"]), ("Result", report["results"])):
            if items:
                append((section, "Name", "Value", "Unit"), header=True)
                for item in items:
                    append((section, item["name"], item["value"], item["unit"]))
        if report["assumptions"]:
            append(("Assumption", "Text"), header=True)
            for assumption in report["assumptions"]:
                append(("Assumption", assumption))
        for table in report["tables"]:
            append((table["title"], *table["columns"]), header=True)
            for row in table["rows"]:
                append(("", *row))

        sheet.freeze_panes = "A2"
        sheet.column_dimensions["A"].width = 24
        sheet.column_dimensions["B"].width = 34
        sheet.column_dimensions["C"].width = 24
        sheet.column_dimensions["D"].width = 20
        for column in range(5, sheet.max_column + 1):
            sheet.column_dimensions[sheet.cell(1, column).column_letter].width = 20
        output = BytesIO()
        workbook.save(output)
        content = output.getvalue()
        if len(content) > cls.MAX_XLSX_BYTES:
            raise ValueError("XLSX output exceeds the 8 MiB export limit")
        return content

    @classmethod
    def pptx(cls, snapshot, exported_at: datetime, include_attribution: bool = False) -> bytes:
        from pptx import Presentation
        from pptx.enum.text import MSO_AUTO_SIZE
        from pptx.util import Inches, Pt

        report = cls._validated_snapshot(snapshot, exported_at, include_attribution)
        summary_pages = sum(
            (len(items) + 11) // 12
            for items in (report["inputs"], report["results"], report["assumptions"])
        )
        table_pages = sum(
            ((len(table["columns"]) + 5) // 6) * max(1, (len(table["rows"]) + 19) // 20)
            for table in report["tables"]
        )
        estimated_pages = 1 + summary_pages + table_pages
        if estimated_pages > cls.MAX_PPTX_SLIDES:
            raise ValueError(
                f"PowerPoint report exceeds the supported slide limit of {cls.MAX_PPTX_SLIDES}"
            )

        presentation = Presentation()
        presentation.slide_width = Inches(13.333)
        presentation.slide_height = Inches(7.5)
        presentation.core_properties.title = cls._xlsx_safe_text(report["title"])
        presentation.core_properties.subject = cls._xlsx_safe_text(f"{report['tool_id']} result")
        presentation.core_properties.author = "OfficeKit" if report["include_attribution"] else ""
        blank_layout = presentation.slide_layouts[6]

        def add_text(slide, text, *, left, top, width, height, font_size=16, bold=False):
            shape = slide.shapes.add_textbox(left, top, width, height)
            frame = shape.text_frame
            frame.word_wrap = True
            frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
            paragraph = frame.paragraphs[0]
            paragraph.text = cls._xlsx_safe_text(str(text))
            paragraph.font.size = Pt(font_size)
            paragraph.font.bold = bold
            return shape

        def add_footer(slide, page_number):
            footer = f"Page {page_number} of {estimated_pages}"
            if report["include_attribution"]:
                footer += "  ·  Generated with OfficeKit · officekit.app"
            add_text(
                slide, footer,
                left=Inches(0.65), top=Inches(7.12), width=Inches(12.0), height=Inches(0.22),
                font_size=8,
            )

        first_slide = presentation.slides.add_slide(blank_layout)
        add_text(
            first_slide, report["title"],
            left=Inches(0.8), top=Inches(1.45), width=Inches(11.8), height=Inches(1.4),
            font_size=30, bold=True,
        )
        metadata = (
            f"Tool: {report['tool_id']}\n"
            f"Operation time: {report['created_at']}\n"
            f"Exported: {report['exported_at']}"
        )
        add_text(
            first_slide, metadata,
            left=Inches(0.85), top=Inches(3.05), width=Inches(11.5), height=Inches(1.5),
            font_size=15,
        )
        page_number = 1
        add_footer(first_slide, page_number)

        def add_summary_pages(title, entries):
            nonlocal page_number
            for offset in range(0, len(entries), 12):
                slide = presentation.slides.add_slide(blank_layout)
                page_number += 1
                add_text(
                    slide, title,
                    left=Inches(0.65), top=Inches(0.4), width=Inches(12), height=Inches(0.55),
                    font_size=24, bold=True,
                )
                batch = entries[offset:offset + 12]
                lines = [f"• {entry}" for entry in batch]
                add_text(
                    slide, "\n".join(lines),
                    left=Inches(0.8), top=Inches(1.2), width=Inches(11.8), height=Inches(5.65),
                    font_size=15,
                )
                add_footer(slide, page_number)

        add_summary_pages("Inputs", [
            f"{item['name']}: {cls._display(item['value'])}"
            + (f" {item['unit']}" if item["unit"] is not None else "")
            for item in report["inputs"]
        ])
        add_summary_pages("Results", [
            f"{item['name']}: {cls._display(item['value'])}"
            + (f" {item['unit']}" if item["unit"] is not None else "")
            for item in report["results"]
        ])
        add_summary_pages("Assumptions", report["assumptions"])

        for table in report["tables"]:
            row_ranges = [
                (start, min(start + 20, len(table["rows"])))
                for start in range(0, len(table["rows"]), 20)
            ] or [(0, 0)]
            for column_start in range(0, len(table["columns"]), 6):
                column_end = min(column_start + 6, len(table["columns"]))
                for row_start, row_end in row_ranges:
                    slide = presentation.slides.add_slide(blank_layout)
                    page_number += 1
                    title = (
                        f"{table['title']} — Columns {column_start + 1}–{column_end}, "
                        f"Rows {row_start + 1 if row_end else 0}–{row_end}"
                    )
                    add_text(
                        slide, title,
                        left=Inches(0.55), top=Inches(0.35), width=Inches(12.2), height=Inches(0.6),
                        font_size=18, bold=True,
                    )
                    selected_columns = table["columns"][column_start:column_end]
                    selected_rows = [
                        row[column_start:column_end]
                        for row in table["rows"][row_start:row_end]
                    ]
                    table_shape = slide.shapes.add_table(
                        len(selected_rows) + 1, len(selected_columns),
                        Inches(0.55), Inches(1.1), Inches(12.2), Inches(5.75),
                    )
                    ppt_table = table_shape.table
                    column_width = Inches(12.2 / len(selected_columns))
                    for column_index, column in enumerate(selected_columns):
                        ppt_table.columns[column_index].width = column_width
                        ppt_table.cell(0, column_index).text = cls._xlsx_safe_text(column)
                    for local_row, row in enumerate(selected_rows, start=1):
                        for column_index, value in enumerate(row):
                            ppt_table.cell(local_row, column_index).text = cls._xlsx_safe_text(cls._display(value))
                    for row in ppt_table.rows:
                        row.height = Inches(5.75 / (len(selected_rows) + 1))
                        for cell in row.cells:
                            cell.text_frame.word_wrap = True
                            cell.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
                            for paragraph in cell.text_frame.paragraphs:
                                paragraph.font.size = Pt(10)
                    add_footer(slide, page_number)

        output = BytesIO()
        presentation.save(output)
        content = output.getvalue()
        if len(content) > cls.MAX_PPTX_BYTES:
            raise ValueError("PowerPoint output exceeds the 8 MiB export limit")
        return content

    @staticmethod
    def _xlsx_safe_text(value):
        safe_characters = []
        for character in value:
            point = ord(character)
            xml_valid = point in (0x09, 0x0A, 0x0D) or 0x20 <= point <= 0xD7FF or \
                0xE000 <= point <= 0xFFFD or 0x10000 <= point <= 0x10FFFF
            if not xml_valid or unicodedata.category(character) == "Cc":
                safe_characters.append(f"[control U+{point:04X}]")
            else:
                safe_characters.append(character)
        return "".join(safe_characters)

    @classmethod
    def export(cls, snapshot, export_format, exported_at: datetime, include_attribution: bool = False):
        if export_format == "markdown":
            return cls.markdown(snapshot, exported_at, include_attribution)
        if export_format == "html":
            return cls.html(snapshot, exported_at, include_attribution)
        if export_format == "json":
            return cls.json(snapshot, exported_at, include_attribution)
        if export_format == "csv":
            return cls.csv(snapshot, exported_at, include_attribution)
        if export_format == "xlsx":
            return cls.xlsx(snapshot, exported_at, include_attribution)
        if export_format == "pptx":
            return cls.pptx(snapshot, exported_at, include_attribution)
        if export_format == "pdf":
            return cls.pdf(snapshot, exported_at, include_attribution)
        if export_format in {"png", "jpeg", "jpg"}:
            return cls.image(snapshot, exported_at, include_attribution, export_format)
        raise ValueError("Unsupported result export format")

    @staticmethod
    def _value_type(value):
        if value is None:
            return "null"
        if type(value) is bool:
            return "boolean"
        if type(value) is int:
            return "integer"
        if type(value) is float:
            return "number"
        return "string"

    @classmethod
    def _write_csv_row(cls, writer, record_type, section, name, value, unit, value_type, row_index="", column_index=""):
        cells = (record_type, section, name, value, unit or "", value_type, row_index, column_index)
        writer.writerow(cls._spreadsheet_safe_cell(cell) for cell in cells)

    @staticmethod
    def _spreadsheet_safe_cell(value):
        if value is None:
            return ""
        if type(value) is bool:
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        rendered = "".join(
            f"[control U+{ord(character):04X}]"
            if unicodedata.category(character) == "Cc" and character not in "\r\n"
            else character
            for character in rendered
        )
        if isinstance(value, str):
            normalized_prefix = unicodedata.normalize("NFKC", rendered.lstrip())[:1]
            if normalized_prefix in ("=", "+", "-", "@"):
                return "'" + rendered
        return rendered

    @classmethod
    def _validated_snapshot(cls, snapshot, exported_at, include_attribution):
        if not isinstance(snapshot, dict) or set(snapshot) != cls.SNAPSHOT_KEYS:
            raise ValueError("Result snapshot must contain exactly the supported fields")
        if not isinstance(exported_at, datetime) or exported_at.tzinfo is None or exported_at.utcoffset() is None:
            raise ValueError("Export time must be timezone-aware")
        if type(include_attribution) is not bool:
            raise ValueError("Attribution option must be a boolean")

        budget = [0]
        tool_id = cls._text(snapshot["tool_id"], "Tool ID", budget, 80)
        if not cls.TOOL_ID.fullmatch(tool_id):
            raise ValueError("Tool ID has an invalid format")
        title = cls._text(snapshot["title"], "Title", budget, 160)
        operation_time = cls._timestamp(snapshot["created_at"], "Operation time", budget)
        inputs = cls._named_values(snapshot["inputs"], "Inputs", budget)
        results = cls._named_values(snapshot["results"], "Results", budget)
        assumptions = cls._text_list(snapshot["assumptions"], "Assumptions", budget, 100)
        tables = cls._tables(snapshot["tables"], budget)
        if not inputs and not results and not assumptions and not tables:
            raise ValueError("Result snapshot must include at least one input, result, assumption or table")
        return {
            "tool_id": tool_id,
            "title": title,
            "created_at": operation_time,
            "exported_at": exported_at.isoformat(),
            "inputs": inputs,
            "results": results,
            "assumptions": assumptions,
            "tables": tables,
            "include_attribution": include_attribution,
        }

    @classmethod
    def _bounded_output(cls, output, format_name):
        try:
            encoded_output = output.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError(f"{format_name} output contains invalid Unicode") from error
        if len(encoded_output) > cls.MAX_TEXT_BYTES * 4:
            raise ValueError(f"{format_name} output exceeds the 4 MiB export limit")
        return output

    @classmethod
    def _text(cls, value, label, budget, max_chars, allow_empty=False):
        if not isinstance(value, str) or (not value and not allow_empty) or len(value) > max_chars:
            requirement = "a string" if allow_empty else "a non-empty string"
            raise ValueError(f"{label} must be {requirement} of at most {max_chars:,} characters")
        try:
            byte_count = len(value.encode("utf-8"))
        except UnicodeEncodeError as error:
            raise ValueError(f"{label} must contain valid UTF-8 text") from error
        budget[0] += byte_count
        if budget[0] > cls.MAX_TEXT_BYTES:
            raise ValueError("Result snapshot text exceeds the 1,048,576 UTF-8 byte limit")
        return value

    @classmethod
    def _timestamp(cls, value, label, budget):
        value = cls._text(value, label, budget, 40)
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{label} must be an ISO 8601 timestamp") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{label} must be timezone-aware")
        return value

    @classmethod
    def _scalar(cls, value, label, budget):
        if value is None or type(value) is bool:
            return value
        if type(value) is int:
            if abs(value) > 1e100:
                raise ValueError(f"{label} exceeds the supported numeric range")
            return value
        if type(value) is float:
            if not math.isfinite(value) or abs(value) > 1e100:
                raise ValueError(f"{label} must be finite and within the supported numeric range")
            return value
        if isinstance(value, str):
            return cls._text(value, label, budget, 10_000, allow_empty=True)
        raise ValueError(f"{label} must be a string, number, boolean or null")

    @classmethod
    def _named_values(cls, values, label, budget):
        if not isinstance(values, list) or len(values) > 1_000:
            raise ValueError(f"{label} must be a list of at most 1,000 entries")
        cleaned = []
        for index, item in enumerate(values):
            if not isinstance(item, dict) or set(item) != {"name", "value", "unit"}:
                raise ValueError(f"{label} entry {index + 1} has an invalid shape")
            name = cls._text(item["name"], f"{label} name", budget, 160)
            value = cls._scalar(item["value"], f"{label} value", budget)
            unit = item["unit"]
            if unit is not None:
                unit = cls._text(unit, f"{label} unit", budget, 80)
            cleaned.append({"name": name, "value": value, "unit": unit})
        return cleaned

    @classmethod
    def _text_list(cls, values, label, budget, max_items):
        if not isinstance(values, list) or len(values) > max_items:
            raise ValueError(f"{label} must be a list of at most {max_items} entries")
        return [cls._text(value, f"{label} entry", budget, 10_000) for value in values]

    @classmethod
    def _tables(cls, tables, budget):
        if not isinstance(tables, list) or len(tables) > 20:
            raise ValueError("Tables must be a list of at most 20 entries")
        total_rows = 0
        cleaned_tables = []
        for table in tables:
            if not isinstance(table, dict) or set(table) != {"title", "columns", "rows"}:
                raise ValueError("Table has an invalid shape")
            title = cls._text(table["title"], "Table title", budget, 160)
            columns = table["columns"]
            rows = table["rows"]
            if not isinstance(columns, list) or not 1 <= len(columns) <= cls.MAX_COLUMNS:
                raise ValueError("Table must contain between 1 and 40 columns")
            cleaned_columns = [cls._text(column, "Table column", budget, 160) for column in columns]
            if not isinstance(rows, list):
                raise ValueError("Table rows must be a list")
            total_rows += len(rows)
            if total_rows > cls.MAX_ROWS:
                raise ValueError("Tables may contain at most 10,000 rows total")
            cleaned_rows = []
            for row in rows:
                if not isinstance(row, list) or len(row) != len(cleaned_columns):
                    raise ValueError("Table row column count does not match its header")
                cleaned_rows.append([
                    cls._scalar(value, "Table cell", budget) for value in row
                ])
            cleaned_tables.append({"title": title, "columns": cleaned_columns, "rows": cleaned_rows})
        return cleaned_tables

    @classmethod
    def _append_values(cls, lines, title, values):
        if not values:
            return
        lines.extend(("", f"## {title}", "", "| Name | Value | Unit |", "| --- | --- | --- |"))
        for item in values:
            unit = "" if item["unit"] is None else cls._markdown_text(item["unit"])
            lines.append(
                f"| {cls._markdown_text(item['name'])} | "
                f"{cls._markdown_text(cls._display(item['value']))} | {unit} |"
            )

    @classmethod
    def _append_html_values(cls, pieces, title, values):
        if not values:
            return
        pieces.append(f"<section><h2>{title}</h2><table><thead><tr><th scope=\"col\">Name</th><th scope=\"col\">Value</th><th scope=\"col\">Unit</th></tr></thead><tbody>")
        for item in values:
            unit = "" if item["unit"] is None else cls._html_text(item["unit"])
            pieces.append(
                "<tr><th scope=\"row\">" + cls._html_text(item["name"]) + "</th>"
                "<td>" + cls._html_text(cls._display(item["value"])) + "</td>"
                "<td>" + unit + "</td></tr>"
            )
        pieces.append("</tbody></table></section>")

    @staticmethod
    def _display(value):
        if value is None:
            return "null"
        if type(value) is bool:
            return "true" if value else "false"
        return str(value)

    @staticmethod
    def _markdown_text(value):
        text = "".join(
            f"[control U+{ord(character):04X}]"
            if unicodedata.category(character) == "Cc" and character not in "\t\n\r"
            else character
            for character in str(value)
        )
        text = text.replace("&", "&amp;").replace("<", "&#60;").replace(">", "&#62;")
        text = text.replace("|", "&#124;").replace("`", "&#96;")
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
        return re.sub(r"([\\*_\[\]~])", r"\\\1", text)

    @staticmethod
    def _html_text(value):
        text = "".join(
            f"[control U+{ord(character):04X}]"
            if unicodedata.category(character) == "Cc" and character not in "\t\n\r"
            else character
            for character in str(value)
        )
        return html.escape(text, quote=True).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
