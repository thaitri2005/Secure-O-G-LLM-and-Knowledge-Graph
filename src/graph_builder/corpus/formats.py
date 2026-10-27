"""Identify a file's format from its bytes, and reject inputs the pipeline cannot read safely."""
from __future__ import annotations

from pathlib import Path
import zipfile

# format -> (paginated, media type)
FORMATS = {
    "pdf": (True, "application/pdf"),
    "image": (True, "image/*"),
    "docx": (False, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "pptx": (True, "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    "xlsx": (False, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "html": (False, "text/html"),
    "markdown": (False, "text/markdown"),
    "text": (False, "text/plain"),
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
TEXT_SUFFIXES = {".md": "markdown", ".markdown": "markdown", ".txt": "text", ".html": "html", ".htm": "html"}


class UnsupportedFormat(ValueError):
    pass


def detect_format(path: Path) -> str:
    """Return a key of FORMATS, or raise UnsupportedFormat with a reason a user can act on."""
    with path.open("rb") as stream:
        head = stream.read(4096)
    suffix = path.suffix.lower()
    if head.startswith(b"%PDF-") or b"%PDF-" in head[:1024]:
        return "pdf"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        raise UnsupportedFormat("legacy Office binary (.doc/.xls/.ppt); save it as .docx/.xlsx/.pptx or PDF first")
    if head.startswith(b"PK"):
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile as error:
            raise UnsupportedFormat(f"damaged ZIP container: {error}") from error
        if "[Content_Types].xml" in names:
            for prefix, kind in (("word/", "docx"), ("ppt/", "pptx"), ("xl/", "xlsx")):
                if any(name.startswith(prefix) for name in names):
                    return kind
        raise UnsupportedFormat("ZIP archive; extract it and add the files inside")
    if suffix in IMAGE_SUFFIXES or head[:8] in (b"\x89PNG\r\n\x1a\n",) or head[:3] == b"\xff\xd8\xff" \
            or head[:4] in (b"II*\x00", b"MM\x00*"):
        from PIL import Image
        try:
            with Image.open(path) as image:
                image.verify()
        except Exception as error:  # Pillow raises many exception types for corrupt images
            raise UnsupportedFormat(f"unreadable image: {error}") from error
        return "image"
    if suffix in TEXT_SUFFIXES:
        try:
            head.decode("utf-8")
        except UnicodeDecodeError as error:
            # A multibyte character may straddle the 4096-byte boundary; check the whole file once.
            try:
                path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                raise UnsupportedFormat("text file is not UTF-8; convert it to UTF-8 first") from error
        return TEXT_SUFFIXES[suffix]
    raise UnsupportedFormat(f"unrecognized format ({suffix or 'no extension'})")


def page_count(path: Path, kind: str) -> int | None:
    if kind == "pdf":
        import pypdfium2
        with pypdfium2.PdfDocument(path) as pdf:
            return len(pdf)
    if kind == "image":
        from PIL import Image
        with Image.open(path) as image:
            return getattr(image, "n_frames", 1)
    return None


def check_pdf(path: Path) -> None:
    """Reject encrypted or unparseable PDFs before they reach the converter."""
    import pypdfium2
    try:
        with pypdfium2.PdfDocument(path) as pdf:
            if len(pdf) == 0:
                raise UnsupportedFormat("PDF has no pages")
    except pypdfium2.PdfiumError as error:
        raise UnsupportedFormat(f"PDF cannot be opened (encrypted or damaged): {error}") from error
