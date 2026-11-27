"""Read back the macOS sidecar merge smoke output and verify PDF structure."""

import sys
from pathlib import Path

import pikepdf


def verify(path: Path) -> None:
    with pikepdf.open(path) as pdf:
        if len(pdf.pages) != 3:
            raise ValueError("Merged PDF page count did not match the smoke fixture.")

        with pdf.open_outline() as outline:
            if [item.title for item in outline.root] != ["first.pdf", "second.pdf"]:
                raise ValueError("Merged PDF source bookmarks were missing or reordered.")
            first_source, second_source = outline.root
            if [item.title for item in first_source.children] != ["OfficeKitOriginalOutlineMarker"]:
                raise ValueError("Merged PDF did not retain the first nested source outline.")
            if [item.title for item in second_source.children] != ["OfficeKitSecondOutlineMarker"]:
                raise ValueError("Merged PDF did not retain the second nested source outline.")
            first_destination = first_source.children[0].resolved_destination(pdf)
            second_destination = second_source.children[0].resolved_destination(pdf)
            if first_destination is None or pdf.pages.index(first_destination.page) != 0:
                raise ValueError("First source outline did not target its first merged page.")
            if second_destination is None or pdf.pages.index(second_destination.page) != 2:
                raise ValueError("Second source outline did not target its first merged page.")

        fields = pdf.acroform.fields
        field_values = [str(field.value) for field in fields]
        field_names = [field.fully_qualified_name for field in fields]
        if sorted(field_values) != ["OfficeKitAdaValueMarker", "OfficeKitGraceValueMarker"]:
            raise ValueError("Merged PDF did not retain both distinct AcroForm values.")
        if len(field_names) != 2 or len(set(field_names)) != 2:
            raise ValueError("Merged PDF form field names were not made unique.")


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: verify_pdf_merge_output.py <merged.pdf>", file=sys.stderr)
        return 2
    try:
        verify(Path(sys.argv[1]))
    except (OSError, ValueError, pikepdf.PdfError) as error:
        print(f"PDF merge structure verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
