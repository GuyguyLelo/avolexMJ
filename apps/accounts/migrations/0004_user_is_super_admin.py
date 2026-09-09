"""Ajout du flag SuperAdmin sur User."""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_user_phone"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_super_admin",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text=(
                    "SuperAdmin : tous les droits, création des administrateurs "
                    "et comptes cabinets."
                ),
                verbose_name="super administrateur",
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="is_platform_admin",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text=(
                    "Administrateur du Ministère de la Justice : cabinets, dossiers, "
                    "procurations."
                ),
                verbose_name="administrateur ministère",
            ),
        ),
    ]
