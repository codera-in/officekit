"""Bounded signature-based file type detection for selected workspace copies."""

from pathlib import PurePosixPath


class FileTypeDetector:
    MAX_HEADER_BYTES = 16_384
    METHOD = "magic-bytes+utf8"

    SIGNATURES = (
        (b"%PDF-", "PDF", "application/pdf"),
        (b"\x89PNG\r\n\x1a\n", "PNG", "image/png"),
        (b"\xff\xd8\xff", "JPEG", "image/jpeg"),
        (b"GIF87a", "GIF", "image/gif"),
        (b"GIF89a", "GIF", "image/gif"),
        (b"II*\x00", "TIFF", "image/tiff"),
        (b"MM\x00*", "TIFF", "image/tiff"),
        (b"PK\x03\x04", "ZIP archive", "application/zip"),
        (b"PK\x05\x06", "ZIP archive", "application/zip"),
        (b"PK\x07\x08", "ZIP archive", "application/zip"),
        (b"\x1f\x8b", "GZIP archive", "application/gzip"),
        (b"\x7fELF", "ELF executable", "application/x-elf"),
    )
    MIME_BY_EXTENSION = {
        ".pdf": ("PDF", "application/pdf"),
        ".png": ("PNG", "image/png"),
        ".jpg": ("JPEG", "image/jpeg"),
        ".jpeg": ("JPEG", "image/jpeg"),
        ".gif": ("GIF", "image/gif"),
        ".tif": ("TIFF", "image/tiff"),
        ".tiff": ("TIFF", "image/tiff"),
        ".bmp": ("BMP", "image/bmp"),
        ".webp": ("WebP", "image/webp"),
        ".heic": ("HEIC image", "image/heic"),
        ".heif": ("HEIF image", "image/heif"),
        ".avif": ("AVIF image", "image/avif"),
        ".zip": ("ZIP archive", "application/zip"),
        ".docx": ("ZIP archive", "application/zip"),
        ".xlsx": ("ZIP archive", "application/zip"),
        ".pptx": ("ZIP archive", "application/zip"),
        ".gz": ("GZIP archive", "application/gzip"),
        ".mov": ("QuickTime video", "video/quicktime"),
        ".mp4": ("MP4 video", "video/mp4"),
        ".m4v": ("MP4 video", "video/mp4"),
        ".m4a": ("M4A audio", "audio/mp4"),
        ".m4b": ("M4A audio", "audio/mp4"),
        ".m4p": ("M4A audio", "audio/mp4"),
        ".txt": ("Text", "text/plain"),
        ".md": ("Text", "text/plain"),
        ".log": ("Text", "text/plain"),
    }
    TEXT_EXTENSIONS = {".txt", ".md", ".log"}
    ISO_MEDIA_EXTENSION_TYPES = {
        ".heic": {"HEIC image", "HEIC image sequence"},
        ".heif": {"HEIF image", "HEIF image sequence", "HEIC image", "HEIC image sequence"},
        ".avif": {"AVIF image", "AVIF image sequence"},
        ".mp4": {"MP4 media", "MP4 video"},
        ".m4v": {"MP4 media", "MP4 video"},
    }

    @staticmethod
    def _validate_name(filename: str) -> str:
        if not isinstance(filename, str) or not filename or "\\" in filename or "\x00" in filename:
            raise ValueError("File name must be a non-empty relative path")
        path = PurePosixPath(filename)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in filename.split("/")):
            raise ValueError("File name must be a non-empty relative path")
        if path.parts and ":" in path.parts[0]:
            raise ValueError("Drive-qualified file names are not allowed")
        return path.as_posix()

    @classmethod
    def detect(cls, filename: str, header: bytes, file_size: int | None = None) -> dict:
        """Identify common signatures from a bounded prefix and compare known extensions."""
        safe_name = cls._validate_name(filename)
        if not isinstance(header, bytes) or len(header) > cls.MAX_HEADER_BYTES:
            raise ValueError("File header must be bytes within the supported inspection limit")
        if file_size is None:
            file_size = len(header)
        if type(file_size) is not int or file_size < len(header):
            raise ValueError("File size must be a non-negative integer covering the inspected header")

        extension = PurePosixPath(safe_name).suffix.casefold()
        if file_size == 0:
            detected_type, mime_type = "Empty file", "application/x-empty"
            extension_matches = None
        else:
            signature = cls._signature(header, file_size)
            if signature is None:
                signature = cls._text_type(header, is_truncated=file_size > len(header))
            detected_type, mime_type = signature or ("Unknown binary", "application/octet-stream")
            extension_info = cls.MIME_BY_EXTENSION.get(extension)
            if signature is not None and detected_type == "ISO base media":
                extension_matches = None
            elif signature is not None and extension in cls.ISO_MEDIA_EXTENSION_TYPES:
                extension_matches = detected_type in cls.ISO_MEDIA_EXTENSION_TYPES[extension]
            elif signature is not None and extension_info is not None:
                extension_matches = signature == extension_info
            elif signature is not None and extension in cls.TEXT_EXTENSIONS and mime_type == "text/plain":
                extension_matches = True
            elif signature is not None and extension_info is not None:
                extension_matches = False
            else:
                extension_matches = None

        return {
            "name": safe_name,
            "size_bytes": file_size,
            "extension": extension,
            "detected_type": detected_type,
            "mime_type": mime_type,
            "extension_matches": extension_matches,
            "method": cls.METHOD,
        }

    @classmethod
    def _signature(cls, header: bytes, file_size: int) -> tuple[str, str] | None:
        for magic, label, mime_type in cls.SIGNATURES:
            if header.startswith(magic):
                return label, mime_type
        if header.startswith(b"BM"):
            if len(header) >= 26:
                bitmap_size = int.from_bytes(header[2:6], "little")
                pixel_offset = int.from_bytes(header[10:14], "little")
                dib_size = int.from_bytes(header[14:18], "little")
                if (
                    dib_size >= 12
                    and 14 + dib_size <= len(header)
                    and bitmap_size >= 14 + dib_size
                    and bitmap_size <= file_size
                    and 14 + dib_size <= pixel_offset <= bitmap_size
                ):
                    return "BMP", "image/bmp"
            return "Unknown binary", "application/octet-stream"
        if len(header) >= 12 and header[:4] == b"RIFF":
            if header[8:12] == b"WEBP":
                return "WebP", "image/webp"
            if header[8:12] == b"WAVE":
                return "WAVE audio", "audio/wav"
            if header[8:12] == b"AVI ":
                return "AVI video", "video/x-msvideo"
        iso_base_media = cls._iso_base_media_type(header, file_size)
        if iso_base_media is not None:
            return iso_base_media
        if len(header) >= 4 and header[:3] == b"ID3":
            return "MP3 audio", "audio/mpeg"
        if len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0:
            return "MPEG audio", "audio/mpeg"
        return None

    @staticmethod
    def _iso_base_media_type(header: bytes, file_size: int) -> tuple[str, str] | None:
        """Recognize common ISO base-media brands without treating every ftyp as MP4."""
        if len(header) < 16 or header[4:8] != b"ftyp":
            return None

        box_size = int.from_bytes(header[:4], "big")
        if box_size == 1:
            if len(header) < 24:
                return None
            box_size = int.from_bytes(header[8:16], "big")
            brand_offset = 16
        else:
            brand_offset = 8

        if box_size < brand_offset + 8 or box_size > file_size:
            return None
        if len(header) < brand_offset + 8:
            return None

        major_brand = header[brand_offset:brand_offset + 4]
        compatible_end = min(len(header), box_size)
        compatible_brands = [
            header[offset:offset + 4]
            for offset in range(brand_offset + 8, compatible_end - 3, 4)
        ]
        brands = {major_brand, *compatible_brands}

        # Prefer a specific image/audio brand when a generic HEIF/MP4 brand is
        # also present in the compatible-brand list.
        if brands & {b"avif", b"avio"}:
            return "AVIF image", "image/avif"
        if brands & {b"avis"}:
            return "AVIF image sequence", "image/avif"
        if brands & {b"heic", b"heix"}:
            return "HEIC image", "image/heic"
        if brands & {b"hevc", b"hevx"}:
            return "HEIC image sequence", "image/heic-sequence"
        if brands & {b"mif1"}:
            return "HEIF image", "image/heif"
        if brands & {b"msf1"}:
            return "HEIF image sequence", "image/heif-sequence"
        if brands & {b"qt  "}:
            return "QuickTime video", "video/quicktime"
        if brands & {b"M4A ", b"M4B ", b"M4P "}:
            return "M4A audio", "audio/mp4"
        if b"M4V " in brands:
            return "MP4 video", "video/mp4"
        if brands & {b"isom", b"iso2", b"iso3", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"mp71", b"dash", b"avc1"}:
            # The brand identifies an MP4 media container, not necessarily a video track.
            return "MP4 media", "application/mp4"
        return "ISO base media", "application/octet-stream"

    @staticmethod
    def _text_type(header: bytes, is_truncated: bool = False) -> tuple[str, str] | None:
        if not header:
            return None
        try:
            text = header.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            if not is_truncated or error.reason != "unexpected end of data" or error.end != len(header):
                return None
            try:
                text = header[:error.start].decode("utf-8-sig")
            except UnicodeDecodeError:
                return None
        if any(ord(character) < 32 and character not in "\t\n\r\f" for character in text):
            return None
        return "Text", "text/plain"
