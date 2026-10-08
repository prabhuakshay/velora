from django.urls import path

from apps.budget import views

urlpatterns = [
    path("", views.category_list, name="category_list"),
    path("groups/new/", views.group_create, name="group_create"),
    path("groups/<int:pk>/edit/", views.group_edit, name="group_edit"),
    path("groups/<int:pk>/delete/", views.group_delete, name="group_delete"),
    path("groups/<int:pk>/hide/", views.group_hide, name="group_hide"),
    path("groups/<int:pk>/unhide/", views.group_unhide, name="group_unhide"),
    path("<int:pk>/hide/", views.category_hide, name="category_hide"),
    path("<int:pk>/unhide/", views.category_unhide, name="category_unhide"),
    path("new/", views.category_create, name="category_create"),
    path("<int:pk>/edit/", views.category_edit, name="category_edit"),
    path("<int:pk>/delete/", views.category_delete, name="category_delete"),
]
