"""A record of each day's digest to each user, so none is sent twice."""

from typing import ClassVar

from django.conf import settings
from django.db import models


class Digest(models.Model):
    """The morning digest sent to a user on a day."""

    sent_on = models.DateField()
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="digests"
    )

    class Meta:
        ordering = ("sent_on",)
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=("sent_on", "user"), name="digest_digest_one_per_user_per_day"
            ),
        ]

    def __str__(self) -> str:
        return f"Digest for {self.user} on {self.sent_on}"
