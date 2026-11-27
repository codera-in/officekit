"""PDF slice catalogue entries (P06, P08, P10, P12–P13, P15–P17)."""

TOOLS = [
    {"id": "pdf_rotate_pages", "name": "Rotate PDF Pages", "category": "PDF & Documents", "tab": "pdf",
     "desc": "Turn selected pages 90, 180 or 270 degrees by setting the page rotation; page content is not redrawn", "icon": "fa-rotate-right"},
    {"id": "pdf_from_images", "name": "Images to PDF", "category": "PDF & Documents", "tab": "pdf",
     "desc": "Combine 1–200 ordered images into one PDF, one page per image, with page size, orientation, fit and margin", "icon": "fa-images"},
    {"id": "pdf_metadata_view", "name": "View PDF Metadata", "category": "Privacy & Security", "tab": "pdf",
     "desc": "Read document properties, XMP, page sizes and form summary without changing the file", "icon": "fa-circle-info"},
    {"id": "pdf_watermark", "name": "Watermark PDF", "category": "PDF & Documents", "tab": "pdf",
     "desc": "Stamp text or an image on selected pages of a new copy, with an engine-rendered preview", "icon": "fa-droplet"},
    {"id": "pdf_page_numbers", "name": "Add PDF Page Numbers", "category": "PDF & Documents", "tab": "pdf",
     "desc": "Number selected pages in a margin with optional roman numerals or a custom template, with an engine-rendered preview", "icon": "fa-hashtag"},
    {"id": "pdf_resize_pages", "name": "Resize PDF Pages", "category": "PDF & Documents", "tab": "pdf",
     "desc": "Change page size to A4, Letter or a custom size, scaling content to fit or changing the canvas only", "icon": "fa-up-right-and-down-left-from-center"},
    {"id": "pdf_grayscale", "name": "Grayscale PDF", "category": "PDF & Documents", "tab": "pdf",
     "desc": "Convert colours to gray while keeping text selectable; refuses content it cannot convert unless you rasterize", "icon": "fa-circle-half-stroke"},
    {"id": "pdf_flatten", "name": "Flatten PDF Forms & Annotations", "category": "PDF & Documents", "tab": "pdf",
     "desc": "Make form values and annotations part of the page so they can no longer be edited; this cannot be undone in the new copy", "icon": "fa-layer-group"},
]

# Aliases avoid format pairs such as "png to pdf": those would rank these tools above the
# existing converter and PDF-to-image results for the same format words.
KEYWORDS = {
    "pdf_rotate_pages": ["rotate pdf", "rotate pdf pages", "turn pdf pages", "pdf page rotation"],
    "pdf_from_images": ["images to pdf", "photos to pdf", "combine images pdf", "image batch pdf"],
    "pdf_metadata_view": ["pdf properties", "view pdf metadata", "pdf document info", "inspect pdf", "pdf info"],
    "pdf_watermark": ["watermark pdf", "pdf watermark", "stamp pdf", "confidential stamp pdf", "draft stamp pdf"],
    "pdf_page_numbers": ["page numbers pdf", "number pdf pages", "add page numbers", "pdf page numbering", "bates numbers"],
    "pdf_resize_pages": ["resize pdf", "pdf page size", "change pdf page size", "a4 pdf"],
    "pdf_grayscale": ["grayscale pdf", "greyscale pdf", "black and white pdf", "desaturate pdf"],
    "pdf_flatten": ["flatten pdf", "flatten form", "flatten annotations", "remove form fields pdf", "non editable pdf"],
}
