from django.apps import AppConfig
from django.db.models.signals import pre_delete


class CardsConfig(AppConfig):
    name = "apps.cards"
    label = "cards"

    def ready(self) -> None:
        from apps.cards.signals import reopen_statement  # noqa: PLC0415
        from apps.transactions.models import Transaction  # noqa: PLC0415

        pre_delete.connect(reopen_statement, sender=Transaction)
