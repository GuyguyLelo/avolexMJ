from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("procurations", "0002_procuration_before_matter"),
    ]

    operations = [
        migrations.AddField(
            model_name="procuration",
            name="draft_html",
            field=models.TextField(
                blank=True,
                help_text=(
                    "Texte mis en forme avant publication PDF. "
                    "Les données métier (dossier, parties…) restent dans leurs champs."
                ),
                verbose_name="brouillon de l'acte (HTML)",
            ),
        ),
    ]
