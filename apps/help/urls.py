from django.urls import path

from apps.help import views

urlpatterns = [
    path("help/", views.help_index, name="help_index"),
    path("help/<slug:slug>/", views.help_area, name="help_area"),
]
