from django.urls import path

from apps.errors import views

app_name = "errors"

urlpatterns = [
    path("", views.index, name="index"),
    path("<str:name>/", views.preview, name="preview"),
]
