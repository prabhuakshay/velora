from django.urls import path

from apps.budget import views

urlpatterns = [
    path("", views.category_list, name="category_list"),
    path("activity/", views.category_activity, name="category_activity"),
    path("groups/new/", views.group_create, name="group_create"),
    path("groups/<int:pk>/edit/", views.group_edit, name="group_edit"),
    path("groups/<int:pk>/delete/", views.group_delete, name="group_delete"),
    path("new/", views.category_create, name="category_create"),
    path("<int:pk>/edit/", views.category_edit, name="category_edit"),
    path("<int:pk>/delete/", views.category_delete, name="category_delete"),
]
