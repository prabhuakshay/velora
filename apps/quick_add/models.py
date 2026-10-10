"""Drafts, the Quick Adds the AI drafts them from, and the AI calls made."""

from datetime import timedelta
from decimal import Decimal
from typing import ClassVar

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.accounts.models import Account
from apps.classification.models import Party
from apps.transactions.models import Transaction
from apps.transactions.split_rules import known_total

MAX_TEXT_LENGTH = 500
# A new Party name must fit the Party it becomes.
PARTY_NAME_MAX_LENGTH: int = Party._meta.get_field("name").max_length  # type: ignore[assignment]
# Longer than a job's three AI calls and their backoff, so only a job that
# was killed mid-call leaves its Quick Add processing this long.
STALL_AFTER = timedelta(minutes=5)


class QuickAddQuerySet(models.QuerySet["QuickAdd"]):
    """Queries over Quick Adds."""

    def unfinished(self) -> QuickAddQuerySet:
        """The Quick Adds with no Draft yet: processing or failed."""
        return self.filter(
            status__in=[QuickAdd.Status.PROCESSING, QuickAdd.Status.FAILED]
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
    # Reset on a retry; created_at stays, as it dates the Draft.
    processing_since = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=16, choices=Status, default=Status.PROCESSING)
    failure_reason = models.TextField(blank=True)
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
    def is_stalled(self) -> bool:
        """Whether it has been processing too long to still be worked on."""
        return (
            self.is_processing and timezone.now() - self.processing_since > STALL_AFTER
        )

    @property
    def is_failed(self) -> bool:
        """Whether the AI couldn't turn it into a Draft."""
        return self.status == QuickAdd.Status.FAILED

    def reject(self) -> None:
        """Mark it rejected: kept, but off the Drafts page."""
        self.status = QuickAdd.Status.REJECTED
        self.save(update_fields=["status"])


class DraftQuerySet(models.QuerySet["Draft"]):
    """Queries over Drafts."""

    def waiting(self) -> DraftQuerySet:
        """The Drafts neither posted nor rejected yet."""
        return self.filter(status=Draft.Status.WAITING)


class Draft(models.Model):
    """A Transaction not yet posted; it touches no Balance (ADR 0006)."""

    class Source(models.TextChoices):
        QUICK_ADD = "quick_add", "Quick Add"
        SCHEDULE = "schedule", "Schedule"
        MANUAL = "manual", "Manual"
        STATEMENT = "statement", "Statement"
        CARD_EMI = "card_emi", "Card EMI"

    class Status(models.TextChoices):
        WAITING = "waiting"
        POSTED = "posted"
        REJECTED = "rejected"

    source = models.CharField(max_length=16, choices=Source)
    quick_add = models.OneToOneField(
        QuickAdd,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="draft",
    )
    occurrence = models.OneToOneField(
        "schedules.Occurrence",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="draft",
    )
    statement = models.OneToOneField(
        "cards.Statement",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="draft",
    )
    card_emi = models.ForeignKey(
        "cards.CardEMI",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="drafts",
    )
    # Which of the Card EMI's installments it records the interest of.
    installment = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.WAITING)
    created_at = models.DateTimeField(auto_now_add=True)
    # Why the last try to post it unchanged was refused.
    posting_error = models.TextField(blank=True)
    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="draft",
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
    # An open-amount Schedule's Draft guessed from the last amount paid.
    estimated = models.BooleanField(default=False)

    objects = DraftQuerySet.as_manager()

    class Meta:
        ordering = ("created_at", "pk")
        indexes: ClassVar = [models.Index(fields=["status"])]
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=models.Q(source="quick_add", quick_add__isnull=False)
                | (~models.Q(source="quick_add") & models.Q(quick_add__isnull=True)),
                name="quick_add_draft_quick_add_iff_source",
                violation_error_message=(
                    "Only a Draft from a Quick Add links to a Quick Add."
                ),
            ),
            models.CheckConstraint(
                condition=models.Q(source="schedule", occurrence__isnull=False)
                | (~models.Q(source="schedule") & models.Q(occurrence__isnull=True)),
                name="quick_add_draft_occurrence_iff_source",
                violation_error_message=(
                    "Only a Draft from a Schedule links to an Occurrence."
                ),
            ),
            models.CheckConstraint(
                condition=models.Q(source="statement", statement__isnull=False)
                | (~models.Q(source="statement") & models.Q(statement__isnull=True)),
                name="quick_add_draft_statement_iff_source",
                violation_error_message=(
                    "Only a card payment Draft links to a Statement."
                ),
            ),
            models.CheckConstraint(
                condition=models.Q(
                    source="card_emi", card_emi__isnull=False, installment__isnull=False
                )
                | (
                    ~models.Q(source="card_emi")
                    & models.Q(card_emi__isnull=True, installment__isnull=True)
                ),
                name="quick_add_draft_card_emi_iff_source",
                violation_error_message=(
                    "Only a Card EMI Draft links to a Card EMI installment."
                ),
            ),
            models.UniqueConstraint(
                fields=("card_emi", "installment"),
                name="quick_add_draft_one_per_card_emi_installment",
            ),
            models.CheckConstraint(
                condition=models.Q(party__isnull=True) | models.Q(new_party_name=""),
                name="quick_add_draft_one_party",
                violation_error_message=(
                    "A Draft has an existing Party or a new Party name, not both."
                ),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_source_display()} Draft for {self.date}"

    @property
    def amount(self) -> Decimal | None:
        """What it moves, or None while any Split's amount is missing."""
        return known_total(split.amount for split in self.splits.all())

    @property
    def label(self) -> str:
        """How it is named in lists: its description, else its Party."""
        return self.description or str(self.party or self.new_party_name or self)

    def mark_posted(self, transaction: Transaction, *, without_edits: bool) -> None:
        """Link the Draft to the Transaction it became.

        Its Occurrence is Paid, or its Statement settled, by that Transaction.
        """
        self.status = Draft.Status.POSTED
        self.transaction = transaction
        self.posting_error = ""
        self.save(update_fields=["status", "transaction", "posting_error"])
        if self.quick_add:
            self.quick_add.status = QuickAdd.Status.POSTED
            self.quick_add.posted_without_edits = without_edits
            self.quick_add.save(update_fields=["status", "posted_without_edits"])
        if self.occurrence:
            self.occurrence.settle(transaction)
        if self.statement:
            self.statement.transaction = transaction
            self.statement.save(update_fields=["transaction"])

    def reject(self) -> None:
        """Mark it rejected, and its Occurrence Skipped, never Missed."""
        self.status = Draft.Status.REJECTED
        self.save(update_fields=["status"])
        if self.quick_add:
            self.quick_add.reject()
        if self.occurrence:
            self.occurrence.settle(None)


class DraftSplit(models.Model):
    """One proposed Split of a Draft."""

    draft = models.ForeignKey(Draft, on_delete=models.CASCADE, related_name="splits")
    # Merging repoints it; any other removal leaves a gap, so posting fails
    # instead of the Split silently vanishing from the Draft.
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
    # Left blank until the user knows it; posting refuses the gap.
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
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
