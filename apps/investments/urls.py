from django.urls import path

from apps.investments import views

urlpatterns = [
    path("investments/", views.investments_overview, name="investments_overview"),
    path(
        "investments/instruments/<int:pk>/",
        views.instrument_detail,
        name="instrument_detail",
    ),
    path(
        "investments/instruments/<int:pk>/prices/",
        views.instrument_add_price,
        name="instrument_add_price",
    ),
    path(
        "accounts/asset/<int:pk>/holdings/",
        views.account_holdings,
        name="account_holdings",
    ),
    path(
        "accounts/asset/<int:pk>/holdings/new/",
        views.investment_event_create,
        name="investment_event_create",
    ),
    path(
        "accounts/investment-events/<int:pk>/edit/",
        views.investment_event_edit,
        name="investment_event_edit",
    ),
    path(
        "accounts/investment-events/<int:pk>/delete/",
        views.investment_event_delete,
        name="investment_event_delete",
    ),
]
