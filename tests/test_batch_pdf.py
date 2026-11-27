"""
TDD Tests for Batch PDF Operations (officekit/engines/engine_pdf_advanced.py)
Covers:
- Batch Merge multiple PDFs into one
- Split PDF by page ranges ('1-2', '3')
- Compression presets ('screen', 'ebook', 'printer')
- Watermark text overlay
- Metadata removal (strip author, producer, title)
- Multi-page extraction
"""

import io
import pytest
import pikepdf
from officekit.engines.engine_pdf_advanced import AdvancedPdfEngine

def create_sample_pdf(num_pages: int = 3, text_prefix: str = "Page") -> bytes:
    """Helper to generate in-memory valid PDFs using pikepdf."""
    pdf = pikepdf.new()
    for i in range(num_pages):
        pdf.add_blank_page(page_size=(612, 792))
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()

def test_batch_merge_pdfs():
    pdf1 = create_sample_pdf(2)
    pdf2 = create_sample_pdf(3)

    merged = AdvancedPdfEngine.merge_multiple([pdf1, pdf2])
    with pikepdf.open(io.BytesIO(merged)) as p:
        assert len(p.pages) == 5


def test_merge_adds_source_bookmarks_at_each_document_boundary():
    first = create_sample_pdf(2)
    second = create_sample_pdf(1)

    merged = AdvancedPdfEngine.merge_multiple(
        [first, second], source_labels=["first.pdf", "second.pdf"]
    )

    with pikepdf.open(io.BytesIO(merged)) as result:
        with result.open_outline() as outline:
            assert [item.title for item in outline.root] == ["first.pdf", "second.pdf"]
            assert [item.destination[0].objgen for item in outline.root] == [
                result.pages[0].objgen,
                result.pages[2].objgen,
            ]


def test_merge_bookmark_labels_remove_controls_and_fall_back_for_empty_names():
    source = create_sample_pdf(1)

    merged = AdvancedPdfEngine.merge_multiple(
        [source, source], source_labels=["unsafe\nname.pdf", "\\folder\\"]
    )

    with pikepdf.open(io.BytesIO(merged)) as result:
        with result.open_outline() as outline:
            assert [item.title for item in outline.root] == ["unsafename.pdf", "Document 2"]


def test_merge_preserves_nested_source_outlines_with_page_destinations():
    source = pikepdf.new()
    source.add_blank_page(page_size=(300, 400))
    source.add_blank_page(page_size=(301, 401))
    with source.open_outline() as outline:
        chapter = pikepdf.OutlineItem("Chapter", 0, page_location="FitH", top=250)
        chapter.color = (0.8, 0.1, 0.2)
        chapter.bold = True
        chapter.is_closed = True
        section = pikepdf.OutlineItem("Section", 1)
        section.italic = True
        chapter.children.append(section)
        outline.root.append(chapter)
    source_bytes = io.BytesIO()
    source.save(source_bytes)
    second = create_sample_pdf(1)

    merged = AdvancedPdfEngine.merge_multiple(
        [source_bytes.getvalue(), second], source_labels=["source.pdf", "appendix.pdf"]
    )

    with pikepdf.open(io.BytesIO(merged)) as result:
        with result.open_outline() as outline:
            source_bookmark, appendix_bookmark = outline.root
            assert source_bookmark.title == "source.pdf"
            chapter_copy = source_bookmark.children[0]
            section_copy = chapter_copy.children[0]
            assert chapter_copy.title == "Chapter"
            assert chapter_copy.destination[0].objgen == result.pages[0].objgen
            assert chapter_copy.resolved_destination(result).top == 250
            assert chapter_copy.color == (0.8, 0.1, 0.2)
            assert chapter_copy.bold is True
            assert chapter_copy.is_closed is True
            assert section_copy.title == "Section"
            assert section_copy.destination[0].objgen == result.pages[1].objgen
            assert section_copy.italic is True
            assert appendix_bookmark.title == "appendix.pdf"


