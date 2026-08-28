"""Stockage privé des contrats de cabinets avocats."""

from __future__ import annotations

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateCabinetContractStorage(FileSystemStorage):
    """Stockage filesystem hors URL publique."""

    def __init__(self) -> None:
        super().__init__(
            location=str(settings.MEDIA_ROOT / "cabinet-contracts"),
            base_url=None,
        )

    def url(self, name: str | None) -> str:
        """Refuse toute URL publique dévinable."""
        raise ValueError(
            "Les contrats de cabinet n'ont pas d'URL publique ; "
            "utilisez la vue de téléchargement protégée."
        )


private_cabinet_contract_storage = PrivateCabinetContractStorage()
