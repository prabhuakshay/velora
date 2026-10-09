"""Quick Adds, the Drafts the AI proposes from them, and the AI calls made."""

from decimal import Decimal
from typing import ClassVar

from django.core.validators import MinValueValidator
from django.db import models

from apps.accounts.models import Account
from apps.classification.models import Party
from apps.transactions.models import Transaction

MAX_TEXT_LENGTH = 500
# A new Party name must fit the Party it becomes.
PARTY_NAME_MAX_LENGTH: int = Party._meta.get_field("name").max_length  # type: ignore[assignment]


class QuickAddQuerySet(models.QuerySet["QuickAdd"]):
    """Queries over Quick Adds."""

    def on_drafts_page(self) -> QuickAddQuerySet:
        """The Quick Adds that still need the user: processing, draft or failed."""
        return self.filter(
            status__in=[
                QuickAdd.Status.PROCESSING,
                QuickAdd.Status.DRAFT,
                QuickAdd.Status.FAILED,
            ]
        )


class QuickAdd(models.Model):
    """What the user wrote about one money event, for the AI to draft."""

    class Status(models.TextChoices):
        PROCESSING = "processing"
        DRAFT = "draft"
        FAILED = "failed"
        POSTED = "posted"
        REJECTED = "rejected"

    text = models.CharField(max_length=MAX_TEXT_LENGTH)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.PROCESSING)
    failure_reason = models.TextField(blank=True)
    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quick_add",
    )
    posted_without_edits = models.BooleanField(default=False)

    objects = QuickAddQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at", "-pk")

    def __str__(self) -> str:
        return self.text

    @property
    def is_processing(self) -> bool:
        """Whether the AI is still working on it."""
        return self.status == QuickAdd.Status.PROCESSING

    @property
    def is_failed(self) -> bool:
        """Whether the AI couldn't turn it into a Draft."""
        return self.status == QuickAdd.Status.FAILED

    def reject(self) -> None:
        """Mark it rejected: kept, but off the Drafts page."""
        self.status = QuickAdd.Status.REJECTED
        self.save(update_fields=["status"])


class Draft(models.Model):
    """A Transaction the AI proposed; it touches no Balance (ADR 0006)."""

    quick_add = models.OneToOneField(
        QuickAdd, on_delete=models.CASCADE, related_name="draft"
    )
    date = models.DateField()
    # Merging the Party repoints the Draft and deleting it is refused, so
    # the Party never silently drops out of the Draft.
    party = models.ForeignKey(
        Party,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="drafts",
    )
    # A Party the AI suggests; created only when the Draft is posted.
    new_party_name = models.CharField(max_length=PARTY_NAME_MAX_LENGTH, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=models.Q(party__isnull=True) | models.Q(new_party_name=""),
                name="quick_add_draft_one_party",
                violation_error_message=(
                    "A Draft has an existing Party or a new Party name, not both."
                ),
            ),
        ]

    def __str__(self) -> str:
        return f"Draft of {self.quick_add}"


class DraftSplit(models.Model):
    """One proposed Split of a Draft."""

    draft = models.ForeignKey(Draft, on_delete=models.CASCADE, related_name="splits")
    # Kept as a gap when the Account is merged away, so posting fails instead
    # of the Split silently vanishing from the Draft.
    from_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        related_name="draft_splits_out",
    )
    to_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        related_name="draft_splits_in",
    )
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )

    class Meta:
        ordering = ("pk",)

    def __str__(self) -> str:
        return f"{self.from_account} to {self.to_account}: {self.amount}"


class AICall(models.Model):
    """One request to OpenRouter and what it cost, from the reply's usage."""

    quick_add = models.ForeignKey(
        QuickAdd, on_delete=models.CASCADE, related_name="ai_calls"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    model = models.CharField(max_length=200)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    # USD, not a Transaction, so ADR 0002 (INR-only) doesn't apply.
    cost = models.DecimalField(max_digits=12, decimal_places=8, default=Decimal(0))
    succeeded = models.BooleanField(default=False)

    class Meta:
        verbose_name = "AI call"

    def __str__(self) -> str:
        return f"{self.model} for {self.quick_add_id}"
