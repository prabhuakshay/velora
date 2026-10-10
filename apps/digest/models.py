"""A record of each day's digest, so it is never sent twice."""

from django.db import models


class Digest(models.Model):
    """The morning digest sent on a day."""

    sent_on = models.DateField(unique=True)

    class Meta:
        ordering = ("sent_on",)

    def __str__(self) -> str:
        return f"Digest for {self.sent_on}"
