from django.urls import path

from apps.cards import views

urlpatterns = [
    path("statements/<int:pk>/edit/", views.statement_edit, name="statement_edit"),
    path(
        "statements/<int:pk>/link-payment/",
        views.statement_link_payment,
        name="statement_link_payment",
    ),
    path(
        "statements/<int:pk>/unlink-payment/",
        views.statement_unlink_payment,
        name="statement_unlink_payment",
    ),
    path(
        "transactions/<int:pk>/card-emi/",
        views.card_emi_create,
        name="card_emi_create",
    ),
    path("card-emis/<int:pk>/", views.card_emi_detail, name="card_emi_detail"),
    path(
        "card-emis/<int:pk>/foreclose/",
        views.card_emi_foreclose,
        name="card_emi_foreclose",
    ),
]
