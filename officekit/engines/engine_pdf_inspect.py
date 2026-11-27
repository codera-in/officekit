"""Read-only PDF inspection report (P10): document info, XMP, page geometry and form/annotation summary."""

import datetime
import re

import pikepdf

from officekit.engines.engine_pdf_tool_common import inherited_value, open_source_pdf, page_rotation

_DATE_PATTERN = re.compile(
    r"D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?"
    r"(?:([Zz])|([+-])(\d{2})'?(\d{2})'?)?$"
)
# PDFDocEncoding differs from Latin-1 for 0x18-0x1F and 0x80-0xA0 (PDF 32000-1 Annex D).
_PDF_DOC_ENCODING = {
    0x18: "˘", 0x19: "ˇ", 0x1A: "ˆ", 0x1B: "˙",
    0x1C: "˝", 0x1D: "˛", 0x1E: "˚", 0x1F: "˜",
    0x80: "•", 0x81: "†", 0x82: "‡", 0x83: "…",
    0x84: "—", 0x85: "–", 0x86: "ƒ", 0x87: "⁄",
    0x88: "‹", 0x89: "›", 0x8A: "−", 0x8B: "‰",
    0x8C: "„", 0x8D: "“", 0x8E: "”", 0x8F: "‘",
    0x90: "’", 0x91: "‚", 0x92: "™", 0x93: "ﬁ",
    0x94: "ﬂ", 0x95: "Ł", 0x96: "Œ", 0x97: "Š",
    0x98: "Ÿ", 0x99: "Ž", 0x9A: "ı", 0x9B: "ł",
    0x9C: "œ", 0x9D: "š", 0x9E: "ž", 0xA0: "€",
}

_XMP_PREFIXES = {
    "http://purl.org/dc/elements/1.1/": "dc",
    "http://ns.adobe.com/xap/1.0/": "xmp",
    "http://ns.adobe.com/xap/1.0/mm/": "xmpMM",
    "http://ns.adobe.com/xap/1.0/rights/": "xmpRights",
    "http://ns.adobe.com/pdf/1.3/": "pdf",
    "http://www.aiim.org/pdfa/ns/id/": "pdfaid",
    "http://ns.adobe.com/photoshop/1.0/": "photoshop",
}


