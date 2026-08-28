"""Stockage privé des rapports d'audience."""

from __future__ import annotations

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateHearingStorage(FileSystemStorage):
    """Stockage filesystem hors URL publique."""

    def __init__(self) -> None:
        super().__init__(
            location=str(settings.MEDIA_ROOT / "hearings"),
            base_url=None,
        )

    def url(self, name: str | None) -> str:
        """Refuse toute URL publique dévinable."""
        raise ValueError(
            "Les rapports d'audience n'ont pas d'URL publique ; "
            "utilisez la vue de téléchargement protégée."
        )


private_hearing_storage = PrivateHearingStorage()
