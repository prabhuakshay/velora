from django.urls import path

from apps.budget import views

urlpatterns = [
    path("", views.category_list, name="category_list"),
    path("activity/", views.category_activity, name="category_activity"),
    path("icons/search/", views.icon_search, name="icon_search"),
    path("<int:pk>/hide/", views.category_hide, name="category_hide"),
    path("<int:pk>/unhide/", views.category_unhide, name="category_unhide"),
    path("new/", views.category_create, name="category_create"),
    path("<int:pk>/edit/", views.category_edit, name="category_edit"),
    path("<int:pk>/delete/", views.category_delete, name="category_delete"),
]
