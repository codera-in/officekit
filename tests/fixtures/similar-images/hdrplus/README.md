# Optional real-camera burst benchmark

This benchmark uses 15 burst folders from Google's HDR+ Burst Photography Dataset
to check that the similar-image finder groups actual handheld camera frames without
merging unrelated scenes. The DNG source photos are **not** committed to this repo or
bundled in OfficeKit.

Dataset source: <https://www.hdrplusdata.org/dataset.html>  
Google Cloud bucket: `gs://hdrplusdata/20171106_subset/bursts/`  
Dataset license: Creative Commons Attribution-ShareAlike (CC BY-SA). Please review the
dataset license and cite Hasinoff et al. (SIGGRAPH Asia 2016) before using the images.

Download these directories into one local folder:

- `0006_20160722_115157_431` (7 frames)
- `0006_20160727_185921_651` (4 frames)
- `0009_20160702_154921_383` (7 frames)
- `0030_20151121_161242_822` (5 frames)
- `0039_20141005_130438_317` (10 frames)
- `0043_20160825_193900_964` (3 frames)
- `0047_20160609_110125_873` (7 frames)
- `0127_20161018_111029_303` (7 frames)
- `0132_20160917_175200_202` (3 frames)
- `0155_20160923_180141_698` (3 frames)
- `0218_20141031_195419_627` (10 frames)
- `0272_20160515_130708_549` (3 frames)
- `0382_20150912_125455_388` (8 frames)
- `0543_20150918_131451_875` (8 frames)
- `0919_20150905_181412_593` (10 frames)

The expanded subset covers 95 frames from 15 camera bursts. The DNG input frames
total about 1.6 GB; only the selected burst directories are needed, not the full
37 GiB curated subset.

Then run the opt-in Mac benchmark:

```sh
OFFICEKIT_HDRPLUS_BURST_ROOT=/path/to/bursts .venv/bin/python -m pytest -q tests/test_similar_images_hdrplus_benchmark.py
```

The test develops local DNGs to temporary JPEGs with rawpy/LibRaw, invokes the
actual bounded image scanner, and removes all converted files when it exits. The
test dependencies include rawpy; do not use a generic video decoder for these
camera RAW files because RAW development settings affect the measured matching
precision and recall.
