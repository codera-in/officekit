"""Run the configured local PII model through the real text scan/redact engine."""

from __future__ import annotations

import argparse
import json
import os
import io
import socket
import sys
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from officekit.engines.engine_pii_redaction import PiiRedactionEngine


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--deny-network", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.deny_network:
        def deny_network(*_args, **_kwargs):
            raise RuntimeError("Network access was denied by the PII smoke test.")

        socket.socket.connect = deny_network
        socket.socket.connect_ex = deny_network
        socket.socket.sendto = deny_network
        socket.create_connection = deny_network
    os.environ["OFFICEKIT_PII_CONTEXT_MODEL"] = str(args.model_path.expanduser().resolve())
    os.environ["HF_HUB_OFFLINE"] = "1" if args.deny_network else os.environ.get("HF_HUB_OFFLINE", "0")
    os.environ["TRANSFORMERS_OFFLINE"] = "1" if args.deny_network else os.environ.get("TRANSFORMERS_OFFLINE", "0")
    content = b"Please ask our colleague Nora Scott for help with the report."
    started = time.perf_counter()
    report = PiiRedactionEngine.scan("synthetic-pii-context.txt", content)
    scan_seconds = time.perf_counter() - started
    matches = [item for item in report["matches"] if item["label"].endswith(" · Context match")]
    if len(matches) != 1:
        raise RuntimeError(f"The local model returned {len(matches)} contextual findings for the synthetic smoke input.")
    selected = matches[0]
    first_id = selected["id"]
    masked, _, _ = PiiRedactionEngine.redact("synthetic-pii-context.txt", content, [first_id], mode="mask")
    redacted, _, _ = PiiRedactionEngine.redact("synthetic-pii-context.txt", content, [first_id], mode="redact")
    rescanned = PiiRedactionEngine.scan("synthetic-pii-context.txt", content)
    if first_id not in {item["id"] for item in rescanned["matches"]}:
        raise RuntimeError("The model did not produce a stable identifier on rescan.")
    if b"Nora Scott" not in content or b"Nora Scott" in redacted or b"Nora Scott" in masked:
        raise RuntimeError("The local model output did not preserve source bytes and redact the selected value.")
    format_results = []
    for extension in ("csv", "md"):
        text_source = b"note,details\n1,Please ask our colleague Nora Scott for help.\n" if extension == "csv" else content
        text_result = _exercise_format(f"native-pii-smoke.{extension}", text_source)
        if b"Nora Scott" in text_result["redacted_bytes"]:
            raise RuntimeError(f"The native {extension.upper()} path did not remove the selected synthetic value.")
        format_results.append({key: value for key, value in text_result.items() if key != "redacted_bytes"})

    from reportlab.pdfgen import canvas
    pdf_buffer = io.BytesIO()
    pdf = canvas.Canvas(pdf_buffer, pagesize=(420, 100))
    pdf.drawString(20, 55, "Please ask our colleague Nora Scott for help.")
    pdf.save()
    pdf_source = pdf_buffer.getvalue()
    pdf_result = _exercise_format("native-pii-smoke.pdf", pdf_source)
    from pypdf import PdfReader
    pdf_reader = PdfReader(io.BytesIO(pdf_result["redacted_bytes"]))
    pdf_text_after = "\n".join(page.extract_text() or "" for page in pdf_reader.pages)
    if "Nora Scott" in pdf_text_after:
        raise RuntimeError("The native PDF path did not remove the selected synthetic value.")
    format_results.append({key: value for key, value in pdf_result.items() if key != "redacted_bytes"})

    docx_buffer = io.BytesIO()
    _make_docx(docx_buffer, "Please ask our colleague Nora Scott for help.")
    docx_source = docx_buffer.getvalue()
    docx_result = _exercise_format("native-pii-smoke.docx", docx_source)
    if "Nora Scott" in _docx_text(docx_result["redacted_bytes"]):
        raise RuntimeError("The native DOCX path did not remove the selected synthetic value.")
    format_results.append({key: value for key, value in docx_result.items() if key != "redacted_bytes"})

    for extension, entries in (("xlsx", _xlsx_parts("Please ask our colleague Nora Scott for help.")),
                               ("pptx", _pptx_parts("Please ask our colleague Nora Scott for help."))):
        office_source = _make_office_archive(entries)
        office_result = _exercise_format(f"native-pii-smoke.{extension}", office_source)
        if "Nora Scott" in "".join(_office_texts(office_result["redacted_bytes"])):
            raise RuntimeError(f"The native {extension.upper()} path did not remove the selected synthetic value.")
        format_results.append({key: value for key, value in office_result.items() if key != "redacted_bytes"})

    from PIL import Image, ImageDraw, ImageChops
    image = Image.new("RGB", (640, 100), "white")
    ImageDraw.Draw(image).text((12, 30), "Please ask our colleague Nora Scott for help.", fill="black")
    image_source = io.BytesIO()
    image.save(image_source, format="PNG")
    image_bytes = image_source.getvalue()
    observation = [{"text": "Please ask our colleague Nora Scott for help.", "x": 12.0,
                   "center_y": 38.0, "width": 230.0, "height": 14.0}]
    image_result = _exercise_format("native-pii-smoke.png", image_bytes, observation)
    output_image = Image.open(io.BytesIO(image_result["redacted_bytes"])).convert("RGB")
    if ImageChops.difference(image, output_image).getbbox() is None:
        raise RuntimeError("The native OCR geometry path did not alter the selected image region.")
    format_results.append({key: value for key, value in image_result.items() if key != "redacted_bytes"})
    result = {
        "backend": "local-model",
        "network_denied": args.deny_network,
        "scan_seconds": scan_seconds,
        "match_count": len(report["matches"]),
        "context_match_count": len(matches),
        "context_type": selected["type"],
        "context_confidence": selected["confidence"],
        "stable_id_on_rescan": True,
        "mask_removed_target": b"Nora Scott" not in masked,
        "redact_removed_target": b"Nora Scott" not in redacted,
        "source_preserved": b"Nora Scott" in content,
        "real_model_format_checks": format_results,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


def _exercise_format(filename: str, source: bytes, observations=None) -> dict:
    started = time.perf_counter()
    report = PiiRedactionEngine.scan(filename, source, observations)
    scan_seconds = time.perf_counter() - started
    matches = [item for item in report["matches"] if item["value"] == "Nora Scott"]
    contextual = [item for item in matches if item["label"].endswith(" · Context match")]
    if len(contextual) != 1:
        raise RuntimeError(f"The native model returned {len(contextual)} contextual findings for {filename}.")
    output, _, _ = PiiRedactionEngine.redact(filename, source, [contextual[0]["id"]],
                                               ocr_observations=observations, mode="redact")
    return {"format": report["format"], "scan_seconds": scan_seconds, "matches": len(report["matches"]),
            "stable_id": contextual[0]["id"] in {item["id"] for item in PiiRedactionEngine.scan(filename, source, observations)["matches"]},
            "redaction_output_changed": source != output, "selected_value_removed": True,
            "redacted_bytes": output}


def _make_docx(buffer: io.BytesIO, text: str) -> None:
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                     '</Types>')
    relationships = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                     '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                     '</Relationships>')
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t xml:space="preserve">' + text + '</w:t></w:r></w:p>'
                '<w:sectPr/></w:body></w:document>')
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/document.xml", document)


def _docx_text(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    return "".join(item.text or "" for item in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"))


def _xlsx_parts(text: str) -> dict[str, str]:
    return {"xl/sharedStrings.xml": ('<?xml version="1.0" encoding="UTF-8"?>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>' + text + '</t></si></sst>')}


def _pptx_parts(text: str) -> dict[str, str]:
    return {"ppt/slides/slide1.xml": ('<?xml version="1.0" encoding="UTF-8"?>'
            '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree>'
            '<p:sp><p:txBody><a:p><a:r><a:t>' + text + '</a:t></a:r></a:p></p:txBody></p:sp>'
            '</p:spTree></p:cSld></p:sld>')}


def _make_office_archive(parts: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in parts.items():
            archive.writestr(name, value)
    return output.getvalue()


def _office_texts(content: bytes) -> list[str]:
    output = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for name in archive.namelist():
            if name.endswith(".xml"):
                try:
                    root = ElementTree.fromstring(archive.read(name))
                except ElementTree.ParseError:
                    continue
                output.append("".join(item.text or "" for item in root.iter()))
    return output


if __name__ == "__main__":
    raise SystemExit(main())
