from django.urls import path

from apps.classification.views import parties, tags

urlpatterns = [
    path("parties/", parties.party_list, name="party_list"),
    path("parties/new/", parties.party_create, name="party_create"),
    path(
        "parties/<int:pk>/transactions/",
        parties.party_transactions,
        name="party_transactions",
    ),
    path("parties/<int:pk>/edit/", parties.party_edit, name="party_edit"),
    path("parties/<int:pk>/hide/", parties.party_hide, name="party_hide"),
    path("parties/<int:pk>/unhide/", parties.party_unhide, name="party_unhide"),
    path("parties/<int:pk>/delete/", parties.party_delete, name="party_delete"),
    path("parties/<int:pk>/merge/", parties.party_merge, name="party_merge"),
    path("tags/", tags.tag_list, name="tag_list"),
    path("tags/new/", tags.tag_create, name="tag_create"),
    path("tags/<int:pk>/transactions/", tags.tag_transactions, name="tag_transactions"),
    path("tags/<int:pk>/edit/", tags.tag_edit, name="tag_edit"),
    path("tags/<int:pk>/hide/", tags.tag_hide, name="tag_hide"),
    path("tags/<int:pk>/unhide/", tags.tag_unhide, name="tag_unhide"),
    path("tags/<int:pk>/delete/", tags.tag_delete, name="tag_delete"),
    path("tags/<int:pk>/merge/", tags.tag_merge, name="tag_merge"),
]