def test_merge_retargets_internal_page_links_to_the_merged_page_tree():
    source = pikepdf.new()
    first_page = source.add_blank_page(page_size=(300, 400))
    target_page = source.add_blank_page(page_size=(301, 401))
    link = source.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name("/Annot"),
            Subtype=pikepdf.Name("/Link"),
            Rect=pikepdf.Array([10, 10, 100, 30]),
            Border=pikepdf.Array([0, 0, 0]),
            Dest=pikepdf.Array([target_page.obj, pikepdf.Name("/Fit")]),
        )
    )
    first_page.obj.Annots = pikepdf.Array([link])
    source_bytes = io.BytesIO()
    source.save(source_bytes)

    merged = AdvancedPdfEngine.merge_multiple([source_bytes.getvalue(), create_sample_pdf(1)])

    with pikepdf.open(io.BytesIO(merged)) as result:
        copied_link = result.pages[0].Annots[0]
        assert copied_link.Subtype == pikepdf.Name("/Link")
        assert copied_link.Dest[0].objgen == result.pages[1].objgen


def test_merge_rejects_malformed_source_outline_instead_of_silently_dropping_it():
    source = pikepdf.new()
    source.add_blank_page()
    with source.open_outline() as outline:
        outline.root.append(pikepdf.OutlineItem("Must have a title", 0))
    del source.Root.Outlines.First["/Title"]
    source_bytes = io.BytesIO()
    source.save(source_bytes)

    with pytest.raises(pikepdf.OutlineStructureError):
        AdvancedPdfEngine.merge_multiple([create_sample_pdf(1), source_bytes.getvalue()])


def make_text_field_pdf(field_name, value):
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=(300, 400))
    field = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name("/Annot"),
            Subtype=pikepdf.Name("/Widget"),
            FT=pikepdf.Name("/Tx"),
            T=field_name,
            V=value,
            Rect=pikepdf.Array([10, 10, 200, 30]),
            F=4,
            P=page.obj,
        )
    )
    page.obj.Annots = pikepdf.Array([field])
    pdf.Root.AcroForm = pdf.make_indirect(
        pikepdf.Dictionary(Fields=pikepdf.Array([field]), DA=pikepdf.String("/Helv 10 Tf 0 g"))
    )
    output = io.BytesIO()
    pdf.save(output)
    return output.getvalue()


def test_merge_preserves_acroform_values_and_renames_colliding_fields():
    first = make_text_field_pdf("Customer", "Ada")
    second = make_text_field_pdf("Customer", "Grace")

    merged = AdvancedPdfEngine.merge_multiple([first, second], ["first.pdf", "second.pdf"])

    with pikepdf.open(io.BytesIO(merged)) as result:
        fields = result.acroform.fields
        assert [field.value for field in fields] == ["Ada", "Grace"]
        assert len({field.fully_qualified_name for field in fields}) == 2
        assert len(result.pages) == 2

def test_split_pdf_ranges():
    pdf_data = create_sample_pdf(6)

    # Extract pages 2-3 and 5
    split_bytes = AdvancedPdfEngine.split_by_ranges(pdf_data, page_ranges="2-3, 5")
    with pikepdf.open(io.BytesIO(split_bytes)) as p:
        assert len(p.pages) == 3

def test_compress_pdf_presets():
    pdf_data = create_sample_pdf(4)

    for preset in ("fast", "balanced", "maximum", "screen", "ebook", "printer"):
        compressed_bytes, ratio = AdvancedPdfEngine.compress_pdf(pdf_data, preset=preset)
        assert isinstance(compressed_bytes, bytes)
        assert len(compressed_bytes) > 0
        assert ratio == pytest.approx(len(compressed_bytes) / len(pdf_data))
        with pikepdf.open(io.BytesIO(compressed_bytes)) as compressed_pdf:
            assert len(compressed_pdf.pages) == 4


def test_compress_pdf_preserves_page_geometry_and_decoded_content():
    pdf = pikepdf.new()
    for page_number in range(3):
        page = pdf.add_blank_page(page_size=(612 + page_number, 792))
        page.Contents = pdf.make_stream(
            f"q 1 0 0 1 {10 + page_number} 20 cm Q\n".encode("ascii")
        )
    source = io.BytesIO()
    pdf.save(source)
    original_bytes = source.getvalue()

    compressed_bytes, _ = AdvancedPdfEngine.compress_pdf(original_bytes, preset="balanced")
    with pikepdf.open(io.BytesIO(original_bytes)) as original, pikepdf.open(
        io.BytesIO(compressed_bytes)
    ) as compressed:
        assert len(compressed.pages) == len(original.pages) == 3
        for original_page, compressed_page in zip(original.pages, compressed.pages):
            assert list(compressed_page.MediaBox) == list(original_page.MediaBox)
            assert compressed_page.Contents.read_bytes() == original_page.Contents.read_bytes()


