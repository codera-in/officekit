"""HTTP integration tests for selected-file workspace and archive routes.

Run with the project's pinned requirements installed:
`python -m unittest tests.test_workspace_api -v`.
"""

import csv
import io
import hashlib
import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError
from PIL import Image, ImageDraw, ImageEnhance

import app as officekit_api
from officekit.engines.engine_workspaces import FileWorkspaceStore
from officekit.engines.engine_similar_images import SimilarImageDependencyError


def zip_bytes(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return buffer.getvalue()


def jpeg_bytes(image, quality=92):
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


class WorkspaceApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.original_store = officekit_api.workspace_store
        officekit_api.workspace_store = FileWorkspaceStore(root=self.temporary.name)
        self.client = TestClient(officekit_api.app)

    def tearDown(self):
        officekit_api.workspace_store.close()
        officekit_api.workspace_store = self.original_store
        self.temporary.cleanup()

    def test_selected_zip_flows_through_extract_download_and_clear(self):
        archive = zip_bytes([("docs/readme.txt", b"OfficeKit local copy")])
        created = self.client.post(
            "/api/workspaces",
            files=[("files", ("project.zip", archive, "application/zip"))],
            headers={"Origin": "tauri://localhost"},
        )
        self.assertEqual(created.status_code, 201)
        workspace_id = created.json()["workspace_id"]
        self.assertEqual(created.json()["files"], [{"name": "project.zip", "size_bytes": len(archive)}])

        extracted = self.client.post(
            f"/api/workspaces/{workspace_id}/extractions",
            json={"archive_name": "project.zip", "output_name": "extracted"},
            headers={"Origin": "tauri://localhost"},
        )
        self.assertEqual(extracted.status_code, 200)
        artifact_id = extracted.json()["artifact_id"]

        downloaded = self.client.get(
            f"/api/workspaces/{workspace_id}/artifacts/{artifact_id}",
            headers={"Origin": "tauri://localhost"},
        )
        self.assertEqual(downloaded.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(downloaded.content)) as bundle:
            self.assertEqual(bundle.read("extracted/docs/readme.txt"), b"OfficeKit local copy")

        deleted = self.client.delete(
            f"/api/workspaces/{workspace_id}", headers={"Origin": "tauri://localhost"}
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get(f"/api/workspaces/{workspace_id}").status_code, 404)

    def test_split_and_join_api_round_trip_binary_files_across_workspaces(self):
        original = bytes(range(256)) * 3 + b"\x00\xff"
        created = self.client.post(
            "/api/workspaces",
            files=[("files", ("archive.bin", original, "application/octet-stream"))],
            headers={"Origin": "tauri://localhost"},
        )
        self.assertEqual(created.status_code, 201)
        source_workspace = created.json()["workspace_id"]

        split = self.client.post(
            f"/api/workspaces/{source_workspace}/splits",
            json={"filename": "archive.bin", "chunk_size_bytes": 128},
            headers={"Origin": "tauri://localhost"},
        )
        self.assertEqual(split.status_code, 201, split.text)
        self.assertEqual(split.json()["chunk_count"], 7)
        self.assertEqual(split.json()["sha256"], hashlib.sha256(original).hexdigest())
        split_download = self.client.get(
            f"/api/workspaces/{source_workspace}/artifacts/{split.json()['artifact_id']}",
            headers={"Origin": "tauri://localhost"},
        )
        self.assertEqual(split_download.status_code, 200)

        join_workspace = self.client.post(
            "/api/workspaces",
            files=[("files", ("parts.zip", split_download.content, "application/zip"))],
            headers={"Origin": "tauri://localhost"},
        ).json()["workspace_id"]
        joined = self.client.post(
            f"/api/workspaces/{join_workspace}/joins",
            json={"archive_name": "parts.zip", "output_name": "restored.bin"},
            headers={"Origin": "tauri://localhost"},
        )
        self.assertEqual(joined.status_code, 201, joined.text)
        self.assertEqual(joined.json()["total_bytes"], len(original))
        self.assertEqual(joined.json()["sha256"], hashlib.sha256(original).hexdigest())
        joined_download = self.client.get(
            f"/api/workspaces/{join_workspace}/artifacts/{joined.json()['artifact_id']}",
            headers={"Origin": "tauri://localhost"},
        )
        with zipfile.ZipFile(io.BytesIO(joined_download.content)) as bundle:
            self.assertEqual(bundle.read("joined/restored.bin"), original)

        for payload in (
            {"filename": "archive.bin", "chunk_size_bytes": 0},
            {"filename": "archive.bin", "chunk_size_bytes": True},
            {"filename": "archive.bin", "chunk_size_bytes": 128, "path": "/tmp/input"},
        ):
            with self.subTest(payload=payload):
                response = self.client.post(
                    f"/api/workspaces/{source_workspace}/splits",
                    json=payload,
                    headers={"Origin": "tauri://localhost"},
                )
                self.assertEqual(response.status_code, 422)
        missing_archive = self.client.post(
            f"/api/workspaces/{join_workspace}/joins",
            json={"archive_name": "missing.zip", "output_name": "restored.bin"},
            headers={"Origin": "tauri://localhost"},
        )
        self.assertEqual(missing_archive.status_code, 404)

    def test_untrusted_browser_origin_cannot_create_a_workspace(self):
        response = self.client.post(
            "/api/workspaces",
            files=[("files", ("project.zip", zip_bytes([]), "application/zip"))],
            headers={"Origin": "https://attacker.example"},
        )
        self.assertEqual(response.status_code, 403)

    def test_zip_slip_is_rejected_without_a_downloadable_artifact(self):
        archive = zip_bytes([("../../escape.txt", b"outside")])
        created = self.client.post("/api/workspaces", files=[("files", ("evil.zip", archive))])
        workspace_id = created.json()["workspace_id"]

        response = self.client.post(
            f"/api/workspaces/{workspace_id}/extractions",
            json={"archive_name": "evil.zip", "output_name": "out"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertFalse(os.path.exists(os.path.join(self.temporary.name, "escape.txt")))

    def test_unknown_artifact_and_invalid_request_are_rejected(self):
        created = self.client.post("/api/workspaces", files=[("files", ("a.txt", b"a"))])
        workspace_id = created.json()["workspace_id"]

        missing = self.client.get(f"/api/workspaces/{workspace_id}/artifacts/{'0' * 32}")
        invalid = self.client.post(f"/api/workspaces/{workspace_id}/extractions", json={})

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(invalid.status_code, 422)

    def test_selected_files_can_be_previewed_renamed_downloaded_and_cleared(self):
        created = self.client.post(
            "/api/workspaces",
            files=[
                ("files", ("receipts/jan report.csv", b"January")),
                ("files", ("receipts/feb report.csv", b"February")),
            ],
            headers={"Origin": "tauri://localhost"},
        )
        workspace_id = created.json()["workspace_id"]
        payload = {
            "filenames": ["receipts/jan report.csv", "receipts/feb report.csv"],
            "pattern_type": "sequence",
            "prefix": "receipt_",
            "start_num": 1,
            "digits": 2,
        }

        preview = self.client.post(
            f"/api/workspaces/{workspace_id}/rename-previews",
            json=payload,
            headers={"Origin": "tauri://localhost"},
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual([item["target"] for item in preview.json()["files"]], [
            "receipts/receipt_01.csv", "receipts/receipt_02.csv"
        ])

        created_artifact = self.client.post(
            f"/api/workspaces/{workspace_id}/renamed-artifacts",
            json=payload,
            headers={"Origin": "tauri://localhost"},
        )
        self.assertEqual(created_artifact.status_code, 201)
        artifact_id = created_artifact.json()["artifact_id"]
        downloaded = self.client.get(
            f"/api/workspaces/{workspace_id}/artifacts/{artifact_id}",
            headers={"Origin": "tauri://localhost"},
        )
        self.assertEqual(downloaded.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(downloaded.content)) as bundle:
            self.assertEqual(bundle.read("renamed/receipts/receipt_01.csv"), b"January")
            self.assertEqual(bundle.read("renamed/receipts/receipt_02.csv"), b"February")

        originals = self.client.get(
            f"/api/workspaces/{workspace_id}", headers={"Origin": "tauri://localhost"}
        )
        self.assertEqual(
            [item["name"] for item in originals.json()["files"]],
            sorted(payload["filenames"], key=str.casefold),
        )
        cleared = self.client.delete(
            f"/api/workspaces/{workspace_id}", headers={"Origin": "tauri://localhost"}
        )
        self.assertEqual(cleared.status_code, 204)

    def test_rename_api_rejects_collisions_invalid_paths_and_untrusted_origins(self):
        created = self.client.post(
            "/api/workspaces",
            files=[("files", ("source.txt", b"source")), ("files", ("target.txt", b"target"))],
        )
        workspace_id = created.json()["workspace_id"]
        payload = {
            "filenames": ["source.txt"],
            "pattern_type": "replace",
            "find_text": "source",
            "replace_text": "target",
        }

        collision = self.client.post(
            f"/api/workspaces/{workspace_id}/rename-previews", json=payload
        )
        invalid = self.client.post(
            f"/api/workspaces/{workspace_id}/rename-previews",
            json={**payload, "filenames": ["../outside.txt"]},
        )
        invalid_pattern = self.client.post(
            f"/api/workspaces/{workspace_id}/rename-previews",
            json={**payload, "pattern_type": "regex"},
        )
        invalid_sequence = self.client.post(
            f"/api/workspaces/{workspace_id}/rename-previews",
            json={**payload, "digits": 0},
        )
        untrusted = self.client.post(
            f"/api/workspaces/{workspace_id}/renamed-artifacts",
            json=payload,
            headers={"Origin": "https://attacker.example"},
        )

        self.assertEqual(collision.status_code, 422)
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid_pattern.status_code, 422)
        self.assertEqual(invalid_sequence.status_code, 422)
        self.assertEqual(untrusted.status_code, 403)

    def test_duplicate_report_scans_only_imported_files_and_returns_relative_names(self):
        created = self.client.post(
            "/api/workspaces",
            files=[
                ("files", ("nested/source.csv", b"identical")),
                ("files", ("nested/copy.csv", b"identical")),
                ("files", ("empty-a.bin", b"")),
                ("files", ("empty-b.bin", b"")),
            ],
            headers={"Origin": "tauri://localhost"},
        )
        workspace_id = created.json()["workspace_id"]

        report = self.client.post(
            f"/api/workspaces/{workspace_id}/duplicate-reports",
            json={"max_entries": 10_000},
            headers={"Origin": "tauri://localhost"},
        )

        self.assertEqual(report.status_code, 200)
        self.assertTrue(report.json()["complete"])
        groups = {tuple(item["files"]): item for item in report.json()["groups"]}
        self.assertIn(("empty-a.bin", "empty-b.bin"), groups)
        self.assertIn(("nested/copy.csv", "nested/source.csv"), groups)
        self.assertNotIn(self.temporary.name, report.text)

        invalid = self.client.post(
            f"/api/workspaces/{workspace_id}/duplicate-reports", json={"max_entries": 0}
        )
        self.assertEqual(invalid.status_code, 422)

    def test_storage_report_scans_selected_copies_and_rejects_invalid_limits(self):
        outside_file = os.path.join(self.temporary.name, "outside-secret.txt")
        with open(outside_file, "wb") as file:
            file.write(b"must not be included")
        created = self.client.post(
            "/api/workspaces",
            files=[
                ("files", ("docs/manual.pdf", b"x" * 12)),
                ("files", ("manual.pdf", b"y" * 5)),
            ],
            headers={"Origin": "tauri://localhost"},
        )
        workspace_id = created.json()["workspace_id"]

        report = self.client.post(
            f"/api/workspaces/{workspace_id}/storage-reports",
            json={"top_n": 10},
            headers={"Origin": "tauri://localhost"},
        )
        path_attempt = self.client.post(
            f"/api/workspaces/{workspace_id}/storage-reports",
            json={"top_n": 10, "path": self.temporary.name},
        )

        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.json()["total_files"], 2)
        self.assertEqual(report.json()["total_size_bytes"], 17)
        self.assertEqual(report.json()["largest_files"][0]["name"], "docs/manual.pdf")
        self.assertEqual(report.json()["largest_folders"], [
            {"name": "docs", "file_count": 1, "size_bytes": 12},
        ])
        self.assertNotIn("outside-secret.txt", report.text)
        self.assertNotIn(self.temporary.name, report.text)
        self.assertEqual(path_attempt.status_code, 422)

        invalid = self.client.post(
            f"/api/workspaces/{workspace_id}/storage-reports", json={"top_n": 1001}
        )
        self.assertEqual(invalid.status_code, 422)

    def test_similar_image_report_is_workspace_scoped_and_rejects_untrusted_options(self):
        created = self.client.post(
            "/api/workspaces",
            files=[
                ("files", ("burst/a.jpg", b"a")),
                ("files", ("burst/b.jpg", b"b")),
                ("files", ("secret.png", b"not selected")),
            ],
            headers={"Origin": "tauri://localhost"},
        )
        workspace_id = created.json()["workspace_id"]
        report_result = {
            "pairs": [{"left": "burst/a.jpg", "right": "burst/b.jpg", "distance": 3}],
            "groups": [{"files": ["burst/a.jpg", "burst/b.jpg"]}],
            "scanned_images": 2,
            "skipped_files": [],
            "errors": [],
            "complete": True,
            "method": "dct-perceptual-hash",
            "frames_per_file": 1,
        }
        with patch("officekit.engines.engine_similar_images.SimilarImageEngine.scan_files", return_value=report_result) as scan:
            report = self.client.post(
                f"/api/workspaces/{workspace_id}/similar-image-reports",
                json={"filenames": ["burst/a.jpg", "burst/b.jpg"], "threshold": 8},
                headers={"Origin": "tauri://localhost"},
            )
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.json(), report_result)
        self.assertEqual({name for name, _ in scan.call_args.args[0]}, {"burst/a.jpg", "burst/b.jpg"})
        self.assertNotIn(self.temporary.name, report.text)

        arbitrary_path = self.client.post(
            f"/api/workspaces/{workspace_id}/similar-image-reports",
            json={"filenames": ["burst/a.jpg"], "path": self.temporary.name},
        )
        too_many = self.client.post(
            f"/api/workspaces/{workspace_id}/similar-image-reports",
            json={"filenames": [f"{index}.jpg" for index in range(501)]},
        )
        invalid_threshold = self.client.post(
            f"/api/workspaces/{workspace_id}/similar-image-reports",
            json={"filenames": ["burst/a.jpg"], "threshold": 65},
        )
        boolean_threshold = self.client.post(
            f"/api/workspaces/{workspace_id}/similar-image-reports",
            json={"filenames": ["burst/a.jpg"], "threshold": True},
        )
        self.assertEqual(arbitrary_path.status_code, 422)
        self.assertEqual(too_many.status_code, 422)
        self.assertEqual(invalid_threshold.status_code, 422)
        self.assertEqual(boolean_threshold.status_code, 422)

    def test_similar_image_route_explains_when_image_decoder_is_unavailable(self):
        created = self.client.post(
            "/api/workspaces", files=[("files", ("one.jpg", b"image"))]
        )
        workspace_id = created.json()["workspace_id"]
        with patch("officekit.engines.engine_similar_images.SimilarImageEngine.scan_files", side_effect=SimilarImageDependencyError("private details")):
            result = self.client.post(
                f"/api/workspaces/{workspace_id}/similar-image-reports",
                json={"filenames": ["one.jpg"]},
            )
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("private details", result.text)

    def test_similar_image_http_flow_groups_photo_like_jpegs_from_selected_workspace_copies(self):
        scene = Image.new("RGB", (320, 220), (93, 146, 185))
        draw = ImageDraw.Draw(scene)
        draw.rectangle((0, 145, 319, 219), fill=(91, 112, 72))
        draw.ellipse((234, 28, 279, 73), fill=(247, 211, 121))
        for index, height in enumerate((78, 112, 90)):
            left = 24 + index * 91
            roof = 145 - height
            draw.polygon(((left - 5, roof + 16), (left + 32, roof), (left + 70, roof + 16)), fill=(112, 67, 53))
            draw.rectangle((left, roof + 16, left + 64, 145), fill=(201, 178, 144))
            draw.rectangle((left + 12, roof + 30, left + 26, roof + 50), fill=(52, 92, 110))
            draw.rectangle((left + 40, roof + 30, left + 54, roof + 50), fill=(52, 92, 110))
        exposed = ImageEnhance.Brightness(scene).enhance(1.1)
        cropped = scene.crop((6, 5, 314, 215)).resize(scene.size, Image.Resampling.LANCZOS)
        unrelated = Image.new("RGB", (320, 220), (31, 36, 73))
        unrelated_draw = ImageDraw.Draw(unrelated)
        unrelated_draw.rectangle((0, 130, 319, 219), fill=(38, 129, 146))
        for left in range(12, 320, 48):
            unrelated_draw.ellipse((left, 25, left + 30, 55), fill=(215, 69, 120))

        uploaded = [
            ("burst/base.jpg", jpeg_bytes(scene, 95)),
            ("burst/exposure.jpg", jpeg_bytes(exposed, 83)),
            ("burst/crop.jpg", jpeg_bytes(cropped, 88)),
            ("other/scene.jpg", jpeg_bytes(unrelated, 90)),
        ]
        created = self.client.post(
            "/api/workspaces",
            files=[("files", (name, content, "image/jpeg")) for name, content in uploaded],
            headers={"Origin": "tauri://localhost"},
        )
        self.assertEqual(created.status_code, 201)
        workspace_id = created.json()["workspace_id"]

        report = self.client.post(
            f"/api/workspaces/{workspace_id}/similar-image-reports",
            json={"filenames": [name for name, _ in uploaded], "threshold": 8},
            headers={"Origin": "tauri://localhost"},
        )

        self.assertEqual(report.status_code, 200, report.text)
        self.assertTrue(report.json()["complete"])
        self.assertEqual(report.json()["scanned_images"], 4)
        self.assertEqual(report.json()["groups"], [{
            "files": ["burst/base.jpg", "burst/crop.jpg", "burst/exposure.jpg"]
        }])
        self.assertNotIn("other/scene.jpg", report.text)
        self.assertNotIn(self.temporary.name, report.text)

    def test_similar_image_http_report_marks_aggregate_work_limit_as_incomplete(self):
        uploaded = []
        for name, size in (("first.png", (32, 32)), ("over-budget.png", (32, 32)), ("small.png", (16, 16))):
            image = Image.new("RGB", size, "white")
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            uploaded.append((name, buffer.getvalue()))
            image.close()
        created = self.client.post(
            "/api/workspaces",
            files=[("files", (name, content, "image/png")) for name, content in uploaded],
            headers={"Origin": "tauri://localhost"},
        )
        workspace_id = created.json()["workspace_id"]

        with patch("officekit.engines.engine_similar_images.SimilarImageEngine.MAX_TOTAL_PIXELS", 1_300):
            response = self.client.post(
                f"/api/workspaces/{workspace_id}/similar-image-reports",
                json={"filenames": [name for name, _ in uploaded]},
                headers={"Origin": "tauri://localhost"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["scanned_images"], 2)
        self.assertFalse(result["complete"])
        self.assertEqual(result["errors"], [{
            "name": "over-budget.png",
            "message": "Aggregate image scan work limit reached; select fewer or smaller images",
        }])
        self.assertNotIn(self.temporary.name, response.text)

    def test_similar_image_response_dto_accepts_full_request_bound_and_rejects_one_over(self):
        response = officekit_api.SimilarImageGroupResponse.model_validate({
            "files": [f"photo-{index}.jpg" for index in range(500)]
        })
        self.assertEqual(len(response.files), 500)
        with self.assertRaises(ValidationError):
            officekit_api.SimilarImageGroupResponse.model_validate({
                "files": [f"photo-{index}.jpg" for index in range(501)]
            })

    def test_workspace_hash_report_returns_bounded_digests_and_rejects_invalid_requests(self):
        created = self.client.post(
            "/api/workspaces",
            files=[
                ("files", ("nested/a.txt", b"alpha")),
                ("files", ("empty.bin", b"")),
                ("files", ("unselected.txt", b"do not expose")),
            ],
            headers={"Origin": "tauri://localhost"},
        )
        workspace_id = created.json()["workspace_id"]
        request_headers = {"Origin": "tauri://localhost"}

        default_hash = self.client.post(
            f"/api/workspaces/{workspace_id}/hash-reports",
            json={"filenames": ["empty.bin", "nested/a.txt"]},
            headers=request_headers,
        )
        sha512_hash = self.client.post(
            f"/api/workspaces/{workspace_id}/hash-reports",
            json={"filenames": ["nested/a.txt"], "algorithm": "sha512"},
            headers=request_headers,
        )

        self.assertEqual(default_hash.status_code, 200)
        self.assertEqual(default_hash.json()["algorithm"], "sha256")
        self.assertEqual(default_hash.json()["total_files"], 2)
        self.assertEqual(default_hash.json()["total_bytes"], 5)
        self.assertEqual(default_hash.json()["files"][0]["digest"], hashlib.sha256(b"").hexdigest())
        self.assertEqual(default_hash.json()["files"][1]["digest"], hashlib.sha256(b"alpha").hexdigest())
        self.assertEqual(sha512_hash.status_code, 200)
        self.assertEqual(sha512_hash.json()["files"][0]["digest"], hashlib.sha512(b"alpha").hexdigest())
        self.assertNotIn("unselected.txt", default_hash.text)
        self.assertNotIn(self.temporary.name, default_hash.text)

        invalid_payloads = (
            ({"filenames": []}, 422),
            ({"filenames": ["nested/a.txt", "nested/a.txt"]}, 422),
            ({"filenames": ["missing.txt"]}, 404),
            ({"filenames": ["../outside.txt"]}, 422),
            ({"filenames": ["nested/a.txt"], "algorithm": "md5"}, 422),
            ({"filenames": ["nested/a.txt"], "path": self.temporary.name}, 422),
            ({"filenames": [f"{index}.txt" for index in range(1001)]}, 422),
        )
        for payload, expected_status in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client.post(
                    f"/api/workspaces/{workspace_id}/hash-reports",
                    json=payload,
                    headers=request_headers,
                )
                self.assertEqual(response.status_code, expected_status)

        missing_workspace = self.client.post(
            f"/api/workspaces/{'0' * 32}/hash-reports",
            json={"filenames": ["nested/a.txt"]},
            headers=request_headers,
        )
        self.assertEqual(missing_workspace.status_code, 404)

    def test_file_type_report_reads_selected_content_and_flags_extension_mismatches(self):
        created = self.client.post(
            "/api/workspaces",
            files=[
                ("files", ("renamed.jpg", b"\x89PNG\r\n\x1a\nimage")),
                ("files", ("report.pdf", b"%PDF-1.7\nbody")),
                ("files", ("empty.bin", b"")),
                ("files", ("unselected.txt", b"do not expose")),
            ],
            headers={"Origin": "tauri://localhost"},
        )
        workspace_id = created.json()["workspace_id"]
        report = self.client.post(
            f"/api/workspaces/{workspace_id}/file-type-reports",
            json={"filenames": ["renamed.jpg", "report.pdf", "empty.bin"]},
            headers={"Origin": "tauri://localhost"},
        )

        self.assertEqual(report.status_code, 200)
        payload = report.json()
        self.assertEqual(payload["total_files"], 3)
        self.assertTrue(payload["complete"])
        records = {record["name"]: record for record in payload["files"]}
        self.assertEqual(records["renamed.jpg"]["detected_type"], "PNG")
        self.assertFalse(records["renamed.jpg"]["extension_matches"])
        self.assertEqual(records["report.pdf"]["mime_type"], "application/pdf")
        self.assertEqual(records["empty.bin"]["detected_type"], "Empty file")
        self.assertNotIn("unselected.txt", report.text)
        self.assertNotIn(self.temporary.name, report.text)

        invalid = (
            {"filenames": []},
            {"filenames": ["renamed.jpg", "renamed.jpg"]},
            {"filenames": ["../outside.jpg"]},
            {"filenames": ["missing.jpg"]},
            {"filenames": [1]},
            {"filenames": ["renamed.jpg"], "path": self.temporary.name},
            {"filenames": [f"{index}.txt" for index in range(1001)]},
        )
        for request in invalid:
            with self.subTest(request=request):
                response = self.client.post(
                    f"/api/workspaces/{workspace_id}/file-type-reports",
                    json=request,
                    headers={"Origin": "tauri://localhost"},
                )
                self.assertEqual(response.status_code, 422 if "missing.jpg" not in request.get("filenames", []) else 404)

    def test_folder_comparison_api_returns_typed_recursive_hash_results(self):
        created = self.client.post("/api/workspaces", files=[
            ("files", ("left/same.txt", b"identical")),
            ("files", ("right/same.txt", b"identical")),
            ("files", ("left/nested/change.bin", b"old")),
            ("files", ("right/nested/change.bin", b"new")),
            ("files", ("left/removed.txt", b"left")),
            ("files", ("right/added.txt", b"right")),
        ], headers={"Origin": "tauri://localhost"})
        self.assertEqual(created.status_code, 201)
        workspace_id = created.json()["workspace_id"]

        response = self.client.post(
            f"/api/workspaces/{workspace_id}/folder-comparisons",
            json={"left_folder": "left", "right_folder": "right"},
            headers={"Origin": "tauri://localhost"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["summary"], {"identical": 1, "changed": 1, "left_only": 1, "right_only": 1})
        self.assertEqual(body["files"][1]["path"], "nested/change.bin")
        self.assertEqual(body["files"][1]["status"], "changed")
        self.assertNotIn(self.temporary.name, response.text)

    def test_workspace_upload_and_folder_compare_include_empty_directories(self):
        created = self.client.post(
            "/api/workspaces",
            data={"directories": ["before", "before/empty-only", "after", "after/nested/empty"]},
            files=[
                ("files", ("before/kept.txt", b"same")),
                ("files", ("after/kept.txt", b"same")),
            ],
            headers={"Origin": "tauri://localhost"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["directories"], [
            "after", "after/nested", "after/nested/empty", "before", "before/empty-only",
        ])
        workspace_id = created.json()["workspace_id"]

        response = self.client.post(
            f"/api/workspaces/{workspace_id}/folder-comparisons",
            json={"left_folder": "before", "right_folder": "after"},
            headers={"Origin": "tauri://localhost"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["directory_summary"], {"identical": 1, "changed": 0, "left_only": 1, "right_only": 2})
        self.assertEqual(body["directories"], [
            {"path": ".", "status": "identical", "left_empty": False, "right_empty": False},
            {"path": "empty-only", "status": "left-only", "left_empty": True, "right_empty": None},
            {"path": "nested", "status": "right-only", "left_empty": None, "right_empty": False},
            {"path": "nested/empty", "status": "right-only", "left_empty": None, "right_empty": True},
        ])

    def test_empty_only_workspace_import_and_folder_comparison_are_supported(self):
        created = self.client.post(
            "/api/workspaces",
            data={"directories": ["before", "after"]},
            headers={"Origin": "tauri://localhost"},
        )

        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["files"], [])
        workspace_id = created.json()["workspace_id"]
        compared = self.client.post(
            f"/api/workspaces/{workspace_id}/folder-comparisons",
            json={"left_folder": "before", "right_folder": "after"},
            headers={"Origin": "tauri://localhost"},
        )

        self.assertEqual(compared.status_code, 200, compared.text)
        self.assertEqual(compared.json()["directories"], [{"path": ".", "status": "identical", "left_empty": True, "right_empty": True}])
        self.assertEqual(compared.json()["files"], [])

    def test_folder_comparison_csv_export_is_formula_safe_and_preserves_hash_report(self):
        created = self.client.post("/api/workspaces", files=[
            ("files", ("left/=SUM(1+1).csv", b"left")),
            ("files", ("right/=SUM(1+1).csv", b"right")),
            ("directories", (None, "left/empty-folder")),
            ("directories", (None, "right/empty-folder")),
        ], headers={"Origin": "tauri://localhost"})
        self.assertEqual(created.status_code, 201)
        workspace_id = created.json()["workspace_id"]

        response = self.client.post(
            f"/api/workspaces/{workspace_id}/folder-comparisons?format=csv",
            json={"left_folder": "left", "right_folder": "right"},
            headers={"Origin": "tauri://localhost"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.headers["content-type"].startswith("text/csv"))
        self.assertIn("folder-comparison.csv", response.headers["content-disposition"])
        rows = list(csv.DictReader(io.StringIO(response.text)))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["relative_path"], "'=SUM(1+1).csv")
        self.assertEqual(rows[0]["entry_type"], "file")
        self.assertEqual(rows[0]["status"], "changed")
        self.assertEqual(rows[0]["folder_a_sha256"], hashlib.sha256(b"left").hexdigest())
        self.assertEqual(rows[0]["folder_b_sha256"], hashlib.sha256(b"right").hexdigest())
        self.assertEqual(rows[1]["entry_type"], "directory")
        self.assertEqual(rows[1]["relative_path"], ".")
        self.assertEqual(rows[1]["status"], "identical")
        self.assertEqual(rows[2]["relative_path"], "empty-folder")

    def test_folder_comparison_api_rejects_invalid_scopes_and_unknown_fields(self):
        created = self.client.post("/api/workspaces", files=[
            ("files", ("left/a.txt", b"a")),
            ("files", ("right/a.txt", b"a")),
        ])
        workspace_id = created.json()["workspace_id"]
        base = f"/api/workspaces/{workspace_id}/folder-comparisons"

        traversal = self.client.post(base, json={"left_folder": "../outside", "right_folder": "right"})
        overlap = self.client.post(base, json={"left_folder": "left", "right_folder": "left/nested"})
        unknown = self.client.post(base, json={"left_folder": "left", "right_folder": "right", "host_path": "/tmp"})
        missing = self.client.post(base, json={"left_folder": "missing", "right_folder": "right"})

        self.assertEqual(traversal.status_code, 422)
        self.assertEqual(overlap.status_code, 422)
        self.assertEqual(unknown.status_code, 422)
        self.assertEqual(missing.status_code, 404)

    def test_folder_comparison_csv_rejects_unknown_format_and_oversized_output(self):
        created = self.client.post("/api/workspaces", files=[
            ("files", ("left/a.txt", b"a")),
            ("files", ("right/a.txt", b"a")),
        ])
        workspace_id = created.json()["workspace_id"]
        base = f"/api/workspaces/{workspace_id}/folder-comparisons"
        request = {"left_folder": "left", "right_folder": "right"}

        invalid = self.client.post(f"{base}?format=xlsx", json=request)
        with patch("officekit.engines.engine_workspace_exports.MAX_FOLDER_COMPARISON_CSV_BYTES", 8):
            oversized = self.client.post(f"{base}?format=csv", json=request)

        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(oversized.status_code, 413)
        self.assertIn("4 MiB", oversized.json()["detail"])



if __name__ == "__main__":
    unittest.main()
