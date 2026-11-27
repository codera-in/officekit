import io
import unittest
from unittest import mock

import pikepdf

from officekit.engines.engine_pdf_inspect import PdfInspectEngine
from tests.pdf_tool_fixtures import make_annotated_pdf, make_form_pdf, make_pdf, pdf_bytes


def docinfo_by_key(report):
    return {entry["key"]: entry for entry in report["docinfo"]}


def utf16be_string(text):
    return pikepdf.String(b"\xfe\xff" + text.encode("utf-16-be"))


class PdfInspectEngineTests(unittest.TestCase):
    def test_known_docinfo_and_custom_fields_are_listed(self):
        pdf = make_pdf([(612, 792)])
        pdf.docinfo["/Title"] = pikepdf.String("Quarterly report")
        pdf.docinfo["/Author"] = pikepdf.String("Ada")
        pdf.docinfo["/Project"] = pikepdf.String("Atlas")
        report = PdfInspectEngine.inspect(pdf_bytes(pdf))
        fields = docinfo_by_key(report)
        self.assertEqual(fields["Title"]["value"], "Quarterly report")
        self.assertTrue(fields["Title"]["standard"])
        self.assertEqual(fields["Author"]["value"], "Ada")
        self.assertIn("Project", fields)
        self.assertFalse(fields["Project"]["standard"])
        self.assertEqual(len([e for e in report["docinfo"] if e["standard"]]), 9)
        self.assertEqual(report["page_count"], 1)

    def test_absent_and_empty_values_are_distinguished(self):
        pdf = make_pdf([(612, 792)])
        pdf.docinfo["/Keywords"] = pikepdf.String("")
        fields = docinfo_by_key(PdfInspectEngine.inspect(pdf_bytes(pdf)))
        self.assertTrue(fields["Keywords"]["present"])
        self.assertEqual(fields["Keywords"]["value"], "")
        self.assertFalse(fields["Subject"]["present"])
        self.assertIsNone(fields["Subject"]["value"])

    def test_unicode_utf16be_and_pdfdocencoding_are_decoded(self):
        pdf = make_pdf([(612, 792)])
        pdf.docinfo["/Title"] = utf16be_string("Résumé ✓")
        pdf.docinfo["/Subject"] = pikepdf.String(b"\x80Q")
        pdf.docinfo["/Author"] = pikepdf.String(b"plain")
        fields = docinfo_by_key(PdfInspectEngine.inspect(pdf_bytes(pdf)))
        self.assertEqual(fields["Title"]["value"], "Résumé ✓")
        self.assertEqual(fields["Subject"]["value"], "•Q")
        self.assertEqual(fields["Author"]["value"], "plain")

    def test_dates_are_iso_when_valid_and_raw_when_malformed(self):
        pdf = make_pdf([(612, 792)])
        pdf.docinfo["/CreationDate"] = pikepdf.String("D:20261022103000+02'00'")
        pdf.docinfo["/ModDate"] = pikepdf.String("D:2026-99-99 nonsense")
        report = PdfInspectEngine.inspect(pdf_bytes(pdf))
        self.assertEqual(report["dates"]["CreationDate"], "2026-10-22T10:30:00+02:00")
        self.assertEqual(report["dates"]["ModDate"], "D:2026-99-99 nonsense")

    def test_xmp_entries_are_reported(self):
        pdf = make_pdf([(612, 792)])
        with pdf.open_metadata(set_pikepdf_as_editor=False) as metadata:
            metadata["dc:title"] = "XMP Title"
        report = PdfInspectEngine.inspect(pdf_bytes(pdf))
        self.assertTrue(report["xmp"]["present"])
        entries = {entry["name"]: entry for entry in report["xmp"]["entries"]}
        self.assertEqual(entries["dc:title"]["value"], "XMP Title")

    def test_no_xmp_is_reported_as_absent(self):
        report = PdfInspectEngine.inspect(pdf_bytes(make_pdf([(612, 792)])))
        self.assertFalse(report["xmp"]["present"])
        self.assertEqual(report["xmp"]["entries"], [])

    def test_page_sizes_group_and_overflow_into_other_count(self):
        sizes = [(100 + index, 200) for index in range(52)]
        report = PdfInspectEngine.inspect(pdf_bytes(make_pdf(sizes)))
        self.assertEqual(len(report["page_sizes"]), 50)
        self.assertEqual(report["page_sizes"][0]["count"], 1)
        self.assertEqual(report["page_sizes"][0]["rotate"], 0)
        self.assertEqual(report["other_count"], 2)

    def test_page_size_grouping_counts_repeated_geometry(self):
        report = PdfInspectEngine.inspect(pdf_bytes(make_pdf([(612, 792), (612, 792), (300, 200)], rotate=[0, 0, 90])))
        groups = {(g["width_pt"], g["height_pt"], g["rotate"]): g["count"] for g in report["page_sizes"]}
        self.assertEqual(groups[(612.0, 792.0, 0)], 2)
        self.assertEqual(groups[(300.0, 200.0, 90)], 1)
        self.assertEqual(report["other_count"], 0)

    def test_form_summary_reports_fields_signatures_and_xfa(self):
        plain = PdfInspectEngine.inspect(make_form_pdf())
        self.assertEqual(plain["forms"], {"fields": 2, "signature_fields": 0, "signed": False, "xfa": False})
        self.assertEqual(plain["annotations"], 0)
        signed = PdfInspectEngine.inspect(make_form_pdf(signed=True))
        self.assertEqual(signed["forms"]["signature_fields"], 1)
        self.assertTrue(signed["forms"]["signed"])
        xfa = PdfInspectEngine.inspect(make_form_pdf(xfa=True))
        self.assertTrue(xfa["forms"]["xfa"])

    def test_non_widget_annotations_are_counted(self):
        report = PdfInspectEngine.inspect(make_annotated_pdf())
        self.assertEqual(report["annotations"], 1)

    def test_long_values_are_truncated_with_flag(self):
        pdf = make_pdf([(612, 792)])
        pdf.docinfo["/Title"] = pikepdf.String("T" * 2500)
        entry = docinfo_by_key(PdfInspectEngine.inspect(pdf_bytes(pdf)))["Title"]
        self.assertEqual(len(entry["value"]), 2000)
        self.assertTrue(entry["truncated"])

    def test_custom_fields_are_capped_at_sixty_four(self):
        pdf = make_pdf([(612, 792)])
        for index in range(70):
            pdf.docinfo[f"/Custom{index:02d}"] = pikepdf.String(str(index))
        report = PdfInspectEngine.inspect(pdf_bytes(pdf))
        customs = [entry for entry in report["docinfo"] if not entry["standard"]]
        self.assertEqual(len(customs), 64)

    def test_dropped_custom_fields_set_the_truncated_flag(self):
        pdf = make_pdf([(612, 792)])
        for index in range(65):
            pdf.docinfo[f"/Custom{index:02d}"] = pikepdf.String("v")
        self.assertTrue(PdfInspectEngine.inspect(pdf_bytes(pdf))["truncated"])

    def test_form_walk_past_the_node_cap_sets_the_truncated_flag(self):
        source = make_form_pdf()
        self.assertFalse(PdfInspectEngine.inspect(source)["truncated"])
        with mock.patch.object(PdfInspectEngine, "MAX_FIELD_NODES", 1):
            report = PdfInspectEngine.inspect(source)
        self.assertTrue(report["truncated"])

    def test_source_is_not_mutated(self):
        source = pdf_bytes(make_pdf([(612, 792)]))
        snapshot = bytes(source)
        PdfInspectEngine.inspect(source)
        self.assertEqual(source, snapshot)

    def test_malformed_encrypted_and_empty_inputs(self):
        with self.assertRaises(ValueError):
            PdfInspectEngine.inspect(b"")
        with self.assertRaises(pikepdf.PdfError):
            PdfInspectEngine.inspect(b"%PDF-1.4 truncated")
        encrypted = io.BytesIO()
        make_pdf([(612, 792)]).save(encrypted, encryption=pikepdf.Encryption(user="u", owner="o", R=6))
        with self.assertRaises(pikepdf.PasswordError):
            PdfInspectEngine.inspect(encrypted.getvalue())
        with self.assertRaises(ValueError):
            PdfInspectEngine.inspect(pdf_bytes(pikepdf.new()))

    def test_encrypted_flag_is_set_for_owner_password_only_files(self):
        owner_only = io.BytesIO()
        make_pdf([(612, 792)]).save(owner_only, encryption=pikepdf.Encryption(user="", owner="o", R=6))
        self.assertTrue(PdfInspectEngine.inspect(owner_only.getvalue())["encrypted"])
        self.assertFalse(PdfInspectEngine.inspect(pdf_bytes(make_pdf([(612, 792)])))["encrypted"])


if __name__ == "__main__":
    unittest.main()
