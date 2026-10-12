from django.apps import AppConfig
from django.db.models.signals import post_delete


class TransactionsConfig(AppConfig):
    name = "apps.transactions"
    label = "transactions"

    def ready(self) -> None:
        from apps.transactions.models import Attachment  # noqa: PLC0415
        from apps.transactions.signals import queue_file_delete  # noqa: PLC0415

        post_delete.connect(queue_file_delete, sender=Attachment)
