from django.apps import AppConfig
from django.contrib.auth.signals import user_logged_in

from apps.users.signals import update_last_login_without_history


class UsersConfig(AppConfig):
    name = "apps.users"
    label = "users"

    def ready(self) -> None:
        # Same dispatch_uid replaces Django's handler instead of running both.
        user_logged_in.disconnect(dispatch_uid="update_last_login")
        user_logged_in.connect(
            update_last_login_without_history, dispatch_uid="update_last_login"
        )
