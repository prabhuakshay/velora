"""Writing a Transaction's Attachments to storage (ADR 0004)."""

from typing import TYPE_CHECKING

from apps.transactions.models import Attachment

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.core.files.uploadedfile import UploadedFile

    from apps.transactions.models import Transaction


def save_attachments(
    transaction: Transaction, files: Iterable[tuple[UploadedFile[bytes], str]]
) -> list[Attachment]:
    """Store each file, with its checked content type, as an Attachment.

    Call inside the database transaction that saves the Transaction, and pass
    the result to remove_files if that transaction then fails to commit. If
    storing fails partway, the files written so far are removed before the
    error propagates.
    """
    saved: list[Attachment] = []
    try:
        for upload, content_type in files:
            attachment = Attachment(
                transaction=transaction,
                original_name=upload.name or "",
                content_type=content_type,
                size=upload.size or 0,
            )
            attachment.file.save(upload.name or "", upload, save=False)
            saved.append(attachment)
            attachment.save()
    except Exception:
        remove_files(saved)
        raise
    return saved


def remove_files(attachments: Iterable[Attachment]) -> None:
    """Delete the stored files of Attachments whose rows were rolled back."""
    for attachment in attachments:
        attachment.file.delete(save=False)
