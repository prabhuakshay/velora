"""Writing a Transaction's Attachments to storage (ADR 0004)."""

from typing import TYPE_CHECKING

from django.utils.http import content_disposition_header

from apps.transactions.models import Attachment

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from django.core.files.uploadedfile import UploadedFile
    from django.db.models.fields.files import FieldFile

    from apps.transactions.models import Transaction


def attachment_url(attachment: Attachment) -> str:
    """A presigned link that shows images and PDFs inline and downloads the rest.

    R2 sets the response headers named in ``parameters`` when serving the link.
    """
    url: Callable[..., str] = attachment.file.storage.url
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
