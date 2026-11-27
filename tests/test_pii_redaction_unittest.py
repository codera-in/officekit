"""Regression coverage for local PII detection and irreversible output masking."""

import io
import zipfile
import pytest

from officekit.engines.engine_pii_redaction import PiiRedactionEngine, PiiRedactionError


def _txt(text):
    return text.encode("utf-8")


def test_text_scan_classifies_confident_and_possible_matches_and_masks_selection():
    content = _txt("Contact: Maya Chen\nEmail: maya@example.com\nPhone: +1 (415) 555-0138\nDate: 2026-10-12")
    scan = PiiRedactionEngine.scan("intake.txt", content)
    assert [(item["label"], item["confidence"]) for item in scan["matches"]] == [
        ("Person name", "possible"),
        ("Email address", "high"),
        ("Phone number", "high"),
        ("Date · possible birth date", "possible"),
    ]
    assert all(set(item) == {"id", "type", "label", "confidence", "value", "location"} for item in scan["matches"])
    selected = [item["id"] for item in scan["matches"] if item["confidence"] == "high"]
    output, name, media_type = PiiRedactionEngine.redact("intake.txt", content, selected, mode="redact")
    assert name == "intake-redacted.txt"
    assert media_type == "text/plain; charset=utf-8"
    assert b"maya@example.com" not in output
    assert b"+1 (415) 555-0138" not in output
    assert b"Maya Chen" in output


def test_english_resume_cues_find_review_candidates_and_redact_selected_values():
    content = _txt(
        "ALICE ANDERSON\n"
        "AI-Native Fullstack Builder · VP of Engineering\n"
        "Orbitzpay.com | Remote\n"
        "Cypher (cypherhq.io) YC 22\n"
        "VMware Software India Pvt Ltd\n"
        "EDUCATION\n"
        "B Tech\n"
        "Amrita School of Engineering\n"
        "Coimbatore, Tamil Nadu\n"
    )

    scan = PiiRedactionEngine.scan("resume.txt", content)
    reviewable = {item["value"]: item for item in scan["matches"]}

    for value, expected_type in (
        ("ALICE ANDERSON", "person"),
        ("Orbitzpay.com", "organization"),
        ("Cypher", "organization"),
        ("VMware Software India Pvt Ltd", "organization"),
        ("Amrita School of Engineering", "organization"),
    ):
        assert reviewable[value]["type"] == expected_type
        assert reviewable[value]["confidence"] == "possible"
        assert "Context match" in reviewable[value]["label"]

    assert "AI-Native Fullstack Builder" not in reviewable
    assert "Coimbatore" not in reviewable
    selected = [reviewable[value]["id"] for value in reviewable]
    output, _, _ = PiiRedactionEngine.redact("resume.txt", content, selected, mode="redact")
    for value in reviewable:
        assert value.encode() not in output


def test_optional_context_match_is_unchecked_and_stable_through_redact_rescan(monkeypatch):
    class FakeDetector:
        def detect(self, text):
            start = text.index("Nora Scott")
            return [{"type": "person", "label": "Person name", "confidence": "possible", "value": "Nora Scott",
                     "_start": start, "_end": start + len("Nora Scott"), "_source": "neural", "_validation": "none", "_score": 0.91}]

    content = _txt("Please ask our colleague Nora Scott for help.")
    monkeypatch.setenv("OFFICEKIT_PII_CONTEXT_MODEL", "/local/poc-model")
    monkeypatch.setattr(PiiRedactionEngine, "_context_detector", FakeDetector())
    monkeypatch.setattr(PiiRedactionEngine, "_context_detector_path", "/local/poc-model")
    scan = PiiRedactionEngine.scan("note.txt", content)
    match = next(item for item in scan["matches"] if "Context match" in item["label"])
    assert match["confidence"] == "possible"
    assert match["label"] == "Person name · Context match"
    assert set(match) == {"id", "type", "label", "confidence", "value", "location"}
    output, _, _ = PiiRedactionEngine.redact("note.txt", content, [match["id"]], mode="redact")
    assert b"Nora Scott" not in output
    assert b"Nora Scott" in content


