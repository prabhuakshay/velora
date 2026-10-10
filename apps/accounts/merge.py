"""Merge one Account into another of the same kind."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction as db_transaction
from django.db.models import Q

from apps.core.history import with_reason
from apps.quick_add.models import DraftSplit
from apps.transactions.models import Split, Transaction

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from apps.accounts.models import Account


@dataclass
class AccountMerge:
    """What merging source into target does, and doing it."""

    source: Account
    target: Account

    @property
    def self_splits(self) -> QuerySet[Split]:
        """Splits that would go from the target to itself."""
        source, target = self.source, self.target
        return Split.objects.filter(
            Q(from_account=source, to_account=target)
            | Q(from_account=target, to_account=source)
        )

    @property
    def moved_splits(self) -> QuerySet[Split]:
        """Splits of the source that survive and point at the target."""
        return Split.objects.filter(
            Q(from_account=self.source) | Q(to_account=self.source)
        ).exclude(pk__in=self.self_splits)

    @property
    def emptied_transactions(self) -> QuerySet[Transaction]:
        """Transactions whose every Split is a self-Split."""
        return (
            Transaction.objects.filter(splits__in=self.self_splits)
            .exclude(splits__in=Split.objects.exclude(pk__in=self.self_splits))
            .distinct()
        )

    def run(self) -> None:
        """Repoint the source's Splits and Draft Splits, then remove the source.

        Saves and deletes row by row so change history records each one.
        """
        source, target = self.source, self.target
        reason = f"Merged {source} into {target}"
        with db_transaction.atomic():
            emptied = list(self.emptied_transactions)
            for split in self.self_splits:
                with_reason(split, reason).delete()
            for transaction in emptied:
                with_reason(transaction, reason).delete()
            for split in self.moved_splits:
                if split.from_account_id == source.pk:
                    split.from_account = target
                if split.to_account_id == source.pk:
                    split.to_account = target
                with_reason(split, reason).save()
            DraftSplit.objects.filter(from_account=source).update(from_account=target)
            DraftSplit.objects.filter(to_account=source).update(to_account=target)
            if target.has_opening_balance:
                # Both are set for these kinds, by a constraint mypy cannot see.
                target.opening_balance += source.opening_balance  # type: ignore[operator]
                target.opening_balance_date = min(
                    target.opening_balance_date,  # type: ignore[type-var]
                    source.opening_balance_date,
                )
                with_reason(target, reason).save()
            with_reason(source, reason).delete()
