# Generated manually for platform supervision.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_platform_admin",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text=(
                    "Supervise tous les cabinets en lecture seule "
                    "(suivi d'activité cross-cabinet)."
                ),
                verbose_name="administrateur plateforme",
            ),
        ),
    ]