def test_optional_context_findings_keep_ocr_location_and_box(monkeypatch):
    from PIL import Image

    class FakeDetector:
        def detect(self, text):
            return [{"type": "person", "label": "Person name", "confidence": "possible", "value": "Nora Scott",
                     "_start": 0, "_end": 10, "_source": "neural", "_validation": "none", "_score": 0.9}]

    source = io.BytesIO()
    Image.new("RGB", (160, 48), "white").save(source, format="PNG")
    observation = [{"text": "Nora Scott", "x": 12.0, "center_y": 20.0, "width": 80.0, "height": 12.0}]
    monkeypatch.setenv("OFFICEKIT_PII_CONTEXT_MODEL", "/local/poc-model")
    monkeypatch.setattr(PiiRedactionEngine, "_context_detector", FakeDetector())
    monkeypatch.setattr(PiiRedactionEngine, "_context_detector_path", "/local/poc-model")
    scan = PiiRedactionEngine.scan("card.png", source.getvalue(), observation)
    match = scan["matches"][0]
    assert match["label"] == "Person name · Context match"
    assert match["location"] == "Image · line 1"
    assert PiiRedactionEngine._matches_in_ocr(observation, "Image")[0]["_box"] == {
        "x0": 12.0, "y0": 14.0, "x1": 92.0, "y1": 26.0,
    }


def test_configured_but_unavailable_context_model_fails_without_fallback(monkeypatch):
    from officekit.engines.pii_context_detector import PiiContextModelUnavailable, PiiContextDetector

    def unavailable(*args, **kwargs):
        raise PiiContextModelUnavailable("private loader detail")

    monkeypatch.setenv("OFFICEKIT_PII_CONTEXT_MODEL", "/missing/local/model")
    monkeypatch.setattr(PiiRedactionEngine, "_context_detector", None)
    monkeypatch.setattr(PiiRedactionEngine, "_context_detector_path", None)
    monkeypatch.setattr(PiiContextDetector, "from_local_path", unavailable)
    with pytest.raises(PiiRedactionError, match="optional local PII context model is unavailable") as error:
        PiiRedactionEngine.scan("note.txt", _txt("ordinary words only"))
    assert "private loader detail" not in str(error.value)


def test_context_model_thread_setting_is_bounded_and_forwarded(monkeypatch):
    from officekit.engines.pii_context_detector import PiiContextDetector

    class FakeDetector:
        pass

    captured = {}

    def load(path, **kwargs):
        captured.update(path=path, **kwargs)
        return FakeDetector()

    monkeypatch.setenv("OFFICEKIT_PII_CONTEXT_MODEL", "/local/poc-model")
    monkeypatch.setenv("OFFICEKIT_PII_CONTEXT_THREADS", "2")
    monkeypatch.setattr(PiiRedactionEngine, "_context_detector", None)
    monkeypatch.setattr(PiiRedactionEngine, "_context_detector_path", None)
    monkeypatch.setattr(PiiContextDetector, "from_local_path", load)

    assert isinstance(PiiRedactionEngine._get_context_detector(), FakeDetector)
    assert captured == {"path": "/local/poc-model", "threads": 2}


@pytest.mark.parametrize("threads", ["0", "5", "2.0", "two", "２"])
def test_invalid_context_model_thread_setting_fails_safely(monkeypatch, threads):
    monkeypatch.setenv("OFFICEKIT_PII_CONTEXT_MODEL", "/local/poc-model")
    monkeypatch.setenv("OFFICEKIT_PII_CONTEXT_THREADS", threads)
    monkeypatch.setattr(PiiRedactionEngine, "_context_detector", None)
    monkeypatch.setattr(PiiRedactionEngine, "_context_detector_path", None)

    with pytest.raises(PiiRedactionError, match="optional local PII context model is unavailable"):
        PiiRedactionEngine._get_context_detector()


