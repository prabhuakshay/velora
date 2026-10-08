from django.conf import settings
from django.contrib.auth import views as auth_views
from django.urls import path
from django_ratelimit.decorators import ratelimit

limit_login = ratelimit(
    key="ip", rate=lambda _group, _request: settings.LOGIN_RATE_LIMIT, method="POST"
)
limit_password_reset = ratelimit(
    key="ip",
    rate=lambda _group, _request: settings.PASSWORD_RESET_RATE_LIMIT,
    method="POST",
)

urlpatterns = [
    path(
        "login/",
        limit_login(auth_views.LoginView.as_view(redirect_authenticated_user=True)),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "password-change/",
        auth_views.PasswordChangeView.as_view(),
        name="password_change",
    ),
    path(
        "password-change/done/",
        auth_views.PasswordChangeDoneView.as_view(),
        name="password_change_done",
    ),
    path(
        "password-reset/",
        limit_password_reset(auth_views.PasswordResetView.as_view()),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
]
