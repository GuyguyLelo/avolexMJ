"""Admin Django pour User."""

from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):  # type: ignore[type-arg]
    """Administration du User e-mail."""

    ordering = ("email",)
    list_display = (
        "email",
        "first_name",
        "last_name",
        "phone",
        "is_staff",
        "is_super_admin",
        "is_platform_admin",
        "is_active",
        "date_joined",
    )
    search_fields = ("email", "first_name", "last_name", "phone")
    list_filter = ("is_staff", "is_super_admin", "is_platform_admin", "is_superuser", "is_active")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            _("Informations personnelles"),
            {"fields": ("first_name", "last_name", "phone", "timezone", "locale")},
        ),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_super_admin",
                    "is_platform_admin",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (_("Dates importantes"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "is_staff",
                    "is_super_admin",
                    "is_platform_admin",
                    "is_active",
                ),
            },
        ),
    )
    filter_horizontal = ("groups", "user_permissions")
