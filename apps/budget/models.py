from typing import TYPE_CHECKING, Any, ClassVar

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.db.models.functions import Lower
from simple_history.models import HistoricalRecords

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.db.models.deletion import Collector


def _protect_unless_owner_deleted(
    collector: Collector,
    field: models.Field[Any, Any],
    sub_objs: models.QuerySet[Category],
    using: str,
) -> None:
    """PROTECT, except when the group is going away because its owner is."""
    owners = {user.pk for user in collector.data.get(get_user_model(), ())}
    cascading = sub_objs.filter(group__owner_id__in=owners)
    if cascading:
        models.CASCADE(collector, field, cascading, using)
    protected = sub_objs.exclude(pk__in=cascading.values("pk"))
    if protected:
        models.PROTECT(collector, field, protected, using)


class CategoryGroup(models.Model):
    class Kind(models.TextChoices):
        INCOME = "INCOME", "Income"
        EXPENSE = "EXPENSE", "Expense"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=7, choices=Kind)
    hidden = models.BooleanField(default=False)

    history = HistoricalRecords()
    save_without_historical_record: Callable[..., None]

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                Lower("name"), "owner", name="budget_group_owner_name_ci_unique"
            ),
        ]

    def __str__(self) -> str:
        return self.name


# Full class names, so Tailwind finds them when scanning this file.
COLOR_CLASSES = {
    "slate": "text-slate-600",
    "red": "text-red-600",
    "orange": "text-orange-600",
    "amber": "text-amber-600",
    "green": "text-green-600",
    "cyan": "text-cyan-600",
    "blue": "text-blue-600",
    "violet": "text-violet-600",
    "pink": "text-pink-600",
}


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


class Category(models.Model):
    """A budget category inside a group.

    Deferred until transactions land:
    - Deleting a category must first reassign its transactions.
    - A group's kind can't change once any of its categories has transactions.
    - Moving a category to a group of a different kind is blocked once it has
      transactions.
    """

    group = models.ForeignKey(
        CategoryGroup,
        on_delete=_protect_unless_owner_deleted,
        related_name="categories",
    )
    name = models.CharField(max_length=100)
    icon = models.CharField(max_length=64, default="tag")
    description = models.CharField(max_length=500, blank=True)
    color = models.CharField(
        max_length=16, choices=[(name, name.title()) for name in COLOR_CLASSES]
    )
    hidden = models.BooleanField(default=False)

    history = HistoricalRecords()
    save_without_historical_record: Callable[..., None]

    class Meta:
        verbose_name_plural = "categories"
        constraints: ClassVar = [
            models.UniqueConstraint(
                Lower("name"), "group", name="budget_category_group_name_ci_unique"
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def color_class(self) -> str:
        return COLOR_CLASSES[self.color]
