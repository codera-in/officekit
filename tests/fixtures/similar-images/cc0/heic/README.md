# HEIC / HEIF test fixtures

These real HEIC files are downloaded from [HEIC.best's sample gallery](https://heic.best/heic-samples), which states that all sample files are released under CC0 1.0 and can be reused commercially. The gallery describes them as real photos created from public-domain stills and says it adds no GPS or personal camera-roll data.

| File | SHA-256 | Use |
| --- | --- | --- |
| `still-medium.heic` | `4951d682f8b66b0ab1c583457edcc7a192677ded84b66a5e72d73d98771e5806` | HEIC scan input depicting a car (1200 × 1600) |
| `still-high-quality.heic` | `75ee292ab3e63dcf208bc6bbb8efabd20c04a91ebf3ad940bfa45b36fdf45f2a` | Unrelated HEIC scan input depicting a temple (1200 × 1600) |

The integration test copies the car fixture to both `.heic` and `.heif` names to verify native decoding and a positive exact-image match, then includes the temple fixture to check cross-scene separation. The aggregate-pixel limit is covered separately. These samples do not establish recall across real camera burst libraries; see the opt-in HDR+ benchmark for curated camera-burst evidence.
