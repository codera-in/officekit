"""Image slice catalogue entries (I06–I07, I10–I12, I14–I20).

Every entry is development-only: none of these IDs is listed in release-profile.json.
Search aliases must never be keyed by a core tool ID.
"""

IMAGE_TOOLS_TAB = "image-tools"

TOOLS = [
    {"id": "image_rotate_flip", "name": "Rotate & Flip Image", "category": "Images", "tab": IMAGE_TOOLS_TAB, "desc": "Turn an image 90, 180 or 270 degrees clockwise and flip it horizontally or vertically; orientation is applied first and the EXIF tag is reset", "icon": "fa-rotate"},
    {"id": "image_exif_view", "name": "EXIF Viewer", "category": "Images", "tab": IMAGE_TOOLS_TAB, "desc": "Read date, camera, exposure and location fields from a photo; GPS coordinates stay hidden until you choose to show them", "icon": "fa-camera"},
    {"id": "image_dpi", "name": "Image DPI / PPI", "category": "Images", "tab": IMAGE_TOOLS_TAB, "desc": "Set the print density tag of a photo in pixels per inch or centimetre without resampling its pixels", "icon": "fa-ruler-combined"},
    {"id": "image_grayscale", "name": "Grayscale Image", "category": "Images", "tab": IMAGE_TOOLS_TAB, "desc": "Make an image black and white using ITU-R 601 luma, keeping any transparency", "icon": "fa-circle-half-stroke"},
    {"id": "image_adjust", "name": "Image Color Adjustments", "category": "Images", "tab": IMAGE_TOOLS_TAB, "desc": "Adjust brightness, contrast and saturation from -100 to 100 with a live preview that matches the saved copy", "icon": "fa-sliders"},
    {"id": "image_border", "name": "Image Border & Rounded Corners", "category": "Images", "tab": IMAGE_TOOLS_TAB, "desc": "Add a coloured border with optional rounded corners and opacity; works on single images or a batch", "icon": "fa-vector-square"},
    {"id": "image_palette", "name": "Dominant Colors", "category": "Images", "tab": IMAGE_TOOLS_TAB, "desc": "List the dominant colours of an image as HEX, RGB and share of pixels; transparent pixels are excluded", "icon": "fa-palette"},
    {"id": "image_data_uri", "name": "Image ↔ Data URI", "category": "Images", "tab": IMAGE_TOOLS_TAB, "desc": "Turn an image into a base64 data URI and back again; the round trip keeps every byte", "icon": "fa-code"},
    {"id": "image_icon_pack", "name": "Icon Pack Generator", "category": "Images", "tab": IMAGE_TOOLS_TAB, "desc": "Build web favicons, Windows .ico and macOS .iconset sizes in one ZIP, padded or centre-cropped to a square", "icon": "fa-icons"},
    {"id": "image_collage", "name": "Image Collage", "category": "Images", "tab": IMAGE_TOOLS_TAB, "desc": "Arrange 2 to 50 images in a grid with set columns, cell size, gap, padding and background", "icon": "fa-table-cells-large"},
    {"id": "image_contact_sheet", "name": "Contact Sheet", "category": "Images", "tab": IMAGE_TOOLS_TAB, "desc": "Lay out many images on A4 or Letter pages as one document or a ZIP of page images, with optional file names", "icon": "fa-table-cells"},
    {"id": "image_compare", "name": "Compare Images", "category": "Images", "tab": IMAGE_TOOLS_TAB, "desc": "Compare two images side by side, as an overlay or as a difference map with pixel counts at a stated threshold", "icon": "fa-code-compare"},
]

KEYWORDS = {
    "image_rotate_flip": ["rotate image", "flip image", "mirror image", "turn photo", "orientation", "rotate photo", "flip photo"],
    "image_exif_view": ["exif", "photo metadata", "camera info", "image details", "gps in photo", "photo date", "view metadata"],
    "image_dpi": ["dpi", "ppi", "image density", "print resolution", "pixels per inch", "set dpi"],
    "image_grayscale": ["grayscale", "greyscale", "black and white", "black white image", "monochrome photo"],
    "image_adjust": ["brightness", "contrast", "saturation", "color adjust", "colour adjust", "image levels"],
    "image_border": ["image border", "photo border", "rounded corners", "round image corners", "add frame to image"],
    "image_palette": ["dominant color", "dominant colour", "color palette", "colour palette", "image colors", "swatches from image"],
    "image_data_uri": ["base64 image", "data uri", "image base64", "data url", "image to base64", "base64 to image"],
    "image_icon_pack": ["favicon", "app icon", "iconset", "ico file", "apple touch icon", "icon generator"],
    "image_collage": ["photo collage", "image grid", "combine images", "photo grid", "merge images"],
    "image_contact_sheet": ["thumbnail sheet", "thumbnail grid", "contact sheet document", "photo index", "image index sheet"],
    "image_compare": ["diff images", "image difference", "pixel diff", "compare photos", "visual diff", "overlay images"],
}
