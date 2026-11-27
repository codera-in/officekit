"""
OfficeKit - Advanced Batch PDF Engine (Pillar 1)
High-performance deterministic document operations:
- Batch Multi-PDF Merge
- Multi-range Split / Page Extractor
- Presets PDF Compression (Lossless stream decimation)
- Privacy Metadata Purge
"""

import io
import re
import unicodedata
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Optional, Tuple
import pikepdf
from officekit.engines.engine_pdf_security import BoundedPdfBuffer, PdfOutputLimitError
from officekit.engines.engine_pdf_compression_policy import compression_options, compression_ratio
from officekit.engines.engine_pdf_ranges import parse_page_ranges as _parse_page_ranges


class AdvancedPdfEngine:
    MAX_OUTPUT_BYTES = 64 * 1024 * 1024
    MAX_SPLIT_GROUPS = 50
    MAX_SPLIT_GROUP_NAME_LENGTH = 120
    MAX_SPLIT_SELECTED_PAGES = 2_000
    MAX_PAGE_MANAGEMENT_PAGES = 2_000

    class _BoundedZipBuffer(io.BytesIO):
        def __init__(self, max_bytes: int):
            super().__init__()
            self.max_bytes = max_bytes
            self.max_length = 0

        def write(self, data):
            end = self.tell() + len(data)
            if max(self.max_length, end) > self.max_bytes:
                raise PdfOutputLimitError()
            written = super().write(data)
            self.max_length = max(self.max_length, end)
            return written

    @staticmethod
    def _copy_outline_item(item, source_pdf, page_offset):
        options = {"color": item.color, "flags": item.flags}
        resolved = item.resolved_destination(source_pdf)
        if resolved is not None and resolved.page is not None:
            try:
                source_page_index = source_pdf.pages.index(resolved.page)
            except ValueError as error:
                raise ValueError("PDF outline destination is outside its source page tree.") from error
            options["destination"] = page_offset + source_page_index
            options["page_location"] = resolved.fit_type
            for key in ("left", "top", "right", "bottom", "zoom"):
                value = getattr(resolved, key)
                if value is not None:
                    options[key] = value
        copied = pikepdf.OutlineItem(item.title, **options)
        copied.is_closed = item.is_closed
        copied.children.extend(
            AdvancedPdfEngine._copy_outline_item(child, source_pdf, page_offset)
            for child in item.children
        )
        return copied

    @staticmethod
    def _source_outline_items(source_pdf, page_offset):
        with source_pdf.open_outline(max_depth=64, strict=True) as outline:
            return [
                AdvancedPdfEngine._copy_outline_item(item, source_pdf, page_offset)
                for item in outline.root
            ]

    @staticmethod
    def merge_multiple(
        pdf_bytes_list: List[bytes], source_labels: Optional[List[str]] = None
    ) -> bytes:
        """Merge PDFs in order and add an outline entry for each source file."""
        merged = pikepdf.new()
        source_bookmarks = []
        for index, b in enumerate(pdf_bytes_list):
            if not b:
                continue
            with pikepdf.open(io.BytesIO(b)) as src:
                first_page = len(merged.pages)
                outline_items = AdvancedPdfEngine._source_outline_items(src, first_page)
                merged.add_pages_from(src)
                label = source_labels[index] if source_labels and index < len(source_labels) else ""
                label = str(label).replace("\\", "/").rsplit("/", 1)[-1].strip()
                label = "".join(character for character in label if character.isprintable())[:160]
                if not label:
                    label = f"Document {index + 1}"
                source_bookmarks.append((label, first_page, outline_items))

        if source_bookmarks:
            with merged.open_outline() as outline:
                for label, page_index, source_items in source_bookmarks:
                    section = pikepdf.OutlineItem(label, page_index)
                    section.children.extend(source_items)
                    outline.root.append(section)

        out_buf = BoundedPdfBuffer(AdvancedPdfEngine.MAX_OUTPUT_BYTES)
        merged.save(out_buf)
        return out_buf.getvalue()

    @staticmethod
    def parse_page_ranges(
        range_str: str, max_pages: int, max_selected_pages: int | None = None
    ) -> List[int]:
        """Parse ordered 1-based page selections into zero-based indices."""
        return _parse_page_ranges(range_str, max_pages, max_selected_pages)

    @classmethod
    def split_by_ranges(cls, pdf_bytes: bytes, page_ranges: str) -> bytes:
        """Extracts specified page ranges into a new PDF."""
        with pikepdf.open(io.BytesIO(pdf_bytes)) as src:
            target_indices = cls.parse_page_ranges(
                page_ranges, len(src.pages), cls.MAX_SPLIT_SELECTED_PAGES
            )
            dest = pikepdf.new()
            for idx in target_indices:
                dest.pages.append(src.pages[idx])

            out_buf = BoundedPdfBuffer(cls.MAX_OUTPUT_BYTES)
            dest.save(out_buf)
            return out_buf.getvalue()

    @classmethod
    def delete_pages(cls, pdf_bytes: bytes, page_ranges: str) -> bytes:
        """Remove selected pages from the page tree, retaining at least one page."""
        if not isinstance(pdf_bytes, bytes) or not pdf_bytes:
            raise ValueError("PDF input must be non-empty bytes")

        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            page_count = len(pdf.pages)
            if page_count > cls.MAX_PAGE_MANAGEMENT_PAGES:
                raise ValueError("The PDF exceeds the supported page limit.")
            removed = cls.parse_page_ranges(
                page_ranges, page_count, cls.MAX_PAGE_MANAGEMENT_PAGES
            )
            if len(removed) >= page_count:
                raise ValueError("At least one page must remain in the PDF.")
            cls._remove_deleted_page_widgets(pdf, removed)
            for page_index in reversed(removed):
                del pdf.pages[page_index]

            out_buf = BoundedPdfBuffer(cls.MAX_OUTPUT_BYTES)
            pdf.save(out_buf)
            return out_buf.getvalue()

    @staticmethod
    def _remove_deleted_page_widgets(pdf, removed_page_indexes: list[int]) -> None:
        """Remove AcroForm widget references attached to pages removed from the page tree."""
        acroform = pdf.Root.get("/AcroForm")
        if acroform is None:
            return

        removed_widget_ids = set()
        for page_index in removed_page_indexes:
            annotations = pdf.pages[page_index].obj.get("/Annots", [])
            for annotation in annotations:
                if annotation.get("/Subtype") == pikepdf.Name("/Widget"):
                    removed_widget_ids.add(annotation.objgen)
        if not removed_widget_ids:
            return

        def keep_field(field):
            if field.objgen in removed_widget_ids:
                return False
            children = field.get("/Kids")
            if children is None:
                return True
            retained = [child for child in children if keep_field(child)]
            if len(retained) != len(children):
                field["/Kids"] = pikepdf.Array(retained)
            return bool(retained) or len(children) == 0

        fields = acroform.get("/Fields")
        if fields is not None:
            retained_fields = [field for field in fields if keep_field(field)]
            if len(retained_fields) != len(fields):
                acroform["/Fields"] = pikepdf.Array(retained_fields)

    @classmethod
    def reorder_pages(cls, pdf_bytes: bytes, page_order: str) -> bytes:
        """Reorder every page in place without replacing page object identities."""
        if not isinstance(pdf_bytes, bytes) or not pdf_bytes:
            raise ValueError("PDF input must be non-empty bytes")

        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            page_count = len(pdf.pages)
            if page_count > cls.MAX_PAGE_MANAGEMENT_PAGES:
                raise ValueError("The PDF exceeds the supported page limit.")
            order = cls.parse_page_ranges(
                page_order, page_count, cls.MAX_PAGE_MANAGEMENT_PAGES
            )
            if len(order) != page_count:
                raise ValueError("Page order must include every page exactly once.")

            original_pages = list(pdf.pages)
            for target_index, original_index in enumerate(order):
                target_page = original_pages[original_index]
                current_index = next(
                    index
                    for index, page in enumerate(pdf.pages)
                    if page.objgen == target_page.objgen
                )
                if current_index != target_index:
                    moved_page = pdf.pages[current_index]
                    del pdf.pages[current_index]
                    pdf.pages.insert(target_index, moved_page)

            out_buf = BoundedPdfBuffer(cls.MAX_OUTPUT_BYTES)
            pdf.save(out_buf)
            return out_buf.getvalue()

    @classmethod
    def split_by_groups(cls, pdf_bytes: bytes, groups: list[dict]) -> bytes:
        """Create named page-group PDFs in one bounded, stored ZIP archive."""
        if not isinstance(pdf_bytes, bytes) or not pdf_bytes:
            raise ValueError("PDF input must be non-empty bytes")
        if not isinstance(groups, list) or not 2 <= len(groups) <= cls.MAX_SPLIT_GROUPS:
            raise ValueError(f"Select between 2 and {cls.MAX_SPLIT_GROUPS} page groups.")

        with pikepdf.open(io.BytesIO(pdf_bytes)) as source:
            names: set[str] = set()
            used_pages: set[int] = set()
            validated = []
            for group in groups:
                if not isinstance(group, dict) or set(group) != {"name", "page_ranges"}:
                    raise ValueError("Each page group needs only a PDF filename and page ranges.")
                name = group["name"]
                page_ranges = group["page_ranges"]
                if (
                    not isinstance(name, str)
                    or not name
                    or len(name) > cls.MAX_SPLIT_GROUP_NAME_LENGTH
                    or name in {".", ".."}
                    or name.rstrip(" .") != name
                    or not name.lower().endswith(".pdf")
                    or any(
                        unicodedata.category(character) in {"Cc", "Cf", "Cs"}
                        or character in '<>:"/\\|?*'
                        for character in name
                    )
                    or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?\.pdf", name)
                ):
                    raise ValueError("Page group names must be safe PDF filenames without folders.")
                name = unicodedata.normalize("NFC", name)
                normalized_name = name.casefold()
                if normalized_name in names:
                    raise ValueError("Page group filenames must be unique, ignoring letter case.")
                names.add(normalized_name)
                if not isinstance(page_ranges, str) or len(page_ranges) > 4096:
                    raise ValueError("Page group ranges must be text within the supported limit.")
                try:
                    selected_pages = cls.parse_page_ranges(
                        page_ranges, len(source.pages), cls.MAX_SPLIT_SELECTED_PAGES
                    )
                except ValueError as error:
                    raise ValueError(f"Invalid page group selection: {error}") from error
                if used_pages.intersection(selected_pages):
                    raise ValueError("A source page cannot appear in more than one output group.")
                if len(used_pages) + len(selected_pages) > cls.MAX_SPLIT_SELECTED_PAGES:
                    raise ValueError("The combined page groups exceed the supported page limit.")
                used_pages.update(selected_pages)
                validated.append((name, selected_pages))

            output = cls._BoundedZipBuffer(cls.MAX_OUTPUT_BYTES)
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                for name, selected_pages in validated:
                    target = pikepdf.new()
                    for page_index in selected_pages:
                        target.pages.append(source.pages[page_index])
                    pdf_output = BoundedPdfBuffer(cls.MAX_OUTPUT_BYTES)
                    target.save(pdf_output)
                    archive.writestr(name, pdf_output.getvalue())
            return output.getvalue()

    @staticmethod
    def compress_pdf(pdf_bytes: bytes, preset: str = "ebook") -> Tuple[bytes, float]:
        """
        Recompresses PDF streams losslessly at the selected deflate level.

        Canonical presets are fast, balanced, and maximum. Legacy screen,
        ebook, and printer names are aliases; none downsamples images or
        changes their visual quality. Returns (bytes, output/input size ratio),
        which can exceed 1.0 when rewriting expands a small PDF.
        """
        if not isinstance(pdf_bytes, bytes) or not pdf_bytes:
            raise ValueError("PDF input must be non-empty bytes")

        options = compression_options(preset)
        original_size = len(pdf_bytes)
        with TemporaryDirectory(prefix="officekit-pdf-compress-") as temp_dir:
            input_path = Path(temp_dir) / "input.pdf"
            output_path = Path(temp_dir) / "output.pdf"
            input_path.write_bytes(pdf_bytes)

            job = (
                pikepdf.JobBuilder()
                .input(str(input_path))
                .output(str(output_path))
                .compress(**options)
                .run()
            )
            if job.exit_code != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
                raise RuntimeError("PDF compression failed")
            if output_path.stat().st_size > AdvancedPdfEngine.MAX_OUTPUT_BYTES:
                raise PdfOutputLimitError()
            compressed_bytes = output_path.read_bytes()

        ratio = compression_ratio(len(compressed_bytes), original_size)
        return compressed_bytes, ratio

    @staticmethod
    def strip_metadata(pdf_bytes: bytes) -> bytes:
        """Removes all author, creator, title, and tracking metadata."""
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            # Purge document info dict
            for key in list(pdf.docinfo.keys()):
                del pdf.docinfo[key]

            # Purge XMP metadata stream
            if '/Metadata' in pdf.Root:
                del pdf.Root['/Metadata']

            out_buf = BoundedPdfBuffer(AdvancedPdfEngine.MAX_OUTPUT_BYTES)
            pdf.save(out_buf)
            return out_buf.getvalue()
