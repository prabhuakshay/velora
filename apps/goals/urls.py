from django.urls import path

from apps.goals import views

urlpatterns = [
    path("goals/", views.goal_list, name="goal_list"),
    path("goals/new/", views.goal_create, name="goal_create"),
    path("goals/<int:pk>/", views.goal_detail, name="goal_detail"),
    path("goals/<int:pk>/edit/", views.goal_edit, name="goal_edit"),
    path("goals/<int:pk>/delete/", views.goal_delete, name="goal_delete"),
    path(
        "goals/<int:pk>/allocations/new/",
        views.allocation_create,
        name="allocation_create",
    ),
    path(
        "goals/allocations/<int:pk>/edit/",
        views.allocation_edit,
        name="allocation_edit",
    ),
    path(
        "goals/allocations/<int:pk>/delete/",
        views.allocation_delete,
        name="allocation_delete",
    ),
]
