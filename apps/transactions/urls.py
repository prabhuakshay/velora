from django.urls import path

from apps.transactions import views

urlpatterns = [
    path("transactions/", views.transaction_list, name="transaction_list"),
    path("transactions/new/", views.transaction_create, name="transaction_create"),
    path(
        "transactions/split-row/",
        views.split_row,
        name="transaction_split_row",
    ),
    path(
        "transactions/<int:pk>/edit/",
        views.transaction_edit,
        name="transaction_edit",
    ),
    path(
        "transactions/<int:pk>/delete/",
        views.transaction_delete,
        name="transaction_delete",
    ),
    path(
        "attachments/<int:pk>/",
        views.attachment_open,
        name="attachment_open",
    ),
    path(
        "attachments/<int:pk>/delete/",
        views.attachment_delete,
        name="attachment_delete",
    ),
]
