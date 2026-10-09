"""Writing a Transaction's Attachments to storage (ADR 0004)."""

import inspect
from typing import TYPE_CHECKING

from django.db import transaction as db_transaction
from django.utils.http import content_disposition_header

from apps.transactions.models import Attachment

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from django.core.files.uploadedfile import UploadedFile
    from django.db.models.fields.files import FieldFile

    from apps.transactions.models import Transaction

STORAGE_DELETE_FAILED = (
    "Couldn't remove attachments from storage; nothing was deleted. Try again."
)


def attachment_url(attachment: Attachment) -> str:
    """A storage link that shows images and PDFs inline and downloads the rest.

    Backends that sign their links, like S3/R2 presigned URLs, take the
    response headers as ``parameters``; others can't set headers and get the
    bare link.
    """
    url: Callable[..., str] = attachment.file.storage.url
    if "parameters" not in inspect.signature(url).parameters:
        return url(attachment.file.name)
    inline = attachment.is_image or attachment.content_type == "application/pdf"
    return url(
        attachment.file.name,
        parameters={
            "ResponseContentDisposition": content_disposition_header(
                as_attachment=not inline, filename=attachment.original_name
            ),
            # Keys carry no extension, so the stored object's type can't be trusted.
            "ResponseContentType": attachment.content_type,
        },
    )


def save_attachments(
    transaction: Transaction, files: Iterable[UploadedFile[bytes]]
) -> None:
    """Store each file as an Attachment of the Transaction.

    Call inside the database transaction that saves the Transaction. If
    anything fails, the files written so far are deleted before the error
    propagates, so the rollback leaves no stray files in storage.
    """
    written: list[FieldFile] = []
    try:
        for upload in files:
            attachment = Attachment(
                transaction=transaction,
                original_name=upload.name or "",
                content_type=upload.content_type or "",
                size=upload.size or 0,
            )
            # Writes the file under a key from attachment_key.
            attachment.file.save(upload.name or "", upload, save=False)
            written.append(attachment.file)
            attachment.save()
    except Exception:
        for file in written:
            file.delete(save=False)
        raise


def delete_attachment(attachment: Attachment) -> None:
    """Delete the Attachment and its stored file, or neither.

    The file goes last, inside the database transaction, so a storage
    failure rolls the row back. Storages treat a missing file as deleted,
    so a delete that failed partway can be retried.
    """
    with db_transaction.atomic():
        attachment.delete()
        attachment.file.delete(save=False)
