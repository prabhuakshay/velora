from django.contrib.auth import views as auth_views
from django.urls import path

from apps.users.throttle import throttle
from apps.users.views import LoginView, preferences, privacy_mode_on

limit_login = throttle("LOGIN_RATE_LIMIT")
limit_password_reset = throttle("PASSWORD_RESET_RATE_LIMIT")

urlpatterns = [
    path(
        "login/",
        limit_login(LoginView.as_view()),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("preferences/", preferences, name="preferences"),
    path("privacy-mode/on/", privacy_mode_on, name="privacy_mode_on"),
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
