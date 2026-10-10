"""Merge one Account into another of the same kind."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction as db_transaction
from django.db.models import Q

from apps.accounts.models import Account
from apps.core.history import with_reason
from apps.quick_add.models import DraftSplit
from apps.schedules.models import ScheduleSplit
from apps.transactions.models import Split, Transaction

if TYPE_CHECKING:
    from django.db.models import QuerySet


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

    @property
    def refusal(self) -> str:
        """Why the merge can't go ahead; empty when it can."""
        if self._is_card(self.source) and self._is_card(self.target):
            return (
                f"{self.source} and {self.target} are both credit cards, so "
                "their Statements would clash. Clear one's card settings and "
                "Statements first."
            )
        return ""

    @staticmethod
    def _is_card(account: Account) -> bool:
        return account.is_card or account.statements.exists()

    def run(self) -> None:
        """Repoint every Split, Draft, Schedule Split and card, then remove the source.

        Saves and deletes row by row so change history records each one.
        """
        if self.refusal:
            raise ValueError(self.refusal)
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
            self._repoint_schedule_splits(reason)
            self._move_card(reason)
            if target.has_opening_balance:
                # Both are set for these kinds, by a constraint mypy cannot see.
                target.opening_balance += source.opening_balance  # type: ignore[operator]
                target.opening_balance_date = min(
                    target.opening_balance_date,  # type: ignore[type-var]
                    source.opening_balance_date,
                )
                with_reason(target, reason).save()
            with_reason(source, reason).delete()

    def _move_card(self, reason: str) -> None:
        """Hand the source's card settings, Statements and paid cards to the target."""
        source, target = self.source, self.target
        for card in Account.objects.filter(pays_from=source):
            card.pays_from = target
            with_reason(card, reason).save()
        source.statements.update(card=target)
        if source.is_card:
            target.statement_day = source.statement_day
            target.due_day = source.due_day
            target.pays_from = source.pays_from
            with_reason(target, reason).save()

    def _repoint_schedule_splits(self, reason: str) -> None:
        """Point Schedule Splits at the target, dropping any it would loop to."""
        source, target = self.source, self.target
        for split in ScheduleSplit.objects.filter(
            Q(from_account=source) | Q(to_account=source)
        ):
            if split.from_account_id == source.pk:
                split.from_account = target
            if split.to_account_id == source.pk:
                split.to_account = target
            if split.from_account_id == split.to_account_id:
                with_reason(split, reason).delete()
            else:
                with_reason(split, reason).save()
