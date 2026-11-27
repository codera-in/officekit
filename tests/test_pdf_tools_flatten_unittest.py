import io
import unittest
from unittest import mock

import pdfplumber
import pikepdf

from officekit.engines.engine_pdf_flatten import FlattenRefusedError, PdfFlattenEngine
from officekit.engines.engine_pdf_security import PdfOutputLimitError
from tests.pdf_tool_fixtures import make_annotated_pdf, make_form_pdf, make_pdf, pdf_bytes, render_page


def page_text(data):
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return pdf.pages[0].extract_text() or ""


def structure(data):
    with pikepdf.open(io.BytesIO(data)) as pdf:
        acroform = "/AcroForm" in pdf.Root
        widgets = 0
        annotations = 0
        for page in pdf.pages:
            for annotation in page.obj.get("/Annots", []):
                if annotation.get("/Subtype") == pikepdf.Name.Widget:
                    widgets += 1
                else:
                    annotations += 1
        return {"acroform": acroform, "widgets": widgets, "annotations": annotations}


def has_ink(data, box):
    """True when the rendered output has dark pixels inside a page-space box (values are visible)."""
    scale = 2
    image = render_page(data, 0, scale=scale).convert("L")
    left, bottom, right, top = box
    crop = image.crop((int(left * scale), int((200 - top) * scale),
                       int(right * scale), int((200 - bottom) * scale)))
    return crop.getextrema()[0] < 128


class FlattenFormsTests(unittest.TestCase):
    def test_forms_scope_removes_structure_and_keeps_values_visible(self):
        source = make_form_pdf(text_value="ALICE")
        snapshot = bytes(source)
        output, fields, annotations = PdfFlattenEngine.flatten(source, "forms", False)
        self.assertEqual(fields, 2)
        self.assertEqual(annotations, 0)
        self.assertEqual(structure(output), {"acroform": False, "widgets": 0, "annotations": 0})
        self.assertIn("ALICE", page_text(output))
        self.assertTrue(has_ink(output, (20, 140, 140, 164)))
        self.assertEqual(source, snapshot)

    def test_choice_field_value_is_visible_after_flatten(self):
        pdf = make_pdf([(300, 200)])
        font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                                                    BaseFont=pikepdf.Name.Helvetica))
        resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(Helv=font))
        appearance = pdf.make_stream(b"/Tx BMC BT /Helv 12 Tf 4 8 Td (OptA) Tj ET EMC")
        appearance.Type = pikepdf.Name.XObject
        appearance.Subtype = pikepdf.Name.Form
        appearance.BBox = pikepdf.Array([0, 0, 120, 24])
        appearance.Resources = resources
        choice = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget, FT=pikepdf.Name.Ch,
            T=pikepdf.String("choice"), V=pikepdf.String("OptA"), Ff=0,
            Rect=pikepdf.Array([20, 100, 140, 124]), F=4, P=pdf.pages[0].obj,
            AP=pikepdf.Dictionary(N=pdf.make_indirect(appearance))))
        pdf.pages[0].obj.Annots = pikepdf.Array([choice])
        pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array([choice]), DR=resources)
        output, fields, _ = PdfFlattenEngine.flatten(pdf_bytes(pdf), "forms", False)
        self.assertEqual(fields, 1)
        self.assertIn("OptA", page_text(output))
        self.assertTrue(has_ink(output, (20, 100, 140, 124)))
        self.assertEqual(structure(output), {"acroform": False, "widgets": 0, "annotations": 0})

    def test_checkbox_state_selects_appearance(self):
        checked, _, _ = PdfFlattenEngine.flatten(make_form_pdf(checkbox_on=True), "forms", False)
        unchecked, _, _ = PdfFlattenEngine.flatten(make_form_pdf(checkbox_on=False), "forms", False)
        self.assertIn("X", page_text(checked))
        self.assertNotIn("X", page_text(unchecked))

    def test_missing_appearance_is_generated_from_the_value(self):
        source = make_form_pdf(text_value="BOB", with_appearance=False)
        output, _, _ = PdfFlattenEngine.flatten(source, "forms", False)
        self.assertIn("BOB", page_text(output))
        self.assertEqual(structure(output)["widgets"], 0)

    def test_signed_field_needs_acknowledgement(self):
        source = make_form_pdf(signed=True)
        with self.assertRaises(FlattenRefusedError) as refused:
            PdfFlattenEngine.flatten(source, "forms", False)
        self.assertEqual(refused.exception.code, "signature_ack_required")
        self.assertEqual(refused.exception.status, 409)
        output, fields, _ = PdfFlattenEngine.flatten(source, "forms", True)
        self.assertEqual(fields, 3)
        self.assertEqual(structure(output)["acroform"], False)

    def test_signed_field_does_not_block_annotations_scope(self):
        output, _, _ = PdfFlattenEngine.flatten(make_form_pdf(signed=True), "annotations", False)
        self.assertEqual(structure(output)["widgets"], 3)

    def test_xfa_is_refused_with_422(self):
        with self.assertRaises(FlattenRefusedError) as refused:
            PdfFlattenEngine.flatten(make_form_pdf(xfa=True), "forms", True)
        self.assertEqual(refused.exception.code, "xfa_unsupported")
        self.assertEqual(refused.exception.status, 422)

    def test_appearance_that_cannot_be_drawn_is_refused(self):
        pdf = make_pdf([(200, 200)])
        widget = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget, FT=pikepdf.Name.Btn,
            T=pikepdf.String("bare"), Rect=pikepdf.Array([0, 0, 20, 20]), F=4))
        pdf.pages[0].obj.Annots = pikepdf.Array([widget])
        pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array([widget]))
        with self.assertRaises(FlattenRefusedError) as refused:
            PdfFlattenEngine.flatten(pdf_bytes(pdf), "forms", True)
        self.assertEqual(refused.exception.code, "appearance_missing")
        self.assertEqual(refused.exception.status, 422)


