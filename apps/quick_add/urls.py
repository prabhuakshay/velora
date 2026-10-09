from django.urls import path

from apps.quick_add import views

urlpatterns = [
    path("quick-add/", views.quick_add_create, name="quick_add_create"),
    path("drafts/", views.draft_list, name="draft_list"),
]
