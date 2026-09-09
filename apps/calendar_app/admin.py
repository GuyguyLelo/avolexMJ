"""Admin agenda."""

from __future__ import annotations

from django.contrib import admin

from apps.calendar_app.models import Event, HearingAttachment


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Administration des événements."""

    list_display = (
        "title",
        "event_type",
        "hearing_status",
        "starts_at",
        "cabinet",
        "is_done",
        "assigned_to",
    )
    list_filter = ("event_type", "hearing_status", "is_done")
    search_fields = ("title", "location", "court", "chamber")
    raw_id_fields = ("cabinet", "matter", "assigned_to", "created_by")


@admin.register(HearingAttachment)
class HearingAttachmentAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Pièces jointes d'audience."""

    list_display = ("original_filename", "event", "uploaded_by", "created_at")
    raw_id_fields = ("event", "uploaded_by")
    search_fields = ("original_filename",)
