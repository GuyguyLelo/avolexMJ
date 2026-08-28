"""Permissions API basées sur le cabinet courant."""

from __future__ import annotations

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.tenants.roles import PERM_ADD, PERM_CHANGE, PERM_DELETE, PERM_VIEW, role_has_perm
from apps.tenants.services import get_membership, is_platform_admin

_METHOD_PERM: dict[str, str] = {
    "GET": PERM_VIEW,
    "HEAD": PERM_VIEW,
    "OPTIONS": PERM_VIEW,
    "POST": PERM_ADD,
    "PUT": PERM_CHANGE,
    "PATCH": PERM_CHANGE,
    "DELETE": PERM_DELETE,
}


class IsCabinetMember(BasePermission):
    """Exige un utilisateur authentifié membre du cabinet, avec permission par verbe HTTP."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        cabinet = getattr(request, "cabinet", None)
        if cabinet is None:
            return False
        required = _METHOD_PERM.get(request.method or "GET", PERM_VIEW)
        if is_platform_admin(user):
            return required == PERM_VIEW
        membership = getattr(request, "membership", None) or get_membership(
            user=user, cabinet=cabinet
        )
        if membership is None:
            return False
        request.membership = membership  # type: ignore[attr-defined]
        return role_has_perm(membership.role, required)
