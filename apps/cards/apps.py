from django.apps import AppConfig
from django.db.models.signals import post_delete, post_save, pre_delete


class CardsConfig(AppConfig):
    name = "apps.cards"
    label = "cards"

    def ready(self) -> None:
        from apps.cards.models import Statement  # noqa: PLC0415
        from apps.cards.signals import (  # noqa: PLC0415
            note_touched_accounts,
            refresh_after_payment,
            refresh_cards,
            refresh_deleted_cards,
            reopen_statement,
        )
        from apps.transactions.models import Transaction  # noqa: PLC0415
        from apps.transactions.signals import splits_saved  # noqa: PLC0415

        pre_delete.connect(reopen_statement, sender=Transaction)
        pre_delete.connect(note_touched_accounts, sender=Transaction)
        post_delete.connect(refresh_deleted_cards, sender=Transaction)
        splits_saved.connect(refresh_cards, sender=Transaction)
        post_save.connect(refresh_after_payment, sender=Statement)
