# SVG image conversion decision

**Status:** Approved by the product owner on 2026-10-17.

The image converter accepts SVG files and presents the supported image outputs:
PNG, JPEG, WebP, BMP, ICO, TIFF, and PDF. SVG defaults to PNG. The primary
action names the selected output (for example, “Convert to PNG”), and the
format controls expose the selected state accessibly.

OfficeKit sanitizes SVG markup locally before rasterizing it at the declared
dimensions. It removes script-capable, embedded, and externally linked content,
limits input size to 10 MiB and output dimensions to 40 megapixels, then passes
the generated PNG through the existing local image conversion engine. PNG keeps
transparency; JPEG and BMP are composited onto white by the existing engine.

No external SVG resources are fetched. The source file remains unchanged.

## Approved source preview

**Status:** Approved by the product owner on 2026-10-17.

When an image is selected, the converter shows a contained source preview on a
theme-aware checkerboard so transparent pixels are visible. Raster previews
use a local object URL; SVG previews reuse the sanitizer and rasterizer above.
The preview reports the source dimensions, updates when another file is
selected, and releases temporary object URLs when replaced or when leaving the
converter. If a file cannot be previewed, the converter explains that and
keeps conversion available. Non-image files do not show an image preview.
