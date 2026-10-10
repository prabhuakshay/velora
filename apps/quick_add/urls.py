from django.urls import path

from apps.quick_add import views

urlpatterns = [
    path("quick-add/", views.quick_add_create, name="quick_add_create"),
    path("drafts/", views.draft_list, name="draft_list"),
    path("drafts/new/", views.draft_create, name="draft_create"),
    path("drafts/<int:pk>/post/", views.draft_post, name="draft_post"),
    path("drafts/<int:pk>/edit/", views.draft_edit, name="draft_edit"),
    path("drafts/<int:pk>/reject/", views.draft_reject, name="draft_reject"),
    path("drafts/<int:pk>/retry/", views.quick_add_retry, name="quick_add_retry"),
    path("drafts/<int:pk>/discard/", views.quick_add_discard, name="quick_add_discard"),
    path(
        "drafts/<int:pk>/resubmit/",
        views.quick_add_resubmit,
        name="quick_add_resubmit",
    ),
]
