"""Managers soft-delete et multi-tenant."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from typing_extensions import Self

from django.core.exceptions import ImproperlyConfigured
from django.db import models

if TYPE_CHECKING:
    from uuid import UUID

    from apps.tenants.models import Cabinet


class SoftDeleteQuerySet(models.QuerySet):
    """QuerySet excluant les enregistrements soft-deleted (par défaut)."""

    def delete(self) -> tuple[int, dict[str, int]]:  # type: ignore[override]
        """Soft-delete en masse."""
        from django.utils import timezone

        updated = self.update(is_deleted=True, deleted_at=timezone.now())
        return updated, {self.model._meta.label: updated}

    def hard_delete(self) -> tuple[int, dict[str, int]]:
        """Suppression SQL réelle."""
        return super().delete()

    def alive(self) -> Self:
        """Filtre les non-supprimés."""
        return self.filter(is_deleted=False)

    def dead(self) -> Self:
        """Filtre les soft-deleted."""
        return self.filter(is_deleted=True)


class SoftDeleteManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """Manager par défaut : masque les soft-deleted."""

    def get_queryset(self) -> SoftDeleteQuerySet:
        """Retourne uniquement les enregistrements non supprimés."""
        return SoftDeleteQuerySet(self.model, using=self._db).alive()


class TenantQuerySet(SoftDeleteQuerySet):
    """QuerySet filtré par le cabinet courant."""

    def for_cabinet(self, cabinet: Cabinet | UUID | str) -> Self:
        """Filtre explicite sur un cabinet (UUID ou instance)."""
        cabinet_id = getattr(cabinet, "pk", cabinet)
        return self.filter(cabinet_id=cabinet_id)


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    """
    Manager par défaut des modèles TenantOwnedModel.

    Filtre systématiquement par le cabinet du ContextVar.
    Utiliser ``Model.unscoped`` pour les opérations cross-cabinet (admin, Celery).
    """

    def get_queryset(self) -> TenantQuerySet:
        """Filtre soft-delete + cabinet courant."""
        from apps.tenants.context import get_current_cabinet

        qs = TenantQuerySet(self.model, using=self._db).alive()
        cabinet = get_current_cabinet()
        if cabinet is None:
            # Pas de cabinet → queryset vide (fail-closed). Évite les fuites cross-tenant.
            return qs.none()
        return qs.filter(cabinet_id=cabinet.pk)

    def for_cabinet(self, cabinet: Cabinet | UUID | str) -> TenantQuerySet:
        """Queryset scoped à un cabinet donné (ignore le ContextVar)."""
        cabinet_id = getattr(cabinet, "pk", cabinet)
        return TenantQuerySet(self.model, using=self._db).alive().filter(cabinet_id=cabinet_id)

    def create(self, **kwargs: Any) -> Any:
        """Crée une instance en injectant le cabinet courant si besoin."""
        from apps.tenants.context import get_current_cabinet

        if "cabinet" not in kwargs and "cabinet_id" not in kwargs:
            cabinet = get_current_cabinet()
            if cabinet is None:
                raise ImproperlyConfigured(
                    "Impossible de créer un objet tenant sans cabinet courant ni argument cabinet=."
                )
            kwargs["cabinet"] = cabinet
        return super().create(**kwargs)
