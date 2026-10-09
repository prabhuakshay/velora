"""Classification models: parties and tags."""

from typing import TYPE_CHECKING, ClassVar

from django.db import models, transaction
from django.db.models.functions import Lower
from simple_history.models import HistoricalRecords

if TYPE_CHECKING:
    from collections.abc import Callable


# Full class names, so Tailwind finds them when scanning this file.
SWATCH_CLASSES = {
    "slate": "bg-slate-600",
    "red": "bg-red-600",
    "orange": "bg-orange-600",
    "amber": "bg-amber-600",
    "green": "bg-green-600",
    "cyan": "bg-cyan-600",
    "blue": "bg-blue-600",
    "violet": "bg-violet-600",
    "pink": "bg-pink-600",
}


class Party(models.Model):
    """Someone outside the user who money is paid to or received from."""

    name = models.CharField(max_length=100)
    notes = models.TextField(blank=True)
    hidden = models.BooleanField(default=False)

    history = HistoricalRecords()
    save_without_historical_record: Callable[..., None]

    class Meta:
        verbose_name_plural = "parties"
        constraints: ClassVar = [
            models.UniqueConstraint(
                Lower("name"), name="classification_party_name_ci_unique"
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @transaction.atomic
    def merge_into(self, target: Party) -> None:
        """Point every Transaction at the target, then delete this Party."""
        # Saved one by one, not with update(), so change history records each.
        for money_event in self.transactions.all():
            money_event.party = target
            money_event.save()
        self.delete()


class Tag(models.Model):
    """A free-form label for grouping money movements."""

    name = models.CharField(max_length=100)
    color = models.CharField(
        max_length=16,
        choices=[(name, name.title()) for name in SWATCH_CLASSES],
        default="slate",
    )
    hidden = models.BooleanField(default=False)

    history = HistoricalRecords()
    save_without_historical_record: Callable[..., None]

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                Lower("name"), name="classification_tag_name_ci_unique"
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def swatch_class(self) -> str:
        """Tailwind background class for the tag's colour."""
        return SWATCH_CLASSES[self.color]
