import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("procurations", "0003_procuration_draft_html"),
    ]

    operations = [
        migrations.AlterField(
            model_name="procuration",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Brouillon"),
                    ("requested", "En attente Conseiller"),
                    ("approved_conseiller", "En attente Dircaba"),
                    ("granted", "Accordée"),
                    ("refused", "Refusée"),
                    ("revoked", "Révoquée"),
                ],
                db_index=True,
                default="draft",
                max_length=20,
                verbose_name="statut",
            ),
        ),
        migrations.AlterField(
            model_name="procuration",
            name="granted_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="granted_procurations",
                to=settings.AUTH_USER_MODEL,
                verbose_name="visa Dircaba par",
            ),
        ),
        migrations.AddField(
            model_name="procuration",
            name="conseiller_at",
            field=models.DateField(
                blank=True, null=True, verbose_name="validée Conseiller le"
            ),
        ),
        migrations.AddField(
            model_name="procuration",
            name="conseiller_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="conseiller_procurations",
                to=settings.AUTH_USER_MODEL,
                verbose_name="validée par le Conseiller",
            ),
        ),
        migrations.AddField(
            model_name="procuration",
            name="conseiller_notes",
            field=models.TextField(blank=True, verbose_name="notes Conseiller"),
        ),
    ]
