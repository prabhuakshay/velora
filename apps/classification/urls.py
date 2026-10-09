from django.urls import path

from apps.classification import views

urlpatterns = [
    path("parties/", views.party_list, name="party_list"),
    path("parties/new/", views.party_create, name="party_create"),
    path("parties/<int:pk>/edit/", views.party_edit, name="party_edit"),
    path("parties/<int:pk>/hide/", views.party_hide, name="party_hide"),
    path("parties/<int:pk>/unhide/", views.party_unhide, name="party_unhide"),
    path("parties/<int:pk>/delete/", views.party_delete, name="party_delete"),
    path("parties/<int:pk>/merge/", views.party_merge, name="party_merge"),
    path("tags/", views.tag_list, name="tag_list"),
    path("tags/new/", views.tag_create, name="tag_create"),
    path("tags/<int:pk>/edit/", views.tag_edit, name="tag_edit"),
    path("tags/<int:pk>/hide/", views.tag_hide, name="tag_hide"),
    path("tags/<int:pk>/unhide/", views.tag_unhide, name="tag_unhide"),
    path("tags/<int:pk>/delete/", views.tag_delete, name="tag_delete"),
    path("tags/<int:pk>/merge/", views.tag_merge, name="tag_merge"),
]
