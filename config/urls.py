"""Root URL routes; each app's routes are included under its prefix."""

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import include, path
from django.views.generic import TemplateView

urlpatterns = [
    path(
        "",
        login_required(TemplateView.as_view(template_name="index.html")),
        name="index",
    ),
    path("auth/", include("apps.users.urls")),
    path("", include("apps.classification.urls")),
    path("", include("apps.accounts.urls")),
    path(settings.ADMIN_URL, admin.site.urls),
]
