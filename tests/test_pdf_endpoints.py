import io
import base64
import zipfile
import unicodedata
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")
pikepdf = pytest.importorskip("pikepdf")
pytest.importorskip("PIL")
pytest.importorskip("pandas")

from fastapi.testclient import TestClient

from app import app
from officekit.engines.engine_pdf_advanced import AdvancedPdfEngine


def make_pdf(page_sizes, *, title=None, encryption=None):
    pdf = pikepdf.new()
    for width, height in page_sizes:
        pdf.add_blank_page(page_size=(width, height))
    if title:
        pdf.docinfo["/Title"] = title
    output = io.BytesIO()
    pdf.save(output, encryption=encryption)
    return output.getvalue()


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


def make_page_form_pdf():
    pdf = pikepdf.new()
    fields = []
    for index, page in enumerate([
        pdf.add_blank_page(page_size=(300, 400)),
        pdf.add_blank_page(page_size=(301, 401)),
        pdf.add_blank_page(page_size=(302, 402)),
    ], start=1):
        widget = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name("/Annot"),
                Subtype=pikepdf.Name("/Widget"),
                FT=pikepdf.Name("/Tx"),
                T=f"Field {index}",
                V=f"Value {index}",
                Rect=pikepdf.Array([10, 10, 200, 30]),
                F=4,
                P=page.obj,
            )
        )
        page.obj.Annots = pikepdf.Array([widget])
        fields.append(widget)
    pdf.Root.AcroForm = pdf.make_indirect(
        pikepdf.Dictionary(Fields=pikepdf.Array(fields), DA=pikepdf.String("/Helv 10 Tf 0 g"))
    )
    output = io.BytesIO()
    pdf.save(output)
    return output.getvalue()


def make_pdf_with_malformed_outline():
    pdf = pikepdf.new()
    pdf.add_blank_page()
    with pdf.open_outline() as outline:
        outline.root.append(pikepdf.OutlineItem("Must have a title", 0))
    del pdf.Root.Outlines.First["/Title"]
    output = io.BytesIO()
    pdf.save(output)
    return output.getvalue()


def make_pdf_with_internal_navigation():
    pdf = pikepdf.new()
    for width, height in [(300, 400), (301, 401), (302, 402)]:
        pdf.add_blank_page(page_size=(width, height))
    pdf.docinfo["/Title"] = "Navigation fixture"
    link = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name("/Annot"),
            Subtype=pikepdf.Name("/Link"),
            Rect=pikepdf.Array([0, 0, 20, 20]),
            A=pikepdf.Dictionary(
                S=pikepdf.Name("/GoTo"),
                D=pikepdf.Array([pdf.pages[0].obj, pikepdf.Name("/Fit")]),
            ),
        )
    )
    pdf.pages[2].obj.Annots = pikepdf.Array([link])
    with pdf.open_outline() as outline:
        outline.root.append(pikepdf.OutlineItem("First page bookmark", 0))
    output = io.BytesIO()
    pdf.save(output)
    return output.getvalue()


@pytest.fixture
def client():
    return TestClient(app)


