"""Generated PDF, image and form fixtures for the PDF tool slice tests.

Nothing here is a committed customer file: every byte is built in code.
"""

import io

import pikepdf
import pypdfium2 as pdfium
from PIL import Image
from reportlab.pdfgen import canvas as reportlab_canvas


def pdf_bytes(pdf):
    output = io.BytesIO()
    pdf.save(output)
    return output.getvalue()


def make_pdf(page_sizes, *, text_prefix=None, rotate=None, content=None):
    """Blank pages with optional Helvetica text (``text_prefix`` + page number)."""
    pdf = pikepdf.new()
    font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                                                BaseFont=pikepdf.Name.Helvetica))
    for index, (width, height) in enumerate(page_sizes):
        page = pdf.add_blank_page(page_size=(width, height))
        page.obj.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        if rotate is not None:
            page.obj.Rotate = rotate[index] if isinstance(rotate, (list, tuple)) else rotate
        if content is not None:
            stream_text = content(index, width, height)
        elif text_prefix is not None:
            stream_text = f"BT /F1 24 Tf 72 {height - 96} Td ({text_prefix}{index + 1}) Tj ET"
        else:
            stream_text = ""
        page.obj.Contents = pdf.make_stream(stream_text.encode("latin-1"))
    return pdf


def make_text_pdf(page_sizes, text_prefix="PAGE "):
    return pdf_bytes(make_pdf(page_sizes, text_prefix=text_prefix))


def make_png(width, height, color=(200, 30, 30), *, alpha=None):
    if alpha is None:
        image = Image.new("RGB", (width, height), color)
    else:
        image = Image.new("RGBA", (width, height), tuple(color) + (alpha,))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def make_jpeg(width, height, color=(30, 120, 200), exif_orientation=None):
    image = Image.new("RGB", (width, height), color)
    output = io.BytesIO()
    if exif_orientation is None:
        image.save(output, format="JPEG", quality=92)
    else:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        image.save(output, format="JPEG", quality=92, exif=exif.tobytes())
    return output.getvalue()


def render_page(pdf_content, index=0, scale=1.0, grayscale=False):
    """Render one page with pypdfium2 and return a PIL image (RGB or L)."""
    document = pdfium.PdfDocument(pdf_content)
    try:
        page = document[index]
        bitmap = page.render(scale=scale, grayscale=grayscale)
        image = bitmap.to_pil()
        bitmap.close()
        page.close()
        return image.copy()
    finally:
        document.close()


def make_form_pdf(*, text_value="ALICE", checkbox_on=True, signed=False, xfa=False,
                  with_appearance=True, need_appearances=False):
    """One page with a text field, a checkbox and optionally a signed signature field."""
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=(300, 200))
    font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                                                BaseFont=pikepdf.Name.Helvetica))
    resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(Helv=font))
    page.obj.Resources = resources
    page.obj.Contents = pdf.make_stream(b"")

    def appearance(text):
        body = (f"/Tx BMC BT /Helv 12 Tf 4 8 Td ({text}) Tj ET EMC" if text is not None
                else "")
        stream = pdf.make_stream(body.encode("latin-1"))
        stream.Type = pikepdf.Name.XObject
        stream.Subtype = pikepdf.Name.Form
        stream.BBox = pikepdf.Array([0, 0, 120, 24])
        stream.Resources = resources
        return stream

    text_field = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget, FT=pikepdf.Name.Tx,
        T=pikepdf.String("name"), V=pikepdf.String(text_value), DA=pikepdf.String("/Helv 12 Tf 0 g"),
        Rect=pikepdf.Array([20, 140, 140, 164]), F=4, P=page.obj,
    ))
    if with_appearance:
        text_field.AP = pikepdf.Dictionary(N=pdf.make_indirect(appearance(text_value)))

    on_state = appearance("X")
    off_state = appearance(None)
    checkbox = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget, FT=pikepdf.Name.Btn,
        T=pikepdf.String("agree"), V=pikepdf.Name.Yes if checkbox_on else pikepdf.Name.Off,
        AS=pikepdf.Name.Yes if checkbox_on else pikepdf.Name.Off,
        Rect=pikepdf.Array([20, 90, 40, 110]), F=4, P=page.obj,
        AP=pikepdf.Dictionary(N=pikepdf.Dictionary(Yes=pdf.make_indirect(on_state),
                                                    Off=pdf.make_indirect(off_state))),
    ))
    field_list = [text_field, checkbox]
    if signed:
        signature = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget, FT=pikepdf.Name.Sig,
            T=pikepdf.String("sig"), V=pikepdf.Dictionary(Type=pikepdf.Name.Sig),
            Rect=pikepdf.Array([20, 40, 140, 70]), F=4, P=page.obj,
            AP=pikepdf.Dictionary(N=pdf.make_indirect(appearance("signed"))),
        ))
        field_list.append(signature)
    page.obj.Annots = pikepdf.Array(field_list)
    acroform = pikepdf.Dictionary(Fields=pikepdf.Array(field_list), DA=pikepdf.String("/Helv 12 Tf 0 g"),
                                  DR=resources)
    if need_appearances:
        acroform.NeedAppearances = True
    if xfa:
        acroform.XFA = pdf.make_stream(b"<xdp/>")
    pdf.Root.AcroForm = acroform
    return pdf_bytes(pdf)


def make_annotated_pdf():
    """One page with a free-text note annotation (non-widget) carrying an appearance stream."""
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=(300, 200))
    font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                                                BaseFont=pikepdf.Name.Helvetica))
    resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    stream = pdf.make_stream(b"BT /F1 12 Tf 4 8 Td (NOTE) Tj ET")
    stream.Type = pikepdf.Name.XObject
    stream.Subtype = pikepdf.Name.Form
    stream.BBox = pikepdf.Array([0, 0, 80, 20])
    stream.Resources = resources
    annotation = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Text, Rect=pikepdf.Array([100, 100, 180, 120]),
        F=4, AP=pikepdf.Dictionary(N=pdf.make_indirect(stream)), P=page.obj,
    ))
    page.obj.Annots = pikepdf.Array([annotation])
    page.obj.Contents = pdf.make_stream(b"")
    return pdf_bytes(pdf)


def make_reportlab_pdf(draw, width=300, height=200):
    """Draw with reportlab; ``draw(canvas)`` receives a canvas of the given page size."""
    output = io.BytesIO()
    canvas = reportlab_canvas.Canvas(output, pagesize=(width, height))
    draw(canvas)
    canvas.showPage()
    canvas.save()
    return output.getvalue()
