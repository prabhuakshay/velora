"""Which files may be kept as Attachments.

A file must have an allowed extension and content that matches it, so a
renamed file can't slip into storage.
"""

import io
import zipfile
import zlib
from pathlib import PurePath
from typing import TYPE_CHECKING, NamedTuple

from django.core.exceptions import ValidationError

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.core.files.uploadedfile import UploadedFile

MAX_ATTACHMENTS = 10
MB = 1024 * 1024
MAX_TOTAL_MB = 10
MAX_TOTAL_BYTES = MAX_TOTAL_MB * MB
# The headroom above the total covers the other form fields and multipart framing.
MAX_REQUEST_BYTES = MAX_TOTAL_BYTES + 2 * MB

HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}


def _is_heic(data: bytes) -> bool:
    return data[4:8] == b"ftyp" and data[8:12] in HEIC_BRANDS


def _is_webp(data: bytes) -> bool:
    return data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def _is_text(data: bytes) -> bool:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    return "\x00" not in text


def _zip_start(data: bytes, name: str) -> bytes | None:
    """The start of the named file inside a zip archive, if the data has it."""
    # Only the start is read, so a zip bomb is never fully unpacked.
    try:
        with (
            zipfile.ZipFile(io.BytesIO(data)) as archive,
            archive.open(name) as member,
        ):
            return member.read(100)
    except (
        zipfile.BadZipFile,
        KeyError,
        # Encrypted members, unsupported compression and corrupt data.
        RuntimeError,
        NotImplementedError,
        EOFError,
        zlib.error,
    ):
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
    """An allowed type: its content type and how to recognise its content.

    Inline types open in the browser; the rest are downloaded.
    """

    content_type: str
    matches: Callable[[bytes], bool]
    inline: bool = False


JPEG = FileType(
    "image/jpeg", lambda data: data.startswith(b"\xff\xd8\xff"), inline=True
)

FILE_TYPES = {
    ".jpg": JPEG,
    ".jpeg": JPEG,
    ".png": FileType(
        "image/png", lambda data: data.startswith(b"\x89PNG"), inline=True
    ),
    ".webp": FileType("image/webp", _is_webp, inline=True),
    ".heic": FileType("image/heic", _is_heic, inline=True),
    ".gif": FileType(
        "image/gif", lambda data: data[:6] in {b"GIF87a", b"GIF89a"}, inline=True
    ),
    ".pdf": FileType(
        "application/pdf", lambda data: data.startswith(b"%PDF"), inline=True
    ),
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


INLINE_CONTENT_TYPES = {
    file_type.content_type for file_type in FILE_TYPES.values() if file_type.inline
}


def checked_content_type(upload: UploadedFile[bytes]) -> str:
    """The content type of a file that may be kept as an Attachment.

    It comes from the file's allowed type, not the browser. Raises
    ValidationError saying why a file may not be kept.
    """
    name = upload.name or ""
    file_type = FILE_TYPES.get(PurePath(name).suffix.lower())
    if file_type is None:
        msg = f"{name} isn't a file type you can attach."
        raise ValidationError(msg)
    upload.seek(0)
    data = upload.read()
    upload.seek(0)
    if not file_type.matches(data):
        msg = f"{name} doesn't contain what its file type says."
        raise ValidationError(msg)
    return file_type.content_type
