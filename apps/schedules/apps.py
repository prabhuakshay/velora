from django.apps import AppConfig
from django.db.models.signals import pre_delete


class SchedulesConfig(AppConfig):
    name = "apps.schedules"
    label = "schedules"

    def ready(self) -> None:
        from apps.schedules.signals import reopen_occurrence  # noqa: PLC0415
        from apps.transactions.models import Transaction  # noqa: PLC0415

        pre_delete.connect(reopen_occurrence, sender=Transaction)