class FlattenAnnotationsTests(unittest.TestCase):
    def test_annotations_scope_draws_and_removes_non_widgets(self):
        source = make_annotated_pdf()
        output, fields, annotations = PdfFlattenEngine.flatten(source, "annotations", False)
        self.assertEqual((fields, annotations), (0, 1))
        self.assertEqual(structure(output)["annotations"], 0)
        self.assertIn("NOTE", page_text(output))
        self.assertTrue(has_ink(output, (100, 100, 180, 120)))

    def test_hidden_annotations_are_removed_without_drawing(self):
        pdf = pikepdf.open(io.BytesIO(make_annotated_pdf()))
        annotation = pdf.pages[0].obj.Annots[0]
        annotation.F = 2
        data = io.BytesIO()
        pdf.save(data)
        pdf.close()
        output, _, drawn = PdfFlattenEngine.flatten(data.getvalue(), "annotations", False)
        self.assertEqual(drawn, 0)
        self.assertNotIn("NOTE", page_text(output))
        self.assertEqual(structure(output)["annotations"], 0)

    def test_all_scope_flattens_forms_and_annotations(self):
        pdf = pikepdf.open(io.BytesIO(make_form_pdf(text_value="CAROL")))
        annotated = pikepdf.open(io.BytesIO(make_annotated_pdf()))
        pdf.pages[0].obj.Annots.append(pdf.copy_foreign(annotated.pages[0].obj.Annots[0]))
        annotated.close()
        data = io.BytesIO()
        pdf.save(data)
        pdf.close()
        output, fields, annotations = PdfFlattenEngine.flatten(data.getvalue(), "all", True)
        self.assertEqual((fields, annotations), (2, 1))
        self.assertEqual(structure(output), {"acroform": False, "widgets": 0, "annotations": 0})
        self.assertIn("CAROL", page_text(output))
        self.assertIn("NOTE", page_text(output))

    def test_link_annotations_are_removed_in_annotations_scope(self):
        pdf = make_pdf([(200, 200)])
        link = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
                                                    Rect=pikepdf.Array([0, 0, 10, 10])))
        pdf.pages[0].obj.Annots = pikepdf.Array([link])
        output, _, _ = PdfFlattenEngine.flatten(pdf_bytes(pdf), "annotations", False)
        self.assertEqual(structure(output)["annotations"], 0)

    def test_annotation_without_appearance_is_refused(self):
        pdf = make_pdf([(200, 200)])
        note = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Text,
                                                    Rect=pikepdf.Array([0, 0, 10, 10])))
        pdf.pages[0].obj.Annots = pikepdf.Array([note])
        with self.assertRaises(FlattenRefusedError) as refused:
            PdfFlattenEngine.flatten(pdf_bytes(pdf), "annotations", False)
        self.assertEqual(refused.exception.code, "appearance_missing")


class FlattenEngineGuardsTests(unittest.TestCase):
    def test_scope_and_flag_validation(self):
        source = make_form_pdf()
        with self.assertRaises(ValueError):
            PdfFlattenEngine.flatten(source, "text", False)
        with self.assertRaises(ValueError):
            PdfFlattenEngine.flatten(source, "forms", "yes")

    def test_malformed_encrypted_empty_and_output_cap(self):
        with self.assertRaises(ValueError):
            PdfFlattenEngine.flatten(b"", "all", False)
        with self.assertRaises(pikepdf.PdfError):
            PdfFlattenEngine.flatten(b"%PDF nope", "all", False)
        encrypted = io.BytesIO()
        pdf = pikepdf.open(io.BytesIO(make_form_pdf()))
        pdf.save(encrypted, encryption=pikepdf.Encryption(user="u", owner="o", R=6))
        pdf.close()
        with self.assertRaises(pikepdf.PasswordError):
            PdfFlattenEngine.flatten(encrypted.getvalue(), "all", False)
        with mock.patch.object(PdfFlattenEngine, "MAX_OUTPUT_BYTES", 64), self.assertRaises(PdfOutputLimitError):
            PdfFlattenEngine.flatten(make_form_pdf(), "forms", False)

    def test_structural_self_check_rejects_surviving_widgets_and_acroform(self):
        with self.assertRaises(RuntimeError):
            PdfFlattenEngine._verify_structure(make_form_pdf(), "forms")
        with self.assertRaises(RuntimeError):
            PdfFlattenEngine._verify_structure(make_annotated_pdf(), "annotations")
        PdfFlattenEngine._verify_structure(make_annotated_pdf(), "forms")


if __name__ == "__main__":
    unittest.main()
