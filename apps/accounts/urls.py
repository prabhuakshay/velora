from django.urls import path, register_converter

from apps.accounts import views
from apps.accounts.models import Account


class KindConverter:
    """Match only the Account kinds that have pages."""

    regex = "|".join(Account.Kind.values)

    def to_python(self, value: str) -> str:
        return value

    def to_url(self, value: str) -> str:
        return value


register_converter(KindConverter, "kind")

urlpatterns = [
    path("accounts/<kind:kind>/", views.account_list, name="account_list"),
    path("accounts/<kind:kind>/new/", views.account_create, name="account_create"),
    path(
        "accounts/<kind:kind>/<int:pk>/edit/",
        views.account_edit,
        name="account_edit",
    ),
    path(
        "accounts/<kind:kind>/<int:pk>/hide/",
        views.account_hide,
        name="account_hide",
    ),
    path(
        "accounts/<kind:kind>/<int:pk>/unhide/",
        views.account_unhide,
        name="account_unhide",
    ),
    path(
        "accounts/<kind:kind>/<int:pk>/merge/",
        views.account_merge,
        name="account_merge",
    ),
    path(
        "accounts/<kind:kind>/<int:pk>/delete/",
        views.account_delete,
        name="account_delete",
    ),
]
