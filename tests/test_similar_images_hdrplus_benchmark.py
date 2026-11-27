"""Opt-in real-camera burst benchmark; source images are never stored in this repo."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

from officekit.engines.engine_similar_images import SimilarImageEngine

try:
    import rawpy
    from PIL import Image
except ImportError:
    rawpy = None
    Image = None


BURST_FRAME_COUNTS = {
    "0006_20160722_115157_431": 7,
    "0006_20160727_185921_651": 4,
    "0009_20160702_154921_383": 7,
    "0030_20151121_161242_822": 5,
    "0039_20141005_130438_317": 10,
    "0043_20160825_193900_964": 3,
    "0047_20160609_110125_873": 7,
    "0127_20161018_111029_303": 7,
    "0132_20160917_175200_202": 3,
    "0155_20160923_180141_698": 3,
    "0218_20141031_195419_627": 10,
    "0272_20160515_130708_549": 3,
    "0382_20150912_125455_388": 8,
    "0543_20150918_131451_875": 8,
    "0919_20150905_181412_593": 10,
}
HDRPLUS_ROOT = os.environ.get("OFFICEKIT_HDRPLUS_BURST_ROOT")


@unittest.skipUnless(
    HDRPLUS_ROOT and sys.platform == "darwin" and rawpy is not None and Image is not None,
    "requires opt-in macOS HDR+ DNG corpus, rawpy, and Pillow for RAW conversion",
)
class HdrPlusBurstBenchmarkTests(unittest.TestCase):
    def test_groups_real_camera_burst_frames_without_merging_unrelated_scenes(self):
        root = Path(HDRPLUS_ROOT)
        with tempfile.TemporaryDirectory(prefix="officekit-hdrplus-jpeg-") as temporary:
            converted = Path(temporary)
            files = []
            for burst_name, expected_count in BURST_FRAME_COUNTS.items():
                source_directory = root / burst_name
                raw_files = sorted(source_directory.glob("*.dng"))
                self.assertEqual(len(raw_files), expected_count, f"Incomplete HDR+ fixture: {burst_name}")
                for frame_index, raw_file in enumerate(raw_files):
                    output_directory = converted / burst_name
                    output_directory.mkdir(parents=True, exist_ok=True)
                    jpeg_path = output_directory / f"payload_N{frame_index:03d}.jpg"
                    with rawpy.imread(str(raw_file)) as raw:
                        rgb = raw.postprocess(
                            output_bps=8,
                            use_camera_wb=True,
                            output_color=rawpy.ColorSpace.sRGB,
                            demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
                        )
                    Image.fromarray(rgb).save(jpeg_path, format="JPEG", quality=95, optimize=False)
                    self.assertTrue(jpeg_path.is_file() and jpeg_path.stat().st_size > 0, f"Empty JPEG output: {raw_file.name}")
                    relative_name = f"{burst_name}/{jpeg_path.name}"
                    files.append((relative_name, str(jpeg_path)))

            report = SimilarImageEngine.scan_files(files, threshold=8)
            self.assertTrue(report["complete"], report)
            self.assertEqual(report["scanned_images"], sum(BURST_FRAME_COUNTS.values()), report)
            self.assertEqual(report["errors"], [], report)

            actual_groups = [set(group["files"]) for group in report["groups"]]
            for burst_name, expected_count in BURST_FRAME_COUNTS.items():
                expected_names = {
                    f"{burst_name}/payload_N{frame:03d}.jpg"
                    for frame in range(expected_count)
                }
                matching = [group for group in actual_groups if expected_names & group]
                self.assertEqual(len(matching), 1, f"Burst was split across groups: {burst_name}; {report}")
                self.assertTrue(expected_names.issubset(matching[0]), f"Frames missed for {burst_name}; {report}")
                self.assertEqual(
                    {name.split("/", 1)[0] for name in matching[0]},
                    {burst_name},
                    f"Unrelated bursts were merged: {burst_name}; {report}",
                )


if __name__ == "__main__":
    unittest.main()
