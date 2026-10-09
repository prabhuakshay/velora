from django.urls import path, register_converter

from apps.accounts import views


class KindConverter:
    """Match only the Account kinds that have pages."""

    regex = "expense|income"

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
]
