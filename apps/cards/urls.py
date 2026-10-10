from django.urls import path

from apps.cards import views

urlpatterns = [
    path("statements/<int:pk>/edit/", views.statement_edit, name="statement_edit"),
    path(
        "transactions/<int:pk>/card-emi/",
        views.card_emi_create,
        name="card_emi_create",
    ),
    path(
        "card-emis/<int:pk>/foreclose/",
        views.card_emi_foreclose,
        name="card_emi_foreclose",
    ),
]
