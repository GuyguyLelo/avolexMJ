"""Libellé numéro impôt sur Cabinet."""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0005_cabinet_contract_number"),
    ]

    operations = [
        migrations.AlterField(
            model_name="cabinet",
            name="vat_number",
            field=models.CharField(blank=True, max_length=32, verbose_name="numéro impôt"),
        ),
    ]
