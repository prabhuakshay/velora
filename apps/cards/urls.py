from django.urls import path

from apps.cards import views

urlpatterns = [
    path("statements/<int:pk>/edit/", views.statement_edit, name="statement_edit"),
]
