"""Renommage identifiant Administrateur ministère → Admin."""

from __future__ import annotations

from django.db import migrations


def rename_ministry_admin_login(apps, schema_editor) -> None:
    User = apps.get_model("accounts", "User")
    User.objects.filter(email__iexact="ministere@avolex.local").update(email="Admin")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_user_identifier_charfield"),
    ]

    operations = [
        migrations.RunPython(rename_ministry_admin_login, migrations.RunPython.noop),
    ]
