from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_rename_ministry_admin_login"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="ministry_role",
            field=models.CharField(
                blank=True,
                choices=[
                    ("admin", "Administrateur"),
                    ("conseiller", "Conseiller"),
                    ("dircaba", "Dircaba"),
                ],
                db_index=True,
                default="",
                help_text=(
                    "Conseiller (1re validation) ou Dircaba (visa final). "
                    "Vide / Administrateur : les deux étapes."
                ),
                max_length=20,
                verbose_name="rôle ministériel",
            ),
        ),
    ]
