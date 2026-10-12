from django.urls import path

from apps.budgets import views

urlpatterns = [
    path("budgets/", views.budget_list, name="budget_list"),
    path("budgets/<int:pk>/edit/", views.budget_edit, name="budget_edit"),
    path("budgets/overall/edit/", views.budget_edit, name="overall_budget_edit"),
]
