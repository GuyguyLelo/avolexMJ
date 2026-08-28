"""Ajout du n° de contrat sur Cabinet."""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0004_alter_invitation_role_alter_membership_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="cabinet",
            name="contract_number",
            field=models.CharField(blank=True, max_length=64, verbose_name="n° de contrat"),
        ),
    ]
