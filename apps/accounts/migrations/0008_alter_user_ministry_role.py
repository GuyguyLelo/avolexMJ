from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_user_ministry_role"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="ministry_role",
            field=models.CharField(
                blank=True,
                choices=[
                    ("admin", "Administrateur"),
                    ("conseiller", "Conseiller"),
                    ("dircaba", "Dircaba"),
                    ("charge_etudes", "Chargé d'Études"),
                    ("greffe", "Greffe"),
                ],
                db_index=True,
                default="",
                help_text=(
                    "Administrateur / Chargé d'Études : émission. "
                    "Conseiller : 1re validation. Dircaba : visa final. Greffe : consultation."
                ),
                max_length=20,
                verbose_name="rôle ministériel",
            ),
        ),
    ]
