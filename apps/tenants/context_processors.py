"""Context processors liés au cabinet courant."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest

from apps.tenants.services import is_platform_admin, list_user_cabinets


def cabinet_context(request: HttpRequest) -> dict[str, Any]:
    """Expose le cabinet courant et la liste des cabinets de l'utilisateur."""
    user = request.user
    cabinet = getattr(request, "cabinet", None)
    membership = getattr(request, "membership", None)
    cabinets: list[Any] = []
    platform = False
    if user.is_authenticated:
        cabinets = list_user_cabinets(user)  # type: ignore[arg-type]
        platform = is_platform_admin(user)  # type: ignore[arg-type]
    return {
        "current_cabinet": cabinet,
        "current_membership": membership,
        "user_cabinets": cabinets,
        "is_platform_admin": platform,
    }