def test_merge_route_merges_selected_pdfs_in_order_and_returns_attachment(client):
    first_pdf = pikepdf.new()
    first_pdf.add_blank_page(page_size=(300, 400))
    first_pdf.add_blank_page(page_size=(301, 401))
    with first_pdf.open_outline() as outline:
        outline.root.append(pikepdf.OutlineItem("Original section", 1))
    first_output = io.BytesIO()
    first_pdf.save(first_output)
    first = first_output.getvalue()
    second = make_pdf([(500, 600)])
    response = client.post(
        "/api/pdf/merge",
        files=[("files", ("first.pdf", first, "application/pdf")),
               ("files", ("second.pdf", second, "application/pdf"))],
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "merged.pdf" in response.headers["content-disposition"]
    with pikepdf.open(io.BytesIO(response.content)) as result:
        assert [list(page.MediaBox) for page in result.pages] == [
            [0, 0, 300, 400], [0, 0, 301, 401], [0, 0, 500, 600]
        ]
        with result.open_outline() as outline:
            assert [item.title for item in outline.root] == ["first.pdf", "second.pdf"]
            assert [item.destination[0].objgen for item in outline.root] == [
                result.pages[0].objgen,
                result.pages[2].objgen,
            ]
            original_section = outline.root[0].children[0]
            assert original_section.title == "Original section"
            assert original_section.destination[0].objgen == result.pages[1].objgen


def test_merge_route_preserves_acroform_values_and_unique_names(client):
    response = client.post(
        "/api/pdf/merge",
        files=[
            ("files", ("first.pdf", make_text_field_pdf("Customer", "Ada"), "application/pdf")),
            ("files", ("second.pdf", make_text_field_pdf("Customer", "Grace"), "application/pdf")),
        ],
    )

    assert response.status_code == 200
    with pikepdf.open(io.BytesIO(response.content)) as result:
        fields = result.acroform.fields
        assert [field.value for field in fields] == ["Ada", "Grace"]
        assert len({field.fully_qualified_name for field in fields}) == 2
        assert len(result.pages) == 2


def test_merge_route_rejects_malformed_outline_without_returning_partial_output(client):
    response = client.post(
        "/api/pdf/merge",
        files=[
            ("files", ("valid.pdf", make_pdf([(300, 400)]), "application/pdf")),
            ("files", ("malformed-outline.pdf", make_pdf_with_malformed_outline(), "application/pdf")),
        ],
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "The PDF file is invalid or the requested operation is unsupported."}


def test_merge_route_rejects_wrong_file_count_and_malformed_pdf(client):
    one_file = client.post(
        "/api/pdf/merge", files=[("files", ("one.pdf", make_pdf([(300, 400)]), "application/pdf"))]
    )
    invalid_input = client.post(
        "/api/pdf/merge",
        files=[("files", ("one.pdf", b"not a PDF", "application/pdf")),
               ("files", ("two.pdf", make_pdf([(300, 400)]), "application/pdf"))],
    )

    assert one_file.status_code == 422
    assert invalid_input.status_code == 422
    assert "detail" in invalid_input.json()
    assert "not a PDF" not in invalid_input.text


def test_split_route_preserves_requested_page_order_and_rejects_duplicate_or_out_of_range(client):
    source = make_pdf([(300 + index, 400 + index) for index in range(5)])
    response = client.post(
        "/api/pdf/split", data={"page_ranges": "5, 2-3"},
        files={"file": ("pages.pdf", source, "application/pdf")},
    )
    duplicate = client.post(
        "/api/pdf/split", data={"page_ranges": "1-2,2"},
        files={"file": ("pages.pdf", source, "application/pdf")},
    )
    out_of_range = client.post(
        "/api/pdf/split", data={"page_ranges": "6"},
        files={"file": ("pages.pdf", source, "application/pdf")},
    )

    assert response.status_code == 200
    with pikepdf.open(io.BytesIO(response.content)) as result:
        assert [list(page.MediaBox) for page in result.pages] == [
            [0, 0, 304, 404], [0, 0, 301, 401], [0, 0, 302, 402]
        ]
    assert duplicate.status_code == 422
    assert out_of_range.status_code == 422


def test_delete_pages_route_removes_selected_pages_and_preserves_source(client):
    original = make_pdf([(300, 400), (301, 401), (302, 402)])
    response = client.post(
        "/api/pdf/pages/delete",
        files={"file": ("source.pdf", original, "application/pdf")},
        data={"page_ranges": "2"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "deleted-pages.pdf" in response.headers["content-disposition"]
    with pikepdf.open(io.BytesIO(response.content)) as result:
        assert [list(page.MediaBox) for page in result.pages] == [
            [0, 0, 300, 400], [0, 0, 302, 402]
        ]
    with pikepdf.open(io.BytesIO(original)) as unchanged:
        assert len(unchanged.pages) == 3


def test_delete_pages_removes_deleted_widgets_and_keeps_surviving_form_fields(client):
    response = client.post(
        "/api/pdf/pages/delete",
        files={"file": ("form.pdf", make_page_form_pdf(), "application/pdf")},
        data={"page_ranges": "2"},
    )

    assert response.status_code == 200
    with pikepdf.open(io.BytesIO(response.content)) as result:
        assert [list(page.MediaBox) for page in result.pages] == [[0, 0, 300, 400], [0, 0, 302, 402]]
        fields = list(result.Root.AcroForm.Fields)
        assert [str(field.T) for field in fields] == ["Field 1", "Field 3"]
        assert [str(field.V) for field in fields] == ["Value 1", "Value 3"]
        assert [field.P.objgen for field in fields] == [page.objgen for page in result.pages]
        assert [len(page.obj.Annots) for page in result.pages] == [1, 1]


def test_delete_pages_preserves_surviving_internal_links_and_outline_targets(client):
    response = client.post(
        "/api/pdf/pages/delete",
        files={"file": ("navigation.pdf", make_pdf_with_internal_navigation(), "application/pdf")},
        data={"page_ranges": "2"},
    )

    assert response.status_code == 200
    with pikepdf.open(io.BytesIO(response.content)) as result:
        assert [list(page.MediaBox) for page in result.pages] == [[0, 0, 300, 400], [0, 0, 302, 402]]
        assert result.pages[1].obj.Annots[0].A.D[0].objgen == result.pages[0].objgen
        with result.open_outline() as outline:
            assert outline.root[0].destination[0].objgen == result.pages[0].objgen


def test_page_management_routes_enforce_engine_page_limit(client, monkeypatch):
    monkeypatch.setattr("officekit.engines.engine_pdf_advanced.AdvancedPdfEngine.MAX_PAGE_MANAGEMENT_PAGES", 2)
    source = make_pdf([(300, 400), (301, 401), (302, 402)])

    delete_response = client.post(
        "/api/pdf/pages/delete",
        files={"file": ("source.pdf", source, "application/pdf")},
        data={"page_ranges": "2"},
    )
    reorder_response = client.post(
        "/api/pdf/pages/reorder",
        files={"file": ("source.pdf", source, "application/pdf")},
        data={"page_order": "3,1,2"},
    )

    assert delete_response.status_code == 422
    assert reorder_response.status_code == 422


@pytest.mark.parametrize(
    ("path", "field", "value"),
    [
        ("/api/pdf/pages/delete", "page_ranges", "2"),
        ("/api/pdf/pages/reorder", "page_order", "3,1,2"),
    ],
)
def test_page_management_routes_return_413_without_partial_output(
    client, monkeypatch, path, field, value
):
    monkeypatch.setattr("officekit.engines.engine_pdf_advanced.AdvancedPdfEngine.MAX_OUTPUT_BYTES", 8)
    response = client.post(
        path,
        files={"file": ("source.pdf", make_pdf([(300, 400), (301, 401), (302, 402)]), "application/pdf")},
        data={field: value},
    )

    assert response.status_code == 413
    assert response.json() == {
        "detail": "The processed PDF exceeds the supported 64 MiB output limit."
    }


@pytest.mark.parametrize("page_ranges", ["", "1-3", "0", "4", "2,2", "3-1"])
def test_delete_pages_route_rejects_invalid_or_all_page_selections(client, page_ranges):
    response = client.post(
        "/api/pdf/pages/delete",
        files={"file": ("source.pdf", make_pdf([(300, 400), (301, 401), (302, 402)]), "application/pdf")},
        data={"page_ranges": page_ranges},
    )

    assert response.status_code == 422
    assert response.json()["detail"] in {
        "The PDF file is invalid or the requested operation is unsupported.",
        "Request contains invalid or unsupported values.",
    }


def test_reorder_pages_route_requires_a_complete_permutation_and_preserves_source(client):
    original = make_pdf([(300, 400), (301, 401), (302, 402)])
    response = client.post(
        "/api/pdf/pages/reorder",
        files={"file": ("source.pdf", original, "application/pdf")},
        data={"page_order": "3,1,2"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "reordered.pdf" in response.headers["content-disposition"]
    with pikepdf.open(io.BytesIO(response.content)) as result:
        assert [list(page.MediaBox) for page in result.pages] == [
            [0, 0, 302, 402], [0, 0, 300, 400], [0, 0, 301, 401]
        ]
    with pikepdf.open(io.BytesIO(original)) as unchanged:
        assert [list(page.MediaBox) for page in unchanged.pages] == [
            [0, 0, 300, 400], [0, 0, 301, 401], [0, 0, 302, 402]
        ]


def test_reorder_pages_route_accepts_complete_identity_range(client):
    response = client.post(
        "/api/pdf/pages/reorder",
        files={"file": ("source.pdf", make_pdf([(300, 400), (301, 401), (302, 402)]), "application/pdf")},
        data={"page_order": "1-3"},
    )

    assert response.status_code == 200
    with pikepdf.open(io.BytesIO(response.content)) as result:
        assert [list(page.MediaBox) for page in result.pages] == [
            [0, 0, 300, 400], [0, 0, 301, 401], [0, 0, 302, 402]
        ]


def test_page_thumbnails_route_returns_ordered_local_images_in_bounded_window(client):
    response = client.post(
        "/api/pdf/page-thumbnails",
        files={"file": ("source.pdf", make_pdf([(300, 400), (301, 401), (302, 402)]), "application/pdf")},
        data={"page_numbers": "3,2"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["page_count"] == 3
    assert [page["page_number"] for page in payload["pages"]] == [3, 2]
    for item in payload["pages"]:
        assert item["width_points"] > 0
        assert item["height_points"] > 0
        assert base64.b64decode(item["data_base64"]).startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize("page_numbers", ["4", "0", "1,1", "1-2", ",1", ",".join(map(str, range(1, 26)))])
def test_page_thumbnails_route_rejects_out_of_range_and_oversized_windows(client, page_numbers):
    response = client.post(
        "/api/pdf/page-thumbnails",
        files={"file": ("source.pdf", make_pdf([(300, 400), (301, 401), (302, 402)]), "application/pdf")},
        data={"page_numbers": page_numbers},
    )

    assert response.status_code == 422
    assert response.json()["detail"] in {
        "The PDF file is invalid or the requested operation is unsupported.",
        "Request contains invalid or unsupported values.",
    }


@pytest.mark.parametrize("method", [AdvancedPdfEngine.delete_pages, AdvancedPdfEngine.reorder_pages])
@pytest.mark.parametrize("pdf_bytes", [None, "not bytes", b""])
def test_page_management_engines_reject_non_bytes_and_empty_input(method, pdf_bytes):
    with pytest.raises(ValueError, match="PDF input must be non-empty bytes"):
        method(pdf_bytes, "1")


@pytest.mark.parametrize("path,field", [
    ("/api/pdf/pages/delete", "page_ranges"),
    ("/api/pdf/pages/reorder", "page_order"),
])
def test_page_management_routes_reject_malformed_pdf_safely(client, path, field):
    response = client.post(
        path,
        files={"file": ("broken.pdf", b"not a PDF", "application/pdf")},
        data={field: "1"},
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "The PDF file is invalid or the requested operation is unsupported."
    }


def test_reorder_pages_route_preserves_internal_links_and_outlines(client):
    response = client.post(
        "/api/pdf/pages/reorder",
        files={"file": ("navigation.pdf", make_pdf_with_internal_navigation(), "application/pdf")},
        data={"page_order": "3,1,2"},
    )

    assert response.status_code == 200
    with pikepdf.open(io.BytesIO(response.content)) as result:
        assert result.docinfo["/Title"] == "Navigation fixture"
        assert [list(page.MediaBox) for page in result.pages] == [
            [0, 0, 302, 402], [0, 0, 300, 400], [0, 0, 301, 401]
        ]
        link = result.pages[0].obj.Annots[0]
        assert link.A.D[0].objgen == result.pages[1].objgen
        with result.open_outline() as outline:
            destination = outline.root[0].destination
            assert destination[0].objgen == result.pages[1].objgen


def test_reorder_pages_preserves_form_fields_and_moves_widget_pages_with_their_content(client):
    response = client.post(
        "/api/pdf/pages/reorder",
        files={"file": ("form.pdf", make_page_form_pdf(), "application/pdf")},
        data={"page_order": "3,1,2"},
    )

    assert response.status_code == 200
    with pikepdf.open(io.BytesIO(response.content)) as result:
        assert [list(page.MediaBox) for page in result.pages] == [
            [0, 0, 302, 402], [0, 0, 300, 400], [0, 0, 301, 401],
        ]
        fields = list(result.Root.AcroForm.Fields)
        assert [str(field.T) for field in fields] == ["Field 1", "Field 2", "Field 3"]
        assert [str(field.V) for field in fields] == ["Value 1", "Value 2", "Value 3"]
        assert [field.P.objgen for field in fields] == [
            result.pages[1].objgen, result.pages[2].objgen, result.pages[0].objgen,
        ]


@pytest.mark.parametrize("page_order", ["", "1,2", "1,2,2", "3-1", "0,1,2", "1,2,4"])
def test_reorder_pages_route_rejects_non_permutations(client, page_order):
    response = client.post(
        "/api/pdf/pages/reorder",
        files={"file": ("source.pdf", make_pdf([(300, 400), (301, 401), (302, 402)]), "application/pdf")},
        data={"page_order": page_order},
    )

    assert response.status_code == 422
    assert response.json()["detail"] in {
        "The PDF file is invalid or the requested operation is unsupported.",
        "Request contains invalid or unsupported values.",
    }


def test_split_groups_route_returns_named_ordered_pdfs_in_a_zip(client):
    source = make_pdf([(300 + index, 400 + index) for index in range(5)])
    response = client.post(
        "/api/pdf/split/groups",
        data={"groups": '[{"name":"cover.pdf","page_ranges":"1,3"},{"name":"appendix.pdf","page_ranges":"5,2"}]'},
        files={"file": ("source.pdf", source, "application/pdf")},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert "split-pages.zip" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        assert bundle.namelist() == ["cover.pdf", "appendix.pdf"]
        with pikepdf.open(io.BytesIO(bundle.read("cover.pdf"))) as cover:
            assert [list(page.MediaBox) for page in cover.pages] == [[0, 0, 300, 400], [0, 0, 302, 402]]
        with pikepdf.open(io.BytesIO(bundle.read("appendix.pdf"))) as appendix:
            assert [list(page.MediaBox) for page in appendix.pages] == [[0, 0, 304, 404], [0, 0, 301, 401]]


@pytest.mark.parametrize("groups", [
    "{}",
    "[]",
    '[{"name":"../unsafe.pdf","page_ranges":"1"},{"name":"other.pdf","page_ranges":"2"}]',
    '[{"name":"same.pdf","page_ranges":"1"},{"name":"SAME.PDF","page_ranges":"2"}]',
    '[{"name":"café.pdf","page_ranges":"1"},{"name":"café.pdf","page_ranges":"2"}]',
    '[{"name":"CON.pdf","page_ranges":"1"},{"name":"other.pdf","page_ranges":"2"}]',
    '[{"name":"safe\u202ename.pdf","page_ranges":"1"},{"name":"other.pdf","page_ranges":"2"}]',
    '[{"name":"one.pdf","page_ranges":"1-2"},{"name":"two.pdf","page_ranges":"2-3"}]',
    '[{"name":"one.pdf","page_ranges":"1-2"},{"name":"two.pdf","page_ranges":"6"}]',
    '[{"name":"one.pdf","page_ranges":"1","extra":true},{"name":"two.pdf","page_ranges":"2"}]',
])
def test_split_groups_route_rejects_unsafe_or_ambiguous_group_manifests(client, groups):
    response = client.post(
        "/api/pdf/split/groups", data={"groups": groups},
        files={"file": ("source.pdf", make_pdf([(300, 400)] * 5), "application/pdf")},
    )
    assert response.status_code == 422
    assert response.json()["detail"]


def test_split_groups_route_rejects_duplicate_json_keys_and_malformed_source(client):
    duplicate_key = client.post(
        "/api/pdf/split/groups",
        data={"groups": '[{"name":"a.pdf","name":"b.pdf","page_ranges":"1"},{"name":"c.pdf","page_ranges":"2"}]'},
        files={"file": ("source.pdf", make_pdf([(300, 400)] * 2), "application/pdf")},
    )
    malformed_pdf = client.post(
        "/api/pdf/split/groups",
        data={"groups": '[{"name":"a.pdf","page_ranges":"1"},{"name":"b.pdf","page_ranges":"2"}]'},
        files={"file": ("source.pdf", b"not a PDF", "application/pdf")},
    )
    assert duplicate_key.status_code == 422
    assert malformed_pdf.status_code == 422
    assert "not a PDF" not in malformed_pdf.text


def test_split_groups_route_stops_before_zip_output_cap_and_returns_no_partial_archive(client):
    source = make_pdf([(300, 400)] * 4)
    groups = '[{"name":"first.pdf","page_ranges":"1,2"},{"name":"second.pdf","page_ranges":"3,4"}]'
    with patch("app.AdvancedPdfEngine.MAX_OUTPUT_BYTES", 1_000):
        response = client.post(
            "/api/pdf/split/groups", data={"groups": groups},
            files={"file": ("source.pdf", source, "application/pdf")},
        )
    assert response.status_code == 413
    assert response.headers["content-type"].startswith("application/json")
    assert not response.content.startswith(b"PK\x03\x04")
    assert response.json()["detail"] == "The processed PDF exceeds the supported 64 MiB output limit."


def test_compress_route_accepts_named_presets_and_reports_actual_size_ratio(client):
    source = make_pdf([(612, 792)] * 3)
    response = client.post(
        "/api/pdf/compress", data={"preset": "balanced"},
        files={"file": ("statement.pdf", source, "application/pdf")},
    )
    invalid_preset = client.post(
        "/api/pdf/compress", data={"preset": "lossy"},
        files={"file": ("statement.pdf", source, "application/pdf")},
    )

    assert response.status_code == 200
    ratio = float(response.headers["x-officekit-output-input-ratio"])
    assert ratio == pytest.approx(len(response.content) / len(source), rel=1e-7)
    with pikepdf.open(io.BytesIO(response.content)) as result:
        assert len(result.pages) == 3
    assert invalid_preset.status_code == 422


def test_metadata_route_removes_info_and_xmp_metadata(client):
    source = make_pdf([(612, 792)], title="Sensitive title")
    response = client.post(
        "/api/pdf/metadata", files={"file": ("private.pdf", source, "application/pdf")}
    )

    assert response.status_code == 200
    assert "private_metadata_removed.pdf" in response.headers["content-disposition"]
    with pikepdf.open(io.BytesIO(response.content)) as result:
        assert "/Title" not in result.docinfo
        assert "/Metadata" not in result.Root


def test_pdf_images_route_renders_every_page_and_returns_readable_png_zip(client):
    pytest.importorskip("pypdfium2")
    from PIL import Image

    source = make_pdf([(144, 216), (216, 144)])
    response = client.post(
        "/api/pdf/images", data={"target_format": "png", "dpi": "72"},
        files={"file": ("sample.pdf", source, "application/pdf")},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["x-officekit-page-count"] == "2"
    assert "sample_pages.zip" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        assert bundle.namelist() == ["page-001.png", "page-002.png"]
        with Image.open(io.BytesIO(bundle.read("page-001.png"))) as first:
            assert first.size == (144, 216)
            assert first.format == "PNG"
        with Image.open(io.BytesIO(bundle.read("page-002.png"))) as second:
            assert second.size == (216, 144)
            assert second.format == "PNG"


def test_pdf_images_route_supports_jpeg_and_rejects_invalid_options(client):
    pytest.importorskip("pypdfium2")
    from PIL import Image

    source = make_pdf([(72, 72)])
    response = client.post(
        "/api/pdf/images", data={"target_format": "jpg", "dpi": "144", "quality": "82"},
        files={"file": ("sample.pdf", source, "application/pdf")},
    )
    unsupported = client.post(
        "/api/pdf/images", data={"target_format": "gif"},
        files={"file": ("sample.pdf", source, "application/pdf")},
    )
    invalid_dpi = client.post(
        "/api/pdf/images", data={"target_format": "png", "dpi": "301"},
        files={"file": ("sample.pdf", source, "application/pdf")},
    )

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        assert bundle.namelist() == ["page-001.jpg"]
        with Image.open(io.BytesIO(bundle.read("page-001.jpg"))) as image:
            assert image.size == (144, 144)
            assert image.format == "JPEG"
            assert image.mode == "RGB"
    assert unsupported.status_code == 422
    assert invalid_dpi.status_code == 422


def test_pdf_images_route_rejects_render_bombs_page_overflow_and_encryption(client):
    # pikepdf caps blank-page dimensions at 14,400 points; at 72 DPI this
    # remains large enough to exceed the renderer's per-page pixel limit.
    oversized_page = make_pdf([(14_400, 14_400)])
    too_many_pages = make_pdf([(72, 72)] * 101)
    encrypted = make_pdf(
        [(72, 72)],
        encryption=pikepdf.Encryption(owner="owner-secret", user="user-secret", R=6),
    )
    responses = [
        client.post("/api/pdf/images", data={"dpi": "72"}, files={"file": ("large.pdf", oversized_page, "application/pdf")}),
        client.post("/api/pdf/images", files={"file": ("many.pdf", too_many_pages, "application/pdf")}),
        client.post("/api/pdf/images", files={"file": ("locked.pdf", encrypted, "application/pdf")}),
    ]

    assert all(response.status_code == 422 for response in responses)
    assert all("owner-secret" not in response.text and "user-secret" not in response.text for response in responses)


def test_pdf_routes_reject_empty_and_invalid_documents_safely(client):
    for route, data in (("/api/pdf/split", {"page_ranges": "1"}),
                        ("/api/pdf/compress", {"preset": "balanced"}),
                        ("/api/pdf/metadata", {}),
                        ("/api/pdf/images", {"target_format": "png"})):
        response = client.post(
            route, data=data,
            files={"file": ("bad.pdf", b"", "application/pdf")},
        )
        assert response.status_code == 422
        assert "detail" in response.json()


def test_pdf_routes_map_password_protected_sources_without_password_to_safe_422(client):
    locked = make_pdf(
        [(300, 400)],
        encryption=pikepdf.Encryption(owner="owner-secret", user="user-secret", R=6),
    )
    response = client.post(
        "/api/pdf/metadata", files={"file": ("locked.pdf", locked, "application/pdf")}
    )

    assert response.status_code == 422
    assert "owner-secret" not in response.text
    assert "user-secret" not in response.text


def test_protect_and_unlock_routes_return_reopenable_pdf_attachments_and_preserve_structure(client):
    source = make_pdf([(300, 400), (301, 401)], title="Private statement")
    protected = client.post(
        "/api/pdf/protect",
        data={"password": "safe-passphrase-42"},
        files={"file": ("source.pdf", source, "application/pdf")},
    )

    assert protected.status_code == 200
    assert protected.headers["content-type"].startswith("application/pdf")
    assert "source_protected.pdf" in protected.headers["content-disposition"]
    with pikepdf.open(io.BytesIO(protected.content), password="safe-passphrase-42") as encrypted:
        assert encrypted.is_encrypted
        assert len(encrypted.pages) == 2
        assert [tuple(float(value) for value in page.MediaBox[2:]) for page in encrypted.pages] == [
            (300.0, 400.0), (301.0, 401.0),
        ]
        assert str(encrypted.docinfo["/Title"]) == "Private statement"

    wrong_password = client.post(
        "/api/pdf/unlock",
        data={"password": "incorrect"},
        files={"file": ("source_protected.pdf", protected.content, "application/pdf")},
    )
    assert wrong_password.status_code == 400
    assert "Incorrect password" in wrong_password.json()["detail"]
    assert "safe-passphrase-42" not in wrong_password.text
    assert not wrong_password.content.startswith(b"%PDF-")

    unlocked = client.post(
        "/api/pdf/unlock",
        data={"password": "safe-passphrase-42"},
        files={"file": ("source_protected.pdf", protected.content, "application/pdf")},
    )

    assert unlocked.status_code == 200
    assert unlocked.headers["content-type"].startswith("application/pdf")
    assert "source_protected_unlocked.pdf" in unlocked.headers["content-disposition"]
    with pikepdf.open(io.BytesIO(unlocked.content)) as decrypted:
        assert not decrypted.is_encrypted
        assert len(decrypted.pages) == 2
        assert [tuple(float(value) for value in page.MediaBox[2:]) for page in decrypted.pages] == [
            (300.0, 400.0), (301.0, 401.0),
        ]
        assert str(decrypted.docinfo["/Title"]) == "Private statement"


def test_protection_accepts_the_shared_browser_workbench_pdf_fixture(client):
    from pathlib import Path

    source = Path(__file__).parent / "fixtures" / "pdf-protect-source.pdf"
    original = source.read_bytes()
    protected = client.post(
        "/api/pdf/protect",
        data={"password": "correct horse battery"},
        files={"file": ("source.pdf", original, "application/pdf")},
    )
    assert protected.status_code == 200
    with pikepdf.open(io.BytesIO(protected.content), password="correct horse battery") as document:
        assert document.is_encrypted
        assert len(document.pages) == 1
    assert source.read_bytes() == original


def test_protection_rejects_passwords_beyond_pdf_revision_six_utf8_limit(client):
    source = make_pdf([(300, 400)])
    maximum_password = "😀" * 31 + "abc"  # 124 + 3 UTF-8 bytes
    assert len(maximum_password.encode("utf-8")) == 127

    accepted = client.post(
        "/api/pdf/protect",
        data={"password": maximum_password},
        files={"file": ("source.pdf", source, "application/pdf")},
    )
    assert accepted.status_code == 200
    with pikepdf.open(io.BytesIO(accepted.content), password=maximum_password) as encrypted:
        assert encrypted.is_encrypted

    too_long = maximum_password + "😀"
    assert len(too_long.encode("utf-8")) == 131
    rejected = client.post(
        "/api/pdf/protect",
        data={"password": too_long},
        files={"file": ("source.pdf", source, "application/pdf")},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "Password must be non-empty and within the supported size limit."

    rejected_unlock = client.post(
        "/api/pdf/unlock",
        data={"password": too_long},
        files={"file": ("locked.pdf", accepted.content, "application/pdf")},
    )
    assert rejected_unlock.status_code == 422
    assert rejected_unlock.json()["detail"] == "Password must be non-empty and within the supported size limit."

    normalization_expansion = "ﷺ" * 16
    assert len(normalization_expansion.encode("utf-8")) <= 127
    assert len(unicodedata.normalize("NFKC", normalization_expansion).encode("utf-8")) > 127
    rejected_expansion = client.post(
        "/api/pdf/protect",
        data={"password": normalization_expansion},
        files={"file": ("source.pdf", source, "application/pdf")},
    )
    assert rejected_expansion.status_code == 422
    assert rejected_expansion.json()["detail"] == "Password must be non-empty and within the supported size limit."


def test_protect_and_unlock_routes_reject_generated_pdf_over_output_limit(client, monkeypatch):
    from officekit.engines.engine_pdf_security import PdfSecurityEngine

    plain = make_pdf([(300, 400)])
    encrypted = make_pdf(
        [(300, 400)], encryption=pikepdf.Encryption(owner="owner-secret", user="user-secret", R=6)
    )
    monkeypatch.setattr(PdfSecurityEngine, "MAX_OUTPUT_BYTES", 32, raising=False)

    protected = client.post(
        "/api/pdf/protect", data={"password": "secret"}, files={"file": ("source.pdf", plain, "application/pdf")}
    )
    unlocked = client.post(
        "/api/pdf/unlock", data={"password": "user-secret"}, files={"file": ("source.pdf", encrypted, "application/pdf")}
    )

    for response in (protected, unlocked):
        assert response.status_code == 413
        assert response.json()["detail"] == "The processed PDF exceeds the supported 64 MiB output limit."


def test_merge_split_compress_and_metadata_routes_bound_generated_pdf_outputs(client, monkeypatch):
    from officekit.engines.engine_pdf_advanced import AdvancedPdfEngine

    source = make_pdf([(300, 400), (500, 600)], title="Private source")
    monkeypatch.setattr(AdvancedPdfEngine, "MAX_OUTPUT_BYTES", 32, raising=False)
    responses = (
        client.post(
            "/api/pdf/merge",
            files=[("files", ("one.pdf", source, "application/pdf")), ("files", ("two.pdf", source, "application/pdf"))],
        ),
        client.post(
            "/api/pdf/split", data={"page_ranges": "1-2"}, files={"file": ("source.pdf", source, "application/pdf")}
        ),
        client.post(
            "/api/pdf/compress", data={"preset": "balanced"}, files={"file": ("source.pdf", source, "application/pdf")}
        ),
        client.post("/api/pdf/metadata", files={"file": ("source.pdf", source, "application/pdf")}),
    )

    for response in responses:
        assert response.status_code == 413
        assert response.json()["detail"] == "The processed PDF exceeds the supported 64 MiB output limit."


def test_merge_rejects_more_than_twenty_files_before_processing(client):
    files = [("files", (f"{index}.pdf", b"invalid", "application/pdf")) for index in range(21)]
    response = client.post("/api/pdf/merge", files=files)
    assert response.status_code == 422


def test_page_counts_route_preserves_file_order_and_counts_pages(client):
    response = client.post(
        "/api/pdf/page-counts",
        files=[
            ("files", ("first.pdf", make_pdf([(300, 400), (500, 600)]), "application/pdf")),
            ("files", ("second.pdf", make_pdf([(700, 800)]), "application/pdf")),
        ],
    )

    assert response.status_code == 200
    assert response.json() == {
        "files": [
            {"index": 0, "page_count": 2, "status": "ready"},
            {"index": 1, "page_count": 1, "status": "ready"},
        ],
        "total_pages": 3,
        "ready_count": 2,
        "unreadable_count": 0,
    }


def test_page_counts_route_reports_unreadable_files_without_leaking_names(client):
    encrypted = make_pdf(
        [(300, 400)], encryption=pikepdf.Encryption(owner="owner-secret", user="user-secret", R=6)
    )
    response = client.post(
        "/api/pdf/page-counts",
        files=[
            ("files", ("good.pdf", make_pdf([(300, 400)]), "application/pdf")),
            ("files", ("private-account-secret.pdf", b"not a pdf", "application/pdf")),
            ("files", ("empty.pdf", b"", "application/pdf")),
            ("files", ("encrypted.pdf", encrypted, "application/pdf")),
        ],
    )

    assert response.status_code == 200
    assert response.json() == {
        "files": [
            {"index": 0, "page_count": 1, "status": "ready"},
            {"index": 1, "page_count": None, "status": "unreadable"},
            {"index": 2, "page_count": None, "status": "unreadable"},
            {"index": 3, "page_count": None, "status": "unreadable"},
        ],
        "total_pages": 1,
        "ready_count": 1,
        "unreadable_count": 3,
    }
    assert "private-account-secret" not in response.text


def test_page_counts_route_rejects_combined_input_overflow(client, monkeypatch):
    from app import MAX_API_UPLOAD_BYTES

    source = make_pdf([(300, 400)])
    monkeypatch.setattr("app.MAX_API_UPLOAD_BYTES", len(source) + 1)
    response = client.post(
        "/api/pdf/page-counts",
        files=[
            ("files", ("first.pdf", source, "application/pdf")),
            ("files", ("second.pdf", source, "application/pdf")),
        ],
    )

    assert len(source) < MAX_API_UPLOAD_BYTES
    assert response.status_code == 413
    assert response.json()["detail"] == "Combined PDF inputs exceed the 64 MiB processing limit."


def test_page_counts_route_requires_one_to_twenty_files(client):
    no_files = client.post("/api/pdf/page-counts")
    too_many = client.post(
        "/api/pdf/page-counts",
        files=[("files", (f"{index}.pdf", b"invalid", "application/pdf")) for index in range(21)],
    )

    assert no_files.status_code == 422
    assert too_many.status_code == 422
