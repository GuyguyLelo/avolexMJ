"""Rôles et matrice de permissions par cabinet."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class Role(models.TextChoices):
    """Rôles d'un membre au sein d'un cabinet."""

    CAIMAN = "caiman", _("Caïman")
    LAWYER = "lawyer", _("Avocat")


# Alias techniques pour les anciens appels ; ils ne figurent plus dans les choix affichés.
Role.OWNER = Role.CAIMAN  # type: ignore[attr-defined]
Role.ASSOCIATE = Role.LAWYER  # type: ignore[attr-defined]
Role.SECRETARY = Role.LAWYER  # type: ignore[attr-defined]
Role.READ_ONLY = "read_only"  # type: ignore[attr-defined]


# Permissions logiques (pas Django auth perms)
PERM_VIEW = "view"
PERM_ADD = "add"
PERM_CHANGE = "change"
PERM_DELETE = "delete"
PERM_MANAGE_MEMBERS = "manage_members"
PERM_MANAGE_BILLING = "manage_billing"
PERM_MANAGE_CABINET = "manage_cabinet"
PERM_INVITE = "invite"

_ALL = frozenset(
    {
        PERM_VIEW,
        PERM_ADD,
        PERM_CHANGE,
        PERM_DELETE,
        PERM_MANAGE_MEMBERS,
        PERM_MANAGE_BILLING,
        PERM_MANAGE_CABINET,
        PERM_INVITE,
    }
)

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    Role.CAIMAN: _ALL,
    Role.LAWYER: frozenset({PERM_VIEW, PERM_ADD, PERM_CHANGE, PERM_DELETE, PERM_INVITE}),
}


def role_has_perm(role: str, perm: str) -> bool:
    """Indique si un rôle possède une permission logique."""
    return perm in ROLE_PERMISSIONS.get(role, frozenset())
