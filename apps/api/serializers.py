"""Serializers REST."""

from __future__ import annotations

from rest_framework import serializers

from apps.calendar_app.models import Event
from apps.clients.models import Client
from apps.matters.models import Matter


class ClientSerializer(serializers.ModelSerializer):
    """Client exposé en API."""

    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = Client
        fields = (
            "id",
            "client_type",
            "first_name",
            "last_name",
            "company_name",
            "email",
            "phone",
            "address_line1",
            "address_line2",
            "postal_code",
            "city",
            "country",
            "notes",
            "display_name",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at", "display_name")


class MatterSerializer(serializers.ModelSerializer):
    """Dossier exposé en API."""

    client_name = serializers.CharField(source="client.display_name", read_only=True)

    class Meta:
        model = Matter
        fields = (
            "id",
            "reference",
            "title",
            "description",
            "practice_area",
            "scale",
            "status",
            "jurisdiction",
            "client",
            "client_name",
            "responsible_lawyer",
            "opened_at",
            "closed_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "reference", "created_at", "updated_at", "client_name")


class EventSerializer(serializers.ModelSerializer):
    """Événement agenda exposé en API."""

    class Meta:
        model = Event
        fields = (
            "id",
            "event_type",
            "title",
            "description",
            "matter",
            "starts_at",
            "ends_at",
            "all_day",
            "location",
            "court",
            "chamber",
            "hearing_status",
            "hearing_report",
            "hearing_report_filename",
            "is_done",
            "assigned_to",
            "remind_at",
            "created_at",
        )
        read_only_fields = ("id", "created_at", "hearing_report_filename")
