# Generated manually to remove client field from Matter model

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('matters', '0008_remove_matter_opposing_party'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='matter',
            name='client',
        ),
    ]