def test_invalid_context_output_fails_with_a_fixed_safe_error(monkeypatch):
    class InvalidDetector:
        def detect(self, text):
            raise ValueError("untrusted output details")

    monkeypatch.setenv("OFFICEKIT_PII_CONTEXT_MODEL", "/local/poc-model")
    monkeypatch.setattr(PiiRedactionEngine, "_context_detector", InvalidDetector())
    monkeypatch.setattr(PiiRedactionEngine, "_context_detector_path", "/local/poc-model")
    with pytest.raises(PiiRedactionError, match="returned invalid results") as error:
        PiiRedactionEngine.scan("note.txt", _txt("ordinary words"))
    assert "untrusted output details" not in str(error.value)


def test_context_runtime_failure_becomes_safe_redaction_error(monkeypatch):
    from officekit.engines.pii_context_detector import PiiContextModelUnavailable

    class FailedDetector:
        def detect(self, _text):
            raise PiiContextModelUnavailable("private native runtime details")

    monkeypatch.setenv("OFFICEKIT_PII_CONTEXT_MODEL", "/local/poc-model")
    monkeypatch.setattr(PiiRedactionEngine, "_context_detector", FailedDetector())
    monkeypatch.setattr(PiiRedactionEngine, "_context_detector_path", "/local/poc-model")

    with pytest.raises(PiiRedactionError, match="failed during detection") as error:
        PiiRedactionEngine.scan("note.txt", _txt("ordinary words"))
    assert "private native runtime details" not in str(error.value)


def test_optional_context_match_redacts_vector_pdf_and_docx(monkeypatch):
    class FakeDetector:
        def detect(self, text):
            target = "Nora Scott"
            if target not in text:
                return []
            start = text.index(target)
            return [{"type": "person", "label": "Person name", "confidence": "possible", "value": target,
                     "_start": start, "_end": start + len(target), "_source": "neural", "_validation": "none", "_score": 0.9}]

    monkeypatch.setenv("OFFICEKIT_PII_CONTEXT_MODEL", "/local/poc-model")
    monkeypatch.setattr(PiiRedactionEngine, "_context_detector", FakeDetector())
    monkeypatch.setattr(PiiRedactionEngine, "_context_detector_path", "/local/poc-model")

    from reportlab.pdfgen import canvas
    pdf_source = io.BytesIO()
    pdf = canvas.Canvas(pdf_source, pagesize=(300, 100))
    pdf.drawString(20, 60, "Please ask Nora Scott for help.")
    pdf.save()
    pdf_content = pdf_source.getvalue()
    pdf_scan = PiiRedactionEngine.scan("note.pdf", pdf_content, [])
    pdf_match = next(item for item in pdf_scan["matches"] if "Context match" in item["label"])
    pdf_output, _, _ = PiiRedactionEngine.redact("note.pdf", pdf_content, [pdf_match["id"]], [], mode="redact")
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_output)) as result:
        assert "Nora Scott" not in (result.pages[0].extract_text() or "")

    document_xml = b'''<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Please ask Nora Scott for help.</w:t></w:r></w:p></w:body></w:document>'''
    docx_source = io.BytesIO()
    with zipfile.ZipFile(docx_source, "w") as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr("word/document.xml", document_xml)
    docx_content = docx_source.getvalue()
    docx_scan = PiiRedactionEngine.scan("note.docx", docx_content)
    docx_match = next(item for item in docx_scan["matches"] if "Context match" in item["label"])
    docx_output, _, _ = PiiRedactionEngine.redact("note.docx", docx_content, [docx_match["id"]], mode="redact")
    with zipfile.ZipFile(io.BytesIO(docx_output)) as archive:
        assert b"Nora Scott" not in archive.read("word/document.xml")


