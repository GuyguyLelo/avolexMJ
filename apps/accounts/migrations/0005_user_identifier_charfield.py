"""Identifiant User en CharField + renommage SuperAdmin."""

from __future__ import annotations

from django.db import migrations, models


def rename_superadmin_login(apps, schema_editor) -> None:
    User = apps.get_model("accounts", "User")
    User.objects.filter(email__iexact="superadmin@avolex.local").update(email="SuperAdmin")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_user_is_super_admin"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="email",
            field=models.CharField(
                db_index=True,
                max_length=254,
                unique=True,
                verbose_name="identifiant",
            ),
        ),
        migrations.RunPython(rename_superadmin_login, migrations.RunPython.noop),
    ]
