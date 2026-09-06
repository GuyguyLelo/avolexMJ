"""Admin facturation."""

from __future__ import annotations

from django.contrib import admin

from apps.billing.models import Expense, Invoice, InvoiceLine, InvoiceSequence, TimeEntry


class InvoiceLineInline(admin.TabularInline):
    """Lignes de facture."""

    model = InvoiceLine
    extra = 0
    readonly_fields = ("kind", "description", "quantity", "unit_price", "amount")


@admin.register(TimeEntry)
class TimeEntryAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Admin saisies de temps."""

    list_display = ("description", "matter", "user", "duration_minutes", "invoice", "cabinet")
    list_filter = ("is_billable",)
    raw_id_fields = ("matter", "user", "invoice", "cabinet", "created_by")


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Admin débours."""

    list_display = ("description", "amount", "matter", "incurred_on", "invoice", "cabinet")
    raw_id_fields = ("matter", "invoice", "cabinet", "created_by")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Admin factures."""

    list_display = ("number", "status", "matter", "total", "issued_at", "cabinet")
    list_filter = ("status",)
    search_fields = ("number", "matter__reference", "matter__title")
    raw_id_fields = ("matter", "cabinet", "created_by")
    inlines = [InvoiceLineInline]


@admin.register(InvoiceSequence)
class InvoiceSequenceAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Admin séquences."""

    list_display = ("cabinet", "year", "last_number")
    raw_id_fields = ("cabinet", "created_by")