@pytest.mark.parametrize("page_count", [10, 50])
def test_optional_context_scan_and_redact_handles_multipage_vector_pdfs(monkeypatch, page_count):
    class FakeDetector:
        def detect(self, text):
            target = "Nora Scott"
            if target not in text:
                return []
            start = text.index(target)
            return [{"type": "person", "label": "Person name", "confidence": "possible", "value": target,
                     "_start": start, "_end": start + len(target), "_source": "neural", "_validation": "none", "_score": 0.9}]

    monkeypatch.setenv("OFFICEKIT_PII_CONTEXT_MODEL", "/local/poc-model")
    monkeypatch.setattr(PiiRedactionEngine, "_context_detector", FakeDetector())
    monkeypatch.setattr(PiiRedactionEngine, "_context_detector_path", "/local/poc-model")
    from reportlab.pdfgen import canvas
    import pdfplumber

    source = io.BytesIO()
    pdf = canvas.Canvas(source, pagesize=(300, 100))
    for page in range(page_count):
        pdf.drawString(20, 60, f"Page {page + 1}: Please ask Nora Scott for help.")
        pdf.showPage()
    pdf.save()
    content = source.getvalue()
    scan = PiiRedactionEngine.scan("multipage.pdf", content, [])
    selected = [item["id"] for item in scan["matches"] if "Context match" in item["label"]]
    assert len(selected) == page_count

    output, _, _ = PiiRedactionEngine.redact("multipage.pdf", content, selected, [], mode="redact")
    with pdfplumber.open(io.BytesIO(output)) as result:
        assert len(result.pages) == page_count
        assert all("Nora Scott" not in (page.extract_text() or "") for page in result.pages)


def test_text_scan_rejects_unsupported_and_invalid_utf8_without_echoing_contents():
    for filename, content in (("file.doc", b"text"), ("file.txt", b"\xff")):
        try:
            PiiRedactionEngine.scan(filename, content)
        except PiiRedactionError as error:
            assert "text" not in str(error).lower() or filename.endswith(".txt")
        else:
            raise AssertionError("invalid input unexpectedly scanned")


def test_empty_selection_creates_a_copy_without_removing_possible_matches():
    content = _txt("Name: Maya Chen")
    output, name, _media_type = PiiRedactionEngine.redact("notes.txt", content, [], mode="redact")
    assert name == "notes-redacted.txt"
    assert b"Maya Chen" in output


def test_selected_ids_must_belong_to_the_scanned_file():
    try:
        PiiRedactionEngine.redact("notes.txt", _txt("Email: maya@example.com"), ["0" * 24])
    except PiiRedactionError as error:
        assert "changed after scanning" in str(error)
    else:
        raise AssertionError("unknown match id unexpectedly redacted")


def test_docx_run_spanning_match_is_removed_from_all_text_runs():
    document_xml = b'''<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Email: maya@</w:t></w:r><w:r><w:t>example.com</w:t></w:r></w:p></w:body></w:document>'''
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr("word/document.xml", document_xml)
    content = source.getvalue()
    scan = PiiRedactionEngine.scan("intake.docx", content)
    assert len(scan["matches"]) == 1
    output, name, media_type = PiiRedactionEngine.redact("intake.docx", content, [scan["matches"][0]["id"]], mode="redact")
    assert name == "intake-redacted.docx"
    assert media_type.endswith("wordprocessingml.document")
    with zipfile.ZipFile(io.BytesIO(output)) as archive:
        xml = archive.read("word/document.xml")
    assert b"maya@example.com" not in xml
    assert b"[REDACTED]" in xml


