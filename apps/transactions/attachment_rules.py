"""Which files may be kept as Attachments.

A file must have an allowed extension and content that matches it, so a
renamed file can't slip into storage.
"""

import io
import zipfile
from pathlib import PurePath
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.core.files.uploadedfile import UploadedFile

MAX_SIZE_MB = 20
MAX_ATTACHMENTS = 10

HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}


def _is_heic(data: bytes) -> bool:
    return data[4:8] == b"ftyp" and data[8:12] in HEIC_BRANDS


def _is_webp(data: bytes) -> bool:
    return data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def _is_text(data: bytes) -> bool:
    # Text must not be markup, so a browser can never render it as HTML or SVG.
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    return "\x00" not in text and not text.lstrip().startswith("<")


def _zip_start(data: bytes, name: str) -> bytes | None:
    """The start of the named file inside a zip archive, if the data has it."""
    # Only the start is read, so a zip bomb is never fully unpacked.
    try:
        with (
            zipfile.ZipFile(io.BytesIO(data)) as archive,
            archive.open(name) as member,
        ):
            return member.read(100)
    except zipfile.BadZipFile, KeyError:
        return None


def _has_member(name: str) -> Callable[[bytes], bool]:
    return lambda data: _zip_start(data, name) is not None


def _opendocument(content_type: str) -> FileType:
    # OpenDocument files name their own type in a "mimetype" member.
    return FileType(
        content_type,
        lambda data: _zip_start(data, "mimetype") == content_type.encode(),
    )


class FileType(NamedTuple):
    """An allowed type: its content type and how to recognise its content."""

    content_type: str
    matches: Callable[[bytes], bool]


JPEG = FileType("image/jpeg", lambda data: data.startswith(b"\xff\xd8\xff"))

FILE_TYPES = {
    ".jpg": JPEG,
    ".jpeg": JPEG,
    ".png": FileType("image/png", lambda data: data.startswith(b"\x89PNG")),
    ".webp": FileType("image/webp", _is_webp),
    ".heic": FileType("image/heic", _is_heic),
    ".gif": FileType("image/gif", lambda data: data[:6] in {b"GIF87a", b"GIF89a"}),
    ".pdf": FileType("application/pdf", lambda data: data.startswith(b"%PDF")),
    ".txt": FileType("text/plain", _is_text),
    ".md": FileType("text/markdown", _is_text),
    ".csv": FileType("text/csv", _is_text),
    ".docx": FileType(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        _has_member("word/document.xml"),
    ),
    ".xlsx": FileType(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        _has_member("xl/workbook.xml"),
    ),
    ".odt": _opendocument("application/vnd.oasis.opendocument.text"),
    ".ods": _opendocument("application/vnd.oasis.opendocument.spreadsheet"),
}


def _file_type(name: str) -> FileType | None:
    return FILE_TYPES.get(PurePath(name).suffix.lower())


def content_type(upload: UploadedFile[bytes]) -> str:
    """The content type of an allowed file, from its type rather than the browser."""
    file_type = _file_type(upload.name or "")
    return file_type.content_type if file_type else ""


def attachment_error(upload: UploadedFile[bytes]) -> str | None:
    """Why this file may not be kept as an Attachment, if it may not."""
    name = upload.name or ""
    file_type = _file_type(name)
    if file_type is None:
        return f"{name} isn't a file type you can attach."
    if (upload.size or 0) > MAX_SIZE_MB * 1024 * 1024:
        return f"{name} is over {MAX_SIZE_MB} MB, the most an Attachment can be."
    upload.seek(0)
    data = upload.read()
    upload.seek(0)
    if not file_type.matches(data):
        return f"{name} doesn't contain what its file type says."
    return None
