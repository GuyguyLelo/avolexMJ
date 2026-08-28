"""Stockage privé des actes de procuration."""

from __future__ import annotations

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateProcurationStorage(FileSystemStorage):
    """Stockage filesystem hors URL publique."""

    def __init__(self) -> None:
        super().__init__(
            location=str(settings.MEDIA_ROOT / "procurations"),
            base_url=None,
        )

    def url(self, name: str | None) -> str:
        """Refuse toute URL publique dévinable."""
        raise ValueError(
            "Les actes de procuration n'ont pas d'URL publique ; "
            "utilisez la vue de téléchargement protégée."
        )


private_procuration_storage = PrivateProcurationStorage()
