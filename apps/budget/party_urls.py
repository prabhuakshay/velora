from django.urls import path

from apps.budget import views

urlpatterns = [
    path("", views.party_list, name="party_list"),
    path("new/", views.party_create, name="party_create"),
    path("<int:pk>/edit/", views.party_edit, name="party_edit"),
    path("<int:pk>/hide/", views.party_hide, name="party_hide"),
    path("<int:pk>/unhide/", views.party_unhide, name="party_unhide"),
    path("<int:pk>/merge/", views.party_merge, name="party_merge"),
    path("<int:pk>/delete/", views.party_delete, name="party_delete"),
]
