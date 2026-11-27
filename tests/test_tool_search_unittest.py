import re
import unittest
from pathlib import Path

from officekit.engines.engine_comms import CommsEngine, TOOL_REGISTRY, TOOL_SEARCH_KEYWORDS


class ToolSearchTests(unittest.TestCase):
    def ids(self, query):
        return [tool["id"] for tool in CommsEngine.search_tools(query)]

    def test_restore_from_trash_is_found_by_its_restore_phrases(self):
        # S06: the Restore from Trash entry answers to the words people use for putting trash back.
        for query in ("restore", "put back", "undelete", "recover from trash"):
            with self.subTest(query=query):
                self.assertIn("trash_restore", self.ids(query))
        restored = next(tool for tool in TOOL_REGISTRY if tool["id"] == "trash_restore")
        self.assertEqual(restored["name"], "Restore from Trash")
        self.assertEqual(restored["category"], "Storage & Cleanup")

    def test_archive_create_phrases_do_not_surface_both_zip_tools(self):
        # CR-7: "create archive" and "make archive" must not return both Create ZIP and Compress & Extract ZIP.
        for query in ("create archive", "make archive"):
            ids = self.ids(query)
            self.assertFalse({"zip_create", "archive_manager"} <= set(ids), (query, ids))

    def test_ergonomics_queries_find_distinct_modes_in_one_local_workbench(self):
        for query, expected in (
            ("stretch reminder", "ergonomics_break"),
            ("eye strain", "ergonomics_eyes"),
            ("drink water", "ergonomics_water"),
            ("airpods posture", "ergonomics_posture"),
            ("meeting countdown", "meeting_countdown"),
        ):
            with self.subTest(query=query):
                match = next(tool for tool in CommsEngine.search_tools(query) if tool["id"] == expected)
                self.assertEqual(match["tab"], "ergonomics")

    def test_pdf_unlock_is_discoverable_in_natural_word_orders_and_inflections(self):
        for query in ('PDF unlock', 'unlock PDF', 'unlock PDFs', 'PDF passwords remove', 'PDF decrypting', 'unlock unlock pdf'):
            with self.subTest(query=query):
                self.assertEqual(self.ids(query)[0], 'pdf_unlock')

    def test_common_action_paraphrases_route_across_the_tool_catalog(self):
        queries = {
            "locate duplicate files": "dup_finder",
            "identify file format": "file_type",
            "examine jwt token": "jwt_inspector",
            "compute loan payment": "loan_emi",
            "create secure password": "password_generator",
            "wipe photo gps metadata": "image_exif_strip",
            "screen capture blur": "screenshot_editor",
            "calculate cpu usage": "system_resources",
            "reset password pdf": "pdf_unlock",
            "protect pdf": "pdf_protect",
            "lock pdf": "pdf_protect",
            "delete pdf pages": "pdf_delete_pages",
        }
        for query, expected in queries.items():
            with self.subTest(query=query):
                self.assertIn(expected, self.ids(query))
        self.assertNotIn("pdf_unlock", self.ids("protect pdf"))

    def test_partial_duplicate_query_finds_duplicate_finder(self):
        for query in ("Dupl", "duplic", "duplicate", "duplicates"):
            with self.subTest(query=query):
                self.assertEqual(self.ids(query)[0], "dup_finder")

    def test_every_registered_tool_has_explicit_useful_search_keywords(self):
        self.assertEqual(set(TOOL_SEARCH_KEYWORDS), {tool['id'] for tool in TOOL_REGISTRY})
        for tool in TOOL_REGISTRY:
            keywords = TOOL_SEARCH_KEYWORDS[tool['id']]
            self.assertGreaterEqual(len(keywords), 2, tool['id'])
            for query in (tool['name'], keywords[0], ' '.join(reversed(keywords[0].split()))):
                with self.subTest(tool=tool['id'], query=query):
                    self.assertIn(tool['id'], self.ids(query))

    def test_plural_common_nouns_find_supported_tools_without_unsupported_actions(self):
        queries = {'PDFs merge': 'pdf_merge', 'file checksums': 'file_hash', 'directory comparison': 'folder_compare', 'transcribe audio': 'voice_transcription', 'meeting notes': 'meeting_notes', 'duplicate files': 'dup_finder', 'colors converter': 'color_converter'}
        for query, tool_id in queries.items():
            with self.subTest(query=query):
                self.assertIn(tool_id, self.ids(query))
        self.assertNotIn('pdf_text_extract', self.ids('PDF OCR'))
        for query in ('minify json', 'unlock DOCX', 'QBO', 'remove duplicate files automatically'):
            with self.subTest(query=query):
                self.assertEqual(self.ids(query), [])

    def test_audio_tools_are_separate_and_describe_local_processing(self):
        voice = next(tool for tool in TOOL_REGISTRY if tool["id"] == "voice_transcription")
        notes = next(tool for tool in TOOL_REGISTRY if tool["id"] == "meeting_notes")
        self.assertIn("local audio", voice["desc"].lower())
        self.assertIn("meeting notes", notes["name"].lower())
        self.assertNotEqual(voice["id"], notes["id"])

    def test_format_aliases_find_closest_convertors(self):
        self.assertEqual(self.ids("jpeg"), ["image_converter"])
        self.assertIn("data_converter", self.ids("xlsx to csv"))
        self.assertIn("data_converter", self.ids("spreadsheet json"))

    def test_image_converter_search_includes_shared_media_workbench_but_not_statement_extractor(self):
        self.assertEqual(self.ids("image converter"), ["image_converter", "media_toolkit"])
        self.assertIn("bank_statement", self.ids("image statement to csv"))

    def test_converter_search_covers_supported_source_and_target_formats(self):
        for query in ("CSV to SQL", "CSV to HTML", "JSON to YAML", "Excel to HTML", "TXT to YAML", "GIF to PDF", "TIFF conversion"):
            with self.subTest(query=query):
                expected = "image_converter" if query.startswith(("GIF", "TIFF")) else "data_converter"
                self.assertIn(expected, self.ids(query))
        self.assertIn("image_converter", self.ids("image to PDF"))
        self.assertEqual(self.ids("PDF to PNG"), ["pdf_to_images"])

    def test_every_pending_calculator_is_found_by_its_stable_id_on_the_calculators_tab(self):
        # AC2 / PM-6: a search for the stable ID returns that exact calculator entry.
        for tool_id in (
            "weighted_average", "fractions_ratios", "roi", "cagr", "date_difference", "age_calculator",
            "business_days", "work_hours", "time_zone_converter", "quadratic_solver", "gcd_lcm",
            "descriptive_statistics", "geometry",
        ):
            with self.subTest(tool_id=tool_id):
                match = next((tool for tool in CommsEngine.search_tools(tool_id) if tool["id"] == tool_id), None)
                self.assertIsNotNone(match)
                self.assertEqual(match["tab"], "calculators")

    def test_every_pdf_slice_tool_is_found_by_its_stable_id_on_the_pdf_tab(self):
        # AC2 / PM-4: a search for each new PDF stable ID returns that exact entry on the pdf tab.
        for tool_id in (
            "pdf_rotate_pages", "pdf_from_images", "pdf_metadata_view", "pdf_watermark",
            "pdf_page_numbers", "pdf_resize_pages", "pdf_grayscale", "pdf_flatten",
        ):
            with self.subTest(tool_id=tool_id):
                match = next((tool for tool in CommsEngine.search_tools(tool_id) if tool["id"] == tool_id), None)
                self.assertIsNotNone(match)
                self.assertEqual(match["tab"], "pdf")

    def test_scientific_math_and_unit_queries_find_exact_calculator_tools(self):
        for query in ("scientific calculator", "evaluate expression", "sin cos tan", "radians degrees calculator"):
            with self.subTest(query=query):
                self.assertIn("math_eval", self.ids(query))
        for query in ("unit converter", "km to miles", "celsius fahrenheit", "bytes to megabytes"):
            with self.subTest(query=query):
                self.assertIn("units_convert", self.ids(query))
        html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
        self.assertIn("math_eval: { tab: 'calculators', calculator: 'scientific' }", html)
        self.assertIn("units_convert: { tab: 'calculators', calculator: 'units' }", html)

    def test_url_encode_decode_queries_find_the_local_codec_screen(self):
        for query in ("url encode", "url decode", "percent encode", "URI component"):
            with self.subTest(query=query):
                self.assertIn("url_codec", self.ids(query))
        html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
        self.assertIn("url_codec: { tab: 'converter', converterMode: 'url_codec', focusId: 'url-codec-input' }", html)

    def test_financial_utility_queries_find_their_calculator_forms(self):
        queries = {
            "margin_markup": ("gross margin", "markup calculator"),
            "break_even": ("break even point", "breakeven units"),
            "simple_interest": ("simple interest", "interest without compounding"),
            "depreciation": ("straight line depreciation", "salvage value schedule"),
        }
        for tool_id, terms in queries.items():
            for query in terms:
                with self.subTest(tool=tool_id, query=query):
                    self.assertIn(tool_id, self.ids(query))
        html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
        self.assertIn("margin_markup: { tab: 'calculators', calculator: 'margin' }", html)
        self.assertIn("break_even: { tab: 'calculators', calculator: 'break-even' }", html)
        self.assertIn("simple_interest: { tab: 'calculators', calculator: 'simple-interest' }", html)
        self.assertIn("depreciation: { tab: 'calculators', calculator: 'depreciation' }", html)

    def test_pdf_to_query_returns_all_related_pdf_tools_not_one_full_phrase_match(self):
        results = set(self.ids("PDF to"))
        self.assertTrue({
            "bank_statement", "pdf_unlock", "pdf_protect", "pdf_merge", "pdf_split",
            "pdf_compress", "pdf_metadata_strip", "pdf_to_images", "pdf_table_extractor",
            "pdf_text_extract",
            "pdf_delete_pages", "pdf_reorder_pages",
        }.issubset(results))

    def test_protect_pdf_search_returns_the_password_protector(self):
        self.assertEqual(self.ids("protect PDF"), ["pdf_protect"])
        self.assertIn("pdf_protect", self.ids("password protect pdf"))

    def test_pdf_password_search_ranks_exact_action_before_synonym_related_tools(self):
        self.assertEqual(self.ids("unlock pdf")[:2], ["pdf_unlock", "pdf_metadata_strip"])
        self.assertNotIn("pdf_delete_pages", self.ids("unlock pdf"))
        self.assertNotIn("pdf_reorder_pages", self.ids("split pdf"))
        self.assertEqual(self.ids("remove pdf metadata")[:1], ["pdf_metadata_strip"])

    def test_pdf_text_search_routes_to_selectable_text_export(self):
        for query in ("pdf to text", "pdf to txt", "extract text from pdf", "pdf to markdown"):
            with self.subTest(query=query):
                self.assertIn("pdf_text_extract", self.ids(query))
        self.assertNotIn("pdf_text_extract", self.ids("extract text from docx"))

    def test_directional_pdf_image_conversion_requires_pdf_context(self):
        self.assertIn("pdf_to_images", self.ids("PDF to JPEG"))
        self.assertIn("pdf_to_images", self.ids("PDF to PNG"))
        self.assertIn("pdf_delete_pages", self.ids("delete pages from pdf"))
        self.assertIn("pdf_reorder_pages", self.ids("reorder pdf pages"))
        self.assertNotIn("pdf_to_images", self.ids("JPEG"))
        self.assertEqual(self.ids("jpeg"), ["image_converter"])

    def test_pdf_statement_export_aliases_cover_csv_excel_and_xls_extensions(self):
        for query in ("PDF to CSV", "PDF to XLS", "PDF to XLSX", "PDF to Excel"):
            with self.subTest(query=query):
                self.assertIn("bank_statement", self.ids(query))
                self.assertIn("pdf_table_extractor", self.ids(query))

    def test_pdf_table_tool_requires_pdf_context_and_is_not_a_statement_parser_alias(self):
        self.assertIn("pdf_table_extractor", self.ids("extract table from PDF"))
        self.assertNotIn("pdf_table_extractor", self.ids("CSV"))

    def test_developer_utilities_search_aliases_open_the_shared_local_workbench(self):
        queries = {
            "devtools_format": ("format json", "json to yaml", "yaml to json", "base64 encode", "base64 decode"),
            "jwt_inspector": ("jwt", "decode jwt", "token claims"),
            "crypto_hashes": ("sha256", "sha512", "hmac", "text digest"),
        }
        for tool_id, terms in queries.items():
            for query in terms:
                with self.subTest(tool=tool_id, query=query):
                    self.assertIn(tool_id, self.ids(query))
        html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
        for tool_id in ("devtools_format", "jwt_inspector", "crypto_hashes"):
            self.assertIn(f"{tool_id}: {{ tab: 'converter', converterMode: 'developer_tools'", html)

    def test_workspace_checksum_and_file_type_search_open_the_shared_local_workspace(self):
        for tool_id, terms in {
            "file_hash": ("file hash", "sha256 file", "checksum file", "compare checksum", "verify checksum against digest"),
            "file_type": ("detect file type", "mime type", "extension mismatch"),
        }.items():
            for query in terms:
                with self.subTest(tool=tool_id, query=query):
                    self.assertIn(tool_id, self.ids(query))
        html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
        self.assertIn("file_hash: { tab: 'workspace', fileTool: 'file_hash' }", html)
        self.assertIn("file_type: { tab: 'workspace', fileTool: 'file_type' }", html)

    def test_image_resize_queries_find_the_dimension_and_batch_workbench(self):
        for query in ("resize image", "batch image resize", "reduce image dimensions", "fit image", "image size pixels"):
            with self.subTest(query=query):
                self.assertIn("image_resize", self.ids(query))
        record = {tool["id"]: tool for tool in CommsEngine.search_tools("resize image")}['image_resize']
        self.assertIn("never upscaling", record["desc"])
        html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
        self.assertIn("image_resize: { tab: 'converter', converterMode: 'media_toolkit', mediaKind: 'image', mediaOperation: 'image-resize'", html)

    def test_file_split_join_is_searchable_and_routes_to_its_local_workspace(self):
        for query in ("split large file", "join split files", "checksum parts"):
            with self.subTest(query=query):
                self.assertIn("file_split_join", self.ids(query))
        record = {tool["id"]: tool for tool in CommsEngine.search_tools("split large file")}['file_split_join']
        self.assertIn("SHA-256", record["desc"])
        html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
        self.assertIn("file_split_join: { tab: 'workspace', fileTool: 'split_join' }", html)

    def test_screenshot_editor_is_searchable_and_routes_to_local_editor(self):
        for query in ("paste screenshot", "blur screenshot", "redact screenshot", "crop screenshot"):
            self.assertIn("screenshot_editor", self.ids(query))
        record = {tool["id"]: tool for tool in CommsEngine.search_tools("paste screenshot")}['screenshot_editor']
        self.assertIn("metadata-free", record["desc"].casefold())
        html = (Path(__file__).resolve().parents[1] / "index.html").read_text()
        self.assertIn("screenshot_editor: { tab: 'screenshot' }", html)

    def test_password_and_passphrase_queries_find_the_local_generator(self):
        for query in ("password", "random password", "passphrase", "diceware", "secure password"):
            with self.subTest(query=query):
                self.assertIn("password_generator", self.ids(query))
        html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
        self.assertIn("password_generator: { tab: 'password' }", html)
        self.assertIn('id="tab-password"', html)

    def test_color_format_directions_and_css_aliases_find_the_color_converter(self):
        for query in ("HEX to RGB", "RGB to HEX", "rgba to hex", "CSS color", "color alpha"):
            with self.subTest(query=query):
                self.assertIn("color_converter", self.ids(query))
        html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
        self.assertIn("color_converter: { tab: 'color' }", html)
        self.assertIn('id="tab-color"', html)

    def test_network_diagnostic_queries_find_each_user_triggered_screen(self):
        queries = {
            "network_dns": ("dns lookup", "mx record", "nameserver"),
            "network_ping": ("ping test", "packet loss", "latency"),
            "network_interfaces": ("network interface", "local ip", "wifi address"),
        }
        for tool_id, terms in queries.items():
            for query in terms:
                with self.subTest(tool=tool_id, query=query):
                    self.assertIn(tool_id, self.ids(query))
        html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
        for tool_id in queries:
            with self.subTest(tool=tool_id):
                self.assertIn(f"{tool_id}: {{ tab: 'network'", html)
        self.assertIn('id="tab-network"', html)

    def test_system_report_and_resource_queries_find_the_manual_overview(self):
        queries = {
            "system_info": ("system information", "mac system report", "computer specs"),
            "system_resources": ("cpu usage", "memory usage", "available memory"),
        }
        for tool_id, terms in queries.items():
            for query in terms:
                with self.subTest(tool=tool_id, query=query):
                    self.assertIn(tool_id, self.ids(query))
        html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
        self.assertIn("system_info: { tab: 'system', focusId: 'system-refresh' }", html)
        self.assertIn("system_resources: { tab: 'system', focusId: 'system-refresh' }", html)

    def test_burst_and_similar_photo_queries_route_to_selected_copy_workspace(self):
        for query in ("similar images", "find similar photos", "burst photos", "camera burst", "near duplicate photos"):
            with self.subTest(query=query):
                self.assertIn("similar_images", self.ids(query))
        html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
        self.assertIn("similar_images: { tab: 'workspace', fileTool: 'similar_images' }", html)
        self.assertIn("/similar-image-reports", html)

    def test_folder_comparison_is_searchable_and_routes_to_workspace(self):
        for query in ("compare folders", "directory compare", "find changed files between folders"):
            with self.subTest(query=query):
                self.assertIn("folder_compare", self.ids(query))
        record = {tool["id"]: tool for tool in CommsEngine.search_tools("compare folders")}['folder_compare']
        self.assertIn("SHA-256", record["desc"])
        html = (Path(__file__).resolve().parents[1] / "index.html").read_text()
        self.assertIn("folder_compare: { tab: 'workspace', fileTool: 'folder_compare' }", html)

    def test_qbo_search_does_not_advertise_the_disabled_export(self):
        self.assertEqual(self.ids("QBO"), [])
        statement = {tool["id"]: tool for tool in CommsEngine.search_tools("")}["bank_statement"]
        self.assertNotIn("qbo", statement["desc"].casefold())

    def test_advanced_pdf_search_copy_matches_the_actual_operation_contract(self):
        records = {tool["id"]: tool for tool in CommsEngine.search_tools("pdf")}
        self.assertIn("2–20", records["pdf_merge"]["desc"])
        self.assertIn("one PDF", records["pdf_split"]["desc"])
        self.assertIn("lossless", records["pdf_compress"]["desc"].casefold())
        self.assertIn("may be larger", records["pdf_compress"]["desc"].casefold())
        self.assertIn("document-info", records["pdf_metadata_strip"]["desc"].casefold())
        self.assertNotIn("tracking streams", records["pdf_metadata_strip"]["desc"].casefold())

    def test_search_requires_all_meaningful_terms_and_ranks_name_matches_first(self):
        self.assertEqual(self.ids("loan"), ["loan_emi"])
        self.assertEqual(self.ids("pdf unrelated"), [])
        self.assertEqual(self.ids("   "), [tool["id"] for tool in CommsEngine.search_tools("")])

    def test_search_keywords_are_returned_for_consistent_client_side_filtering(self):
        image_tool = CommsEngine.search_tools("jpeg")[0]
        self.assertIn("jpeg", image_tool["keywords"])
        self.assertIn("jpg", image_tool["keywords"])

    def test_registry_records_and_available_frontend_destinations_stay_in_sync(self):
        tool_ids = [tool.get("id") for tool in TOOL_REGISTRY]
        self.assertEqual(len(tool_ids), len(set(tool_ids)))
        self.assertTrue(all(isinstance(tool_id, str) and tool_id for tool_id in tool_ids))
        for tool in TOOL_REGISTRY:
            for field in ("name", "category", "desc", "icon"):
                self.assertIsInstance(tool.get(field), str, f"{tool.get('id')} is missing {field}")
                self.assertTrue(tool[field].strip(), f"{tool.get('id')} has an empty {field}")
        self.assertLessEqual(set(TOOL_SEARCH_KEYWORDS), set(tool_ids))
        self.assertEqual({tool["id"] for tool in CommsEngine.search_tools("")}, set(tool_ids))

        html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
        destination_source = re.search(
            r"const OFFICEKIT_TOOL_DESTINATIONS = Object\.freeze\(\{([\s\S]*?)\n        \}\);",
            html,
        )
        self.assertIsNotNone(destination_source, "the stable-ID destination map is missing")
        destination_pattern = r"^\s+([a-z][a-z0-9_]*): \{ tab: '([^']+)'([^}]*)\},?$"
        destination_records = re.findall(destination_pattern, destination_source.group(1), re.MULTILINE)
        # Slice extensions register their destinations one line each in their own assets file.
        for slice_script in sorted((Path(__file__).resolve().parents[1] / "assets").glob("officekit-slice-*.js")):
            destination_records += re.findall(destination_pattern, slice_script.read_text(encoding="utf-8"), re.MULTILINE)
        self.assertTrue(destination_records)
        destinations = {tool_id: (tab, attributes) for tool_id, tab, attributes in destination_records}
        self.assertEqual(len(destinations), len(destination_records), "destination IDs must be unique")
        self.assertLessEqual(set(destinations), set(tool_ids), "the UI must not route unknown registry IDs")
        self.assertEqual(
            set(destinations),
            set(tool_ids),
            f"every searchable tool needs an actual UI destination; missing: {sorted(set(tool_ids) - set(destinations))}",
        )

        section_ids = set(re.findall(r'<section id="tab-([^"]+)"', html))
        # Slice destinations may mount their tool tab dynamically instead of declaring a
        # static section in index.html. Require the registered extension to create it.
        for slice_script in sorted((Path(__file__).resolve().parents[1] / "assets").glob("officekit-slice-*.js")):
            section_ids.update(re.findall(r"screen\.id\s*=\s*'tab-([^']+)'", slice_script.read_text(encoding="utf-8")))
        workspace_source = re.search(
            r"const WORKSPACE_TOOL_COPY = Object\.freeze\(\{([\s\S]*?)\n        \}\);",
            html,
        )
        self.assertIsNotNone(workspace_source, "the local workspace operation registry is missing")
        workspace_actions = set(re.findall(r"^\s+([a-z_]+): \{", workspace_source.group(1), re.MULTILINE))
        for tool_id, (tab, attributes) in destinations.items():
            with self.subTest(tool_id=tool_id):
                self.assertIn(tab, section_ids, f"{tool_id} points at a missing tab")
                option_pairs = dict(re.findall(r"([a-zA-Z]+): '([^']+)'", attributes))
                if "pdfTool" in option_pairs:
                    self.assertRegex(html, re.escape(f'data-pdf-tool="{option_pairs["pdfTool"]}"'))
                if "fileTool" in option_pairs:
                    self.assertIn(
                        option_pairs["fileTool"],
                        workspace_actions,
                        f"{tool_id} points at a missing local file operation",
                    )
                if "calculator" in option_pairs:
                    self.assertRegex(html, re.escape(f'id="calc-form-{option_pairs["calculator"]}"'))
                if "focusId" in option_pairs:
                    self.assertRegex(html, re.escape(f'id="{option_pairs["focusId"]}"'))

    def test_two_character_prefix_finds_pdf_tools(self):
        pdf_ids = self.ids('pd')
        self.assertGreaterEqual(len(pdf_ids), 5)
        for expected in ('pdf_unlock', 'pdf_protect', 'pdf_merge', 'pdf_split', 'pdf_compress', 'pdf_editor'):
            with self.subTest(tool=expected):
                self.assertIn(expected, pdf_ids)

    def test_search_rejects_non_text_and_oversized_queries(self):
        self.assertEqual(self.ids('the and to'), [])
        for query in (None, 123, ["pdf"], "x" * 257):
            with self.subTest(query=type(query).__name__):
                with self.assertRaises(ValueError):
                    CommsEngine.search_tools(query)


class AdvertisedDeveloperScopeTests(unittest.TestCase):
    def test_unavailable_minify_operation_is_not_advertised_or_routed(self):
        self.assertEqual(CommsEngine.search_tools("minify json"), [])
        formatter = next(tool for tool in CommsEngine.search_tools("format json") if tool["id"] == "devtools_format")
        self.assertIn("Base64", formatter["desc"])


if __name__ == "__main__":
    unittest.main()
