"""Transactions: real-world money events made of Splits."""

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, ClassVar

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.http import content_disposition_header
from simple_history.models import HistoricalRecords

from apps.accounts.models import Account
from apps.classification.models import Party, Tag
from apps.transactions.attachment_rules import INLINE_CONTENT_TYPES

if TYPE_CHECKING:
    from collections.abc import Callable


class Transaction(models.Model):
    """One real-world money event, with a date and optionally a Party."""

    date = models.DateField()
    party = models.ForeignKey(
        Party,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="transactions",
    )
    description = models.TextField(blank=True)

    history = HistoricalRecords()
    save_without_historical_record: Callable[..., None]

    class Meta:
        indexes: ClassVar = [models.Index(fields=["date"])]

    def __str__(self) -> str:
        return f"{self.date} {self.description or self.party or ''}".strip()


class Split(models.Model):
    """A positive amount moving from one Account to another (ADR 0003)."""

    transaction = models.ForeignKey(
        Transaction, on_delete=models.CASCADE, related_name="splits"
    )
    from_account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="splits_out"
    )
    to_account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="splits_in"
    )
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="splits")

    history = HistoricalRecords(m2m_fields=[tags])
    save_without_historical_record: Callable[..., None]

    class Meta:
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="transactions_split_amount_positive",
                violation_error_message="Amount must be greater than zero.",
            ),
            models.CheckConstraint(
                condition=~models.Q(from_account=models.F("to_account")),
                name="transactions_split_accounts_differ",
                violation_error_message="A Split cannot go from an Account to itself.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.from_account} to {self.to_account}: {self.amount}"


def attachment_key(_attachment: Attachment, _filename: str) -> str:
    """A random storage key, so files can be moved later without renaming."""
    return f"attachments/{uuid.uuid4().hex}"


class Attachment(models.Model):
    """A file kept with a Transaction, such as a receipt (ADR 0004)."""

    transaction = models.ForeignKey(
        Transaction, on_delete=models.CASCADE, related_name="attachments"
    )
    file = models.FileField(upload_to=attachment_key)
    # Only used as the download name; the storage key never derives from it.
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "pk")

    def __str__(self) -> str:
        return self.original_name

    @property
    def is_image(self) -> bool:
        """Whether the edit page can show the Attachment as a preview."""
        return (
            self.content_type.startswith("image/")
            and self.content_type in INLINE_CONTENT_TYPES
        )

    def presigned_url(self) -> str:
        """A short-lived link that opens images and PDFs and downloads the rest."""
        url: Callable[..., str] = self.file.storage.url
        return url(
            self.file.name,
            parameters={
                "ResponseContentDisposition": content_disposition_header(
                    as_attachment=self.content_type not in INLINE_CONTENT_TYPES,
                    filename=self.original_name,
                ),
                # Keys carry no extension, so the stored object's type can't be trusted.
                "ResponseContentType": self.content_type,
            },
        )