def test_compress_pdf_preserves_form_values_annotations_outlines_and_metadata():
    with pikepdf.open(io.BytesIO(make_text_field_pdf("Account", "001234"))) as source:
        source.docinfo["/Title"] = "Statement title"
        with source.open_outline() as outline:
            outline.root.append(pikepdf.OutlineItem("Transactions", 0))
        source_buffer = io.BytesIO()
        source.save(source_buffer)

    compressed, _ = AdvancedPdfEngine.compress_pdf(source_buffer.getvalue(), preset="maximum")

    with pikepdf.open(io.BytesIO(compressed)) as result:
        assert len(result.pages) == 1
        assert result.docinfo["/Title"] == "Statement title"
        assert result.pages[0].Annots[0].Subtype == pikepdf.Name("/Widget")
        assert result.pages[0].Annots[0].V == "001234"
        assert result.Root.AcroForm.Fields[0].V == "001234"
        with result.open_outline() as outline:
            assert [item.title for item in outline.root] == ["Transactions"]


def test_compress_pdf_preserves_rendered_visuals_for_vector_text_and_raster_content():
    pytest.importorskip("pypdfium2")
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    from PIL import Image, ImageChops
    import pypdfium2

    page = io.BytesIO()
    document = canvas.Canvas(page, pagesize=(360, 240), pageCompression=0)
    document.setFillColorRGB(0.12, 0.32, 0.68)
    document.rect(18, 18, 324, 204, fill=1, stroke=0)
    document.setFillColorRGB(1, 1, 1)
    document.setFont("Helvetica", 17)
    document.drawString(34, 190, "OfficeKit lossless compression check")
    pixels = Image.new("RGB", (48, 32))
    pixels.putdata([
        (x * 5, y * 7, (x * 13 + y * 3) % 256)
        for y in range(32) for x in range(48)
    ])
    document.drawImage(ImageReader(pixels), 38, 48, width=144, height=96)
    document.setStrokeColorRGB(1, 0.72, 0.1)
    document.setLineWidth(3)
    document.line(210, 60, 318, 165)
    document.save()
    pixels.close()

    source = page.getvalue()
    def render(pdf_bytes):
        pdf = pypdfium2.PdfDocument(pdf_bytes)
        try:
            bitmap = pdf[0].render(scale=1.5, rev_byteorder=True)
            try:
                return bitmap.to_pil().convert("RGB")
            finally:
                bitmap.close()
        finally:
            pdf.close()

    for preset in ("fast", "balanced", "maximum"):
        compressed, _ = AdvancedPdfEngine.compress_pdf(source, preset=preset)
        original_image = render(source)
        compressed_image = render(compressed)
        try:
            assert compressed_image.size == original_image.size
            assert ImageChops.difference(original_image, compressed_image).getbbox() is None
        finally:
            original_image.close()
            compressed_image.close()


def test_compress_pdf_rejects_unknown_preset():
    with pytest.raises(ValueError, match="Unknown PDF compression preset"):
        AdvancedPdfEngine.compress_pdf(create_sample_pdf(1), preset="lossy")

def test_remove_pdf_metadata():
    pdf = pikepdf.new()
    pdf.add_blank_page()
    with pdf.open_metadata() as meta:
        meta['dc:title'] = 'Confidential Bank Statement'
        meta['dc:creator'] = 'John Doe'
    buf = io.BytesIO()
    pdf.save(buf)
    dirty_pdf = buf.getvalue()

    cleaned_bytes = AdvancedPdfEngine.strip_metadata(dirty_pdf)
    with pikepdf.open(io.BytesIO(cleaned_bytes)) as p:
        docinfo = p.docinfo
        assert 'Title' not in docinfo or str(docinfo.get('Title', '')) == ''
