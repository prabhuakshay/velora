from django.urls import path

from apps.investments import views

urlpatterns = [
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
]
