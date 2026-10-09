"""The private Cloudflare R2 bucket that holds Attachments (ADR 0004)."""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from storages.backends.s3 import S3Storage


class R2Storage(S3Storage):
    """S3 storage pointed at R2, handing out short-lived presigned links."""

    def __init__(self, **options: object) -> None:
        missing = [
            var
            for option, var in settings.R2_ENV_VARS.items()
            if not options.get(option)
        ]
        if missing:
            msg = f"Attachment storage needs {', '.join(missing)} to be set."
            raise ImproperlyConfigured(msg)
        super().__init__(
            **{
                # R2 has a single region and no ACLs; the bucket itself is private.
                "region_name": "auto",
                "signature_version": "s3v4",
                # Keeps links on the endpoint's origin, which the CSP allows.
                "addressing_style": "path",
                "querystring_auth": True,
                "querystring_expire": 300,
                **options,
            }
        )
