from django.urls import path

from apps.quick_add import views

urlpatterns = [
    path("quick-add/", views.quick_add_create, name="quick_add_create"),
    path("drafts/", views.draft_list, name="draft_list"),
    path("drafts/<int:pk>/post/", views.draft_post, name="draft_post"),
    path("drafts/<int:pk>/reject/", views.draft_reject, name="draft_reject"),
]
