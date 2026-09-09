# Generated manually — migrate legacy single report into HearingAttachment

from django.db import migrations


def forwards(apps, schema_editor):
    Event = apps.get_model("calendar_app", "Event")
    HearingAttachment = apps.get_model("calendar_app", "HearingAttachment")
    for event in Event.objects.exclude(hearing_report_file="").exclude(hearing_report_file__isnull=True):
        if HearingAttachment.objects.filter(event_id=event.pk).exists():
            continue
        HearingAttachment.objects.create(
            event_id=event.pk,
            file=event.hearing_report_file,
            original_filename=(event.hearing_report_filename or "rapport-audience.pdf")[:255],
            uploaded_by_id=event.created_by_id,
        )


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("calendar_app", "0005_hearing_attachments"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
