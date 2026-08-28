"""Ajout du fichier contrat sur Cabinet."""

from __future__ import annotations

import apps.tenants.models
import apps.tenants.storage
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0006_alter_cabinet_vat_number"),
    ]

    operations = [
        migrations.AddField(
            model_name="cabinet",
            name="contract_file_name",
            field=models.CharField(blank=True, max_length=255, verbose_name="nom du contrat"),
        ),
        migrations.AddField(
            model_name="cabinet",
            name="contract_file",
            field=models.FileField(
                blank=True,
                max_length=512,
                storage=apps.tenants.storage.PrivateCabinetContractStorage(),
                upload_to=apps.tenants.models.cabinet_contract_upload_to,
                verbose_name="contrat",
            ),
        ),
    ]
