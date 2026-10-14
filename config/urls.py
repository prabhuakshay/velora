"""Root URL routes; each app's routes are included under its prefix."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from apps.home import views as home_views

urlpatterns = [
    path("", home_views.home, name="index"),
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
    path("", include("apps.budgets.urls")),
    path("", include("apps.investments.urls")),
    path("", include("apps.goals.urls")),
    path("", include("apps.help.urls")),
    path(settings.ADMIN_URL, admin.site.urls),
]
