from django.urls import path

from apps.budget import views

urlpatterns = [
    path("", views.expense_account_list, name="expense_account_list"),
    path("new/", views.expense_account_create, name="expense_account_create"),
    path("<int:pk>/edit/", views.expense_account_edit, name="expense_account_edit"),
    path("<int:pk>/hide/", views.expense_account_hide, name="expense_account_hide"),
    path(
        "<int:pk>/unhide/", views.expense_account_unhide, name="expense_account_unhide"
    ),
    path("<int:pk>/merge/", views.expense_account_merge, name="expense_account_merge"),
    path(
        "<int:pk>/delete/", views.expense_account_delete, name="expense_account_delete"
    ),
]