def test_images_require_an_ocr_box_for_each_selected_match_and_mask_opaquely():
    from PIL import Image

    image = Image.new("RGB", (240, 80), "white")
    source = io.BytesIO()
    image.save(source, format="PNG")
    observations = [
        {"text": "maya@example.com", "x": 20.0, "center_y": 30.0, "width": 150.0, "height": 16.0}
    ]
    scan = PiiRedactionEngine.scan("card.png", source.getvalue(), observations)
    output, name, media_type = PiiRedactionEngine.redact("card.png", source.getvalue(), [scan["matches"][0]["id"]], observations, mode="redact")
    assert name == "card-redacted.png"
    assert media_type == "image/png"
    with Image.open(io.BytesIO(output)) as redacted:
        assert redacted.getpixel((24, 28)) == (0, 0, 0)
        assert redacted.getpixel((210, 28)) == (255, 255, 255)


def test_animated_image_is_rejected_instead_of_redacting_only_first_frame():
    from PIL import Image

    first, second = Image.new("RGB", (8, 8), "white"), Image.new("RGB", (8, 8), "red")
    image = io.BytesIO()
    first.save(image, format="GIF", save_all=True, append_images=[second], duration=100, loop=0)
    try:
        PiiRedactionEngine.scan("animation.gif", image.getvalue())
    except PiiRedactionError as error:
        assert "Animated" in str(error)
    else:
        raise AssertionError("animated image unexpectedly scanned")


def test_pdf_export_flattens_pages_and_removes_selected_text_layer():
    from reportlab.pdfgen import canvas
    import pdfplumber

    source = io.BytesIO()
    pdf = canvas.Canvas(source, pagesize=(300, 160))
    pdf.drawString(25, 120, "Email: maya@example.com")
    pdf.drawString(25, 85, "Ordinary text remains visible")
    pdf.save()
    content = source.getvalue()
    scan = PiiRedactionEngine.scan("document.pdf", content)
    email = next(item for item in scan["matches"] if item["type"] == "email")
    output, name, media_type = PiiRedactionEngine.redact("document.pdf", content, [email["id"]], mode="redact")
    assert name == "document-redacted.pdf"
    assert media_type == "application/pdf"
    with pdfplumber.open(io.BytesIO(output)) as result:
        assert len(result.pages) == 1
        text = result.pages[0].extract_text() or ""
    assert "maya@example.com" not in text
    assert text == ""


def test_default_mask_keeps_limited_email_hint_and_redact_replaces_everything():
    content = _txt("Email: maya.chen@example.com")
    match = PiiRedactionEngine.scan("note.txt", content)["matches"][0]
    masked, masked_name, _media_type = PiiRedactionEngine.redact("note.txt", content, [match["id"]])
    redacted, redacted_name, _media_type = PiiRedactionEngine.redact("note.txt", content, [match["id"]], mode="redact")
    assert masked_name == "note-masked.txt"
    assert "m••••••••@example.com".encode() in masked
    assert b"maya.chen@example.com" not in masked
    assert redacted_name == "note-redacted.txt"
    assert b"[REDACTED]" in redacted
    assert b"example.com" not in redacted


def test_mask_mode_rejects_unknown_mode():
    try:
        PiiRedactionEngine.redact("note.txt", _txt("Email: maya@example.com"), [], mode="unmask")
    except PiiRedactionError as error:
        assert "partial masking" in str(error)
    else:
        raise AssertionError("invalid output mode was accepted")


def test_image_mask_covers_original_text_and_renders_only_partial_hint():
    from PIL import Image

    image = Image.new("RGB", (240, 80), "white")
    source = io.BytesIO()
    image.save(source, format="PNG")
    observations = [{"text": "maya@example.com", "x": 20.0, "center_y": 30.0, "width": 150.0, "height": 16.0}]
    scan = PiiRedactionEngine.scan("card.png", source.getvalue(), observations)
    output, name, _media_type = PiiRedactionEngine.redact("card.png", source.getvalue(), [scan["matches"][0]["id"]], observations)
    assert name == "card-masked.png"
    with Image.open(io.BytesIO(output)) as masked:
        assert masked.getpixel((24, 38)) == (0, 0, 0)
        assert any(masked.getpixel((x, 29)) != (0, 0, 0) for x in range(25, 170))
        assert masked.getpixel((210, 28)) == (255, 255, 255)
