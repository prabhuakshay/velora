from django.urls import path

from apps.budgets import views

urlpatterns = [
    path("budgets/", views.budget_list, name="budget_list"),
    path("budgets/set/", views.budget_set, name="budget_set"),
    path("budgets/<int:pk>/remove/", views.budget_remove, name="budget_remove"),
]
