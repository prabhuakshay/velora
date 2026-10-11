"""Root URL routes; each app's routes are included under its prefix."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from apps.accounts import views as account_views

urlpatterns = [
    path("", account_views.home, name="index"),
    path(
        "manifest.webmanifest",
        TemplateView.as_view(
            template_name="pwa/manifest.webmanifest",
            content_type="application/manifest+json",
        ),
        name="manifest",
    ),
    # At the root, since a service worker only controls pages under its path.
    path(
        "sw.js",
        TemplateView.as_view(template_name="pwa/sw.js", content_type="text/javascript"),
        name="service_worker",
    ),
    path(
        "offline/", TemplateView.as_view(template_name="offline.html"), name="offline"
    ),
    path("auth/", include("apps.users.urls")),
    path("", include("apps.classification.urls")),
    path("", include("apps.accounts.urls")),
    path("", include("apps.transactions.urls")),
    path("", include("apps.quick_add.urls")),
    path("", include("apps.schedules.urls")),
    path("", include("apps.cards.urls")),
    path(settings.ADMIN_URL, admin.site.urls),
]
