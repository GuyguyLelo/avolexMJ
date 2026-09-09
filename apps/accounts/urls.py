"""URLs accounts."""

from __future__ import annotations

from django.urls import path

from apps.accounts import profile_views, user_views, views

app_name = "accounts"

urlpatterns = [
    path("login/", views.AvoLexLoginView.as_view(), name="login"),
    path("logout/", views.AvoLexLogoutView.as_view(), name="logout"),
    path("register/", views.RegisterView.as_view(), name="register"),
    path("password-reset/", views.AvoLexPasswordResetView.as_view(), name="password_reset"),
    path(
        "password-reset/done/",
        views.AvoLexPasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "password-reset/<uidb64>/<token>/",
        views.AvoLexPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/complete/",
        views.AvoLexPasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    path(
        "invitations/<str:token>/",
        views.AcceptInvitationView.as_view(),
        name="accept_invitation",
    ),
    path("profil/", profile_views.ProfileDetailView.as_view(), name="profile"),
    path(
        "profil/modifier/",
        profile_views.ProfileUpdateView.as_view(),
        name="profile_update",
    ),
    path("utilisateurs/", user_views.UserListView.as_view(), name="user_list"),
    path("utilisateurs/nouveau/", user_views.UserCreateView.as_view(), name="user_create"),
    path("utilisateurs/<uuid:pk>/", user_views.UserDetailView.as_view(), name="user_detail"),
    path(
        "utilisateurs/<uuid:pk>/modifier/",
        user_views.UserUpdateView.as_view(),
        name="user_update",
    ),
    path(
        "utilisateurs/<uuid:pk>/desactiver/",
        user_views.UserDeactivateView.as_view(),
        name="user_deactivate",
    ),
]