class PdfInspectEngine:
    MAX_VALUE_CHARS = 2_000
    MAX_CUSTOM_FIELDS = 64
    MAX_XMP_ENTRIES = 128
    MAX_PAGE_SIZE_GROUPS = 50
    MAX_FIELD_NODES = 10_000
    STANDARD_KEYS = (
        "Title", "Author", "Subject", "Keywords", "Creator",
        "Producer", "CreationDate", "ModDate", "Trapped",
    )

    @classmethod
    def inspect(cls, content: bytes) -> dict:
        with open_source_pdf(content) as pdf:
            truncated = False
            docinfo_entries, docinfo_truncated = cls._docinfo(pdf)
            truncated = truncated or docinfo_truncated
            dates = cls._dates(pdf)
            xmp, xmp_truncated = cls._xmp(pdf)
            truncated = truncated or xmp_truncated
            page_sizes, other_count = cls._page_sizes(pdf)
            forms, forms_truncated = cls._forms(pdf)
            truncated = truncated or forms_truncated
            annotations = cls._annotations(pdf)
            return {
                "pdf_version": str(pdf.pdf_version),
                "page_count": len(pdf.pages),
                "docinfo": docinfo_entries,
                "dates": dates,
                "xmp": xmp,
                "page_sizes": page_sizes,
                "other_count": other_count,
                "forms": forms,
                "annotations": annotations,
                "encrypted": bool(pdf.is_encrypted),
                "truncated": truncated,
            }

    @classmethod
    def _decode(cls, value) -> str:
        if not isinstance(value, pikepdf.String):
            return str(value)
        raw = bytes(value)
        if raw.startswith(b"\xfe\xff"):
            return raw[2:].decode("utf-16-be", errors="replace")
        if raw.startswith(b"\xef\xbb\xbf"):
            return raw[3:].decode("utf-8", errors="replace")
        return "".join(_PDF_DOC_ENCODING.get(byte, chr(byte)) for byte in raw)

    @classmethod
    def _bounded(cls, text: str) -> tuple[str, bool]:
        if len(text) > cls.MAX_VALUE_CHARS:
            return text[: cls.MAX_VALUE_CHARS], True
        return text, False

    @classmethod
    def _docinfo(cls, pdf):
        info = pdf.docinfo
        entries = []
        truncated = False
        for key in cls.STANDARD_KEYS:
            name = f"/{key}"
            present = name in info
            value, cut = (None, False)
            if present:
                value, cut = cls._bounded(cls._decode(info[name]))
            truncated = truncated or cut
            entries.append({"key": key, "label": key, "standard": True, "present": present,
                            "value": value, "truncated": cut})
        custom = [name for name in info.keys() if str(name)[1:] not in cls.STANDARD_KEYS]
        for name in custom[: cls.MAX_CUSTOM_FIELDS]:
            value, cut = cls._bounded(cls._decode(info[name]))
            truncated = truncated or cut
            entries.append({"key": str(name)[1:], "label": str(name)[1:], "standard": False,
                            "present": True, "value": value, "truncated": cut})
        # Keys past the cap are left out of the report, so the report says it is partial.
        return entries, truncated or len(custom) > cls.MAX_CUSTOM_FIELDS

    @classmethod
    def _dates(cls, pdf) -> dict:
        dates = {}
        for key in ("CreationDate", "ModDate"):
            name = f"/{key}"
            if name not in pdf.docinfo:
                dates[key] = None
                continue
            raw = cls._decode(pdf.docinfo[name])
            dates[key] = cls._iso_date(raw)[0:cls.MAX_VALUE_CHARS]
        return dates

    @classmethod
    def _iso_date(cls, raw: str) -> str:
        match = _DATE_PATTERN.fullmatch(raw.strip())
        if match is None:
            return raw
        try:
            year, month, day, hour, minute, second = (
                int(part) if part else default
                for part, default in zip(match.groups()[0:6], (0, 1, 1, 0, 0, 0))
            )
            tzinfo = None
            if match.group(7):
                tzinfo = datetime.timezone.utc
            elif match.group(8):
                offset_hours, offset_minutes = int(match.group(9)), int(match.group(10))
                if offset_hours > 23 or offset_minutes > 59:
                    return raw
                delta = datetime.timedelta(hours=offset_hours, minutes=offset_minutes)
                tzinfo = datetime.timezone(delta if match.group(8) == "+" else -delta)
            return datetime.datetime(year, month, day, hour, minute, second, tzinfo=tzinfo).isoformat()
        except ValueError:
            return raw

    @staticmethod
    def _xmp_name(name: str) -> str:
        """Show common XMP namespaces with their conventional prefix; keep unknown ones in full."""
        if not name.startswith("{") or "}" not in name:
            return name
        namespace, local = name[1:].split("}", 1)
        prefix = _XMP_PREFIXES.get(namespace)
        return f"{prefix}:{local}" if prefix else name

    @classmethod
    def _xmp(cls, pdf):
        if "/Metadata" not in pdf.Root:
            return {"present": False, "entries": []}, False
        entries = []
        truncated = False
        try:
            with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as metadata:
                for name in metadata.keys():
                    if len(entries) >= cls.MAX_XMP_ENTRIES:
                        truncated = True
                        break
                    value = metadata[name]
                    text = ", ".join(str(item) for item in value) if isinstance(value, list) else str(value)
                    text, cut = cls._bounded(text)
                    truncated = truncated or cut
                    entries.append({"name": cls._xmp_name(str(name)), "value": text, "truncated": cut})
        except Exception:
            # A present but unparseable packet is reported as present with no readable entries.
            entries = []
        return {"present": True, "entries": entries}, truncated

    @classmethod
    def _page_sizes(cls, pdf):
        groups: dict[tuple, int] = {}
        for page in pdf.pages:
            left, bottom, right, top = (float(value) for value in page.mediabox)
            key = (round(right - left, 4), round(top - bottom, 4), page_rotation(page.obj))
            groups[key] = groups.get(key, 0) + 1
        ordered = list(groups.items())
        listed = ordered[: cls.MAX_PAGE_SIZE_GROUPS]
        other = sum(count for _, count in ordered[cls.MAX_PAGE_SIZE_GROUPS:])
        return [{"width_pt": width, "height_pt": height, "rotate": rotate, "count": count}
                for (width, height, rotate), count in listed], other

    @classmethod
    def _forms(cls, pdf) -> tuple[dict, bool]:
        acroform = pdf.Root.get("/AcroForm")
        summary = {"fields": 0, "signature_fields": 0, "signed": False, "xfa": False}
        if acroform is None:
            return summary, False
        summary["xfa"] = "/XFA" in acroform
        stack = list(acroform.get("/Fields", []))
        seen = set()
        visited = 0
        while stack:
            node = stack.pop()
            visited += 1
            if visited > cls.MAX_FIELD_NODES:
                return summary, True
            identity = node.objgen
            if identity in seen:
                continue
            seen.add(identity)
            kids = [kid for kid in node.get("/Kids", []) if "/T" in kid]
            if kids:
                stack.extend(kids)
                continue
            summary["fields"] += 1
            if inherited_value(node, "/FT") == pikepdf.Name.Sig:
                summary["signature_fields"] += 1
                if "/V" in node:
                    summary["signed"] = True
        return summary, False

    @classmethod
    def _annotations(cls, pdf) -> int:
        count = 0
        for page in pdf.pages:
            for annotation in page.obj.get("/Annots", []):
                if annotation.get("/Subtype") != pikepdf.Name.Widget:
                    count += 1
        return count
