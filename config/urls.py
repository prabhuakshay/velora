"""Root URL routes; each app's routes are included under its prefix."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.accounts import views as account_views

urlpatterns = [
    path("", account_views.home, name="index"),
    path("auth/", include("apps.users.urls")),
    path("", include("apps.classification.urls")),
    path("", include("apps.accounts.urls")),
    path("", include("apps.transactions.urls")),
    path("", include("apps.quick_add.urls")),
    path("", include("apps.schedules.urls")),
    path(settings.ADMIN_URL, admin.site.urls),
]
