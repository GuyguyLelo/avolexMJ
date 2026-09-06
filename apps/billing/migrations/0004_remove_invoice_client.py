# Generated manually to remove client field from Invoice model

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0003_currency_usd'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='invoice',
            name='client',
        ),
    ]
