"""Services facturation : temps, frais, émission, PDF, CSV."""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, BinaryIO

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.billing.models import (
    Expense,
    Invoice,
    InvoiceLine,
    InvoiceLineKind,
    InvoiceSequence,
    InvoiceStatus,
    TimeEntry,
)
from apps.tenants.roles import PERM_ADD, PERM_CHANGE, PERM_DELETE, PERM_MANAGE_BILLING, PERM_VIEW
from apps.tenants.services import require_cabinet_perm

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.clients.models import Client
    from apps.matters.models import Matter
    from apps.tenants.models import Cabinet

logger = logging.getLogger(__name__)


def default_hourly_rate() -> Decimal:
    """Taux horaire par défaut (USD)."""
    return Decimal(str(getattr(settings, "BILLING_DEFAULT_HOURLY_RATE", "250.00")))


def default_tax_rate() -> Decimal:
    """Taux de TVA par défaut (%)."""
    return Decimal(str(getattr(settings, "BILLING_DEFAULT_TAX_RATE", "20.00")))


def assert_matter_cabinet(*, matter: Matter, cabinet: Cabinet) -> None:
    """Vérifie l'appartenance du dossier au cabinet."""
    if matter.cabinet_id != cabinet.pk:
        raise PermissionDenied(_("Dossier inaccessible."))


@transaction.atomic
def create_time_entry(
    *,
    cabinet: Cabinet,
    user: User,
    matter: Matter,
    description: str,
    duration_minutes: int,
    hourly_rate: Decimal | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    is_billable: bool = True,
) -> TimeEntry:
    """Crée une saisie de temps manuelle."""
    require_cabinet_perm(user=user, cabinet=cabinet, perm=PERM_ADD)
    assert_matter_cabinet(matter=matter, cabinet=cabinet)
    from apps.procurations.services import require_matter_activity_allowed

    require_matter_activity_allowed(matter)
    if duration_minutes <= 0:
        raise ValidationError({"duration_minutes": _("La durée doit être positive.")})
    now = timezone.now()
    return TimeEntry.objects.create(
        cabinet=cabinet,
        matter=matter,
        user=user,
        description=description.strip(),
        duration_minutes=duration_minutes,
        hourly_rate=hourly_rate or default_hourly_rate(),
        started_at=started_at or now,
        ended_at=ended_at or now,
        is_billable=is_billable,
        created_by=user,
    )


@transaction.atomic
def start_timer(
    *,
    cabinet: Cabinet,
    user: User,
    matter: Matter,
    description: str,
    hourly_rate: Decimal | None = None,
) -> TimeEntry:
    """Démarre un timer (un seul timer actif par utilisateur / cabinet)."""
    require_cabinet_perm(user=user, cabinet=cabinet, perm=PERM_ADD)
    assert_matter_cabinet(matter=matter, cabinet=cabinet)
    from apps.procurations.services import require_matter_activity_allowed

    require_matter_activity_allowed(matter)
    running = TimeEntry.objects.filter(
        cabinet=cabinet,
        user=user,
        started_at__isnull=False,
        ended_at__isnull=True,
    ).first()
    if running:
        raise ValidationError(
            _("Un timer est déjà en cours. Arrêtez-le avant d'en démarrer un autre.")
        )
    return TimeEntry.objects.create(
        cabinet=cabinet,
        matter=matter,
        user=user,
        description=description.strip() or _("Temps"),
        started_at=timezone.now(),
        duration_minutes=0,
        hourly_rate=hourly_rate or default_hourly_rate(),
        is_billable=True,
        created_by=user,
    )


@transaction.atomic
def stop_timer(*, entry: TimeEntry, user: User) -> TimeEntry:
    """Arrête un timer et calcule la durée."""
    require_cabinet_perm(user=user, cabinet=entry.cabinet, perm=PERM_CHANGE)
    if not entry.is_running:
        raise ValidationError(_("Ce timer n'est pas en cours."))
    now = timezone.now()
    assert entry.started_at is not None
    minutes = max(1, int((now - entry.started_at).total_seconds() // 60))
    entry.ended_at = now
    entry.duration_minutes = minutes
    entry.save(update_fields=["ended_at", "duration_minutes", "updated_at"])
    return entry


@transaction.atomic
def create_expense(
    *,
    cabinet: Cabinet,
    user: User,
    matter: Matter,
    description: str,
    amount: Decimal,
    incurred_on: date | None = None,
    is_billable: bool = True,
) -> Expense:
    """Crée un débours."""
    require_cabinet_perm(user=user, cabinet=cabinet, perm=PERM_ADD)
    assert_matter_cabinet(matter=matter, cabinet=cabinet)
    from apps.procurations.services import require_matter_activity_allowed

    require_matter_activity_allowed(matter)
    if amount <= 0:
        raise ValidationError({"amount": _("Le montant doit être positif.")})
    return Expense.objects.create(
        cabinet=cabinet,
        matter=matter,
        description=description.strip(),
        amount=amount.quantize(Decimal("0.01")),
        currency=cabinet.default_currency,
        incurred_on=incurred_on or timezone.localdate(),
        is_billable=is_billable,
        created_by=user,
    )


def unbilled_time_entries(*, cabinet: Cabinet, matter: Matter | None = None) -> QuerySet[TimeEntry]:
    """Temps facturables non encore rattachés à une facture."""
    qs = TimeEntry.objects.filter(
        cabinet=cabinet,
        is_billable=True,
        invoice__isnull=True,
        ended_at__isnull=False,
    ).select_related("matter", "user")
    if matter is not None:
        qs = qs.filter(matter=matter)
    return qs


def unbilled_expenses(*, cabinet: Cabinet, matter: Matter | None = None) -> QuerySet[Expense]:
    """Débours facturables non facturés."""
    qs = Expense.objects.filter(
        cabinet=cabinet,
        is_billable=True,
        invoice__isnull=True,
    ).select_related("matter")
    if matter is not None:
        qs = qs.filter(matter=matter)
    return qs


def _recompute_draft_totals(invoice: Invoice) -> None:
    """Recalcule HT / TVA / TTC à partir des lignes (brouillon)."""
    subtotal = sum((line.amount for line in invoice.lines.all()), Decimal("0.00"))
    tax = (subtotal * invoice.tax_rate / Decimal("100")).quantize(Decimal("0.01"))
    invoice.subtotal = subtotal.quantize(Decimal("0.01"))
    invoice.tax_amount = tax
    invoice.total = (invoice.subtotal + invoice.tax_amount).quantize(Decimal("0.01"))
    invoice.save(update_fields=["subtotal", "tax_amount", "total", "updated_at"])


@transaction.atomic
def create_draft_invoice(
    *,
    cabinet: Cabinet,
    user: User,
    client: Client,
    matter: Matter | None,
    time_entry_ids: list[str] | None = None,
    expense_ids: list[str] | None = None,
    tax_rate: Decimal | None = None,
    notes: str = "",
    due_days: int = 30,
) -> Invoice:
    """
    Crée une facture brouillon et y rattache temps / frais sélectionnés.

    Les lignes sont créées immédiatement (modifiables tant que brouillon).
    """
    require_cabinet_perm(user=user, cabinet=cabinet, perm=PERM_ADD)
    if client.cabinet_id != cabinet.pk:
        raise PermissionDenied(_("Client inaccessible."))
    if matter is not None:
        assert_matter_cabinet(matter=matter, cabinet=cabinet)
        if matter.client_id != client.pk:
            raise ValidationError(_("Le dossier n'appartient pas à ce client."))
        from apps.procurations.services import require_matter_activity_allowed

        require_matter_activity_allowed(matter)

    invoice = Invoice.objects.create(
        cabinet=cabinet,
        client=client,
        matter=matter,
        status=InvoiceStatus.DRAFT,
        tax_rate=tax_rate if tax_rate is not None else default_tax_rate(),
        notes=notes.strip(),
        due_at=timezone.localdate() + timedelta(days=due_days),
        currency=cabinet.default_currency,
        created_by=user,
    )

    if time_entry_ids:
        entries = list(
            TimeEntry.objects.filter(
                pk__in=time_entry_ids,
                cabinet=cabinet,
                invoice__isnull=True,
                is_billable=True,
            )
        )
        if len(entries) != len(set(time_entry_ids)):
            raise ValidationError(_("Certaines saisies de temps sont invalides ou déjà facturées."))
        for entry in entries:
            hours = (Decimal(entry.duration_minutes) / Decimal(60)).quantize(Decimal("0.01"))
            InvoiceLine.objects.create(
                cabinet=cabinet,
                invoice=invoice,
                kind=InvoiceLineKind.TIME,
                description=f"{entry.description} ({entry.duration_minutes} min)",
                quantity=hours,
                unit_price=entry.hourly_rate,
                amount=entry.amount,
                source_time_entry=entry,
                created_by=user,
            )
            entry.invoice = invoice
            entry.save(update_fields=["invoice", "updated_at"])

    if expense_ids:
        expenses = list(
            Expense.objects.filter(
                pk__in=expense_ids,
                cabinet=cabinet,
                invoice__isnull=True,
                is_billable=True,
            )
        )
        if len(expenses) != len(set(expense_ids)):
            raise ValidationError(_("Certains débours sont invalides ou déjà facturés."))
        for expense in expenses:
            InvoiceLine.objects.create(
                cabinet=cabinet,
                invoice=invoice,
                kind=InvoiceLineKind.EXPENSE,
                description=expense.description,
                quantity=Decimal("1.00"),
                unit_price=expense.amount,
                amount=expense.amount,
                source_expense=expense,
                created_by=user,
            )
            expense.invoice = invoice
            expense.save(update_fields=["invoice", "updated_at"])

    _recompute_draft_totals(invoice)
    logger.info("Facture brouillon créée id=%s cabinet=%s", invoice.pk, cabinet.pk)
    return invoice


def allocate_invoice_number(*, cabinet: Cabinet, year: int | None = None) -> str:
    """
    Alloue le prochain numéro FAC-YYYY-NNNNN (sans trou, verrouillage DB).

    Must be called inside transaction.atomic().
    """
    year = year or timezone.localdate().year
    seq, _created = InvoiceSequence.objects.select_for_update().get_or_create(
        cabinet=cabinet,
        year=year,
        defaults={"last_number": 0},
    )
    seq.last_number += 1
    seq.save(update_fields=["last_number", "updated_at"])
    return f"FAC-{year}-{seq.last_number:05d}"


@transaction.atomic
def issue_invoice(*, invoice: Invoice, user: User) -> Invoice:
    """Émet la facture : numéro légal + statut SENT + génération PDF."""
    require_cabinet_perm(user=user, cabinet=invoice.cabinet, perm=PERM_CHANGE)
    if invoice.status != InvoiceStatus.DRAFT:
        raise ValidationError(_("Seule une facture brouillon peut être émise."))
    if not invoice.lines.exists():
        raise ValidationError(_("La facture ne contient aucune ligne."))

    _recompute_draft_totals(invoice)
    invoice.number = allocate_invoice_number(cabinet=invoice.cabinet)
    invoice.status = InvoiceStatus.SENT
    invoice.issued_at = timezone.localdate()
    if invoice.due_at is None:
        invoice.due_at = invoice.issued_at + timedelta(days=30)
    invoice.save(
        update_fields=[
            "number",
            "status",
            "issued_at",
            "due_at",
            "subtotal",
            "tax_amount",
            "total",
            "updated_at",
        ]
    )
    pdf_bytes = render_invoice_pdf_bytes(invoice)
    store_invoice_pdf(invoice=invoice, pdf_bytes=pdf_bytes)
    logger.info("Facture émise number=%s id=%s", invoice.number, invoice.pk)
    return invoice


def render_invoice_pdf_bytes(invoice: Invoice) -> bytes:
    """Génère le PDF de facture en mémoire."""
    from apps.billing.pdf import build_invoice_pdf

    return build_invoice_pdf(invoice)


def invoice_needs_pdf(invoice: Invoice) -> bool:
    """True si le PDF est absent ou n'est qu'un stub de test."""
    if not invoice.pdf_file:
        return True
    try:
        return invoice.pdf_file.size < 500
    except OSError:
        return True


@transaction.atomic
def store_invoice_pdf(*, invoice: Invoice, pdf_bytes: bytes) -> Invoice:
    """Persiste le PDF généré sur le storage privé."""
    filename = f"{invoice.number or invoice.pk}.pdf"
    invoice.pdf_file.save(filename, ContentFile(pdf_bytes), save=True)
    return invoice


@transaction.atomic
def mark_invoice_paid(*, invoice: Invoice, user: User) -> Invoice:
    """Passe une facture émise / impayée en payée."""
    require_cabinet_perm(user=user, cabinet=invoice.cabinet, perm=PERM_CHANGE)
    if invoice.status not in {InvoiceStatus.SENT, InvoiceStatus.OVERDUE}:
        raise ValidationError(_("Seule une facture envoyée ou impayée peut être marquée payée."))
    invoice.status = InvoiceStatus.PAID
    invoice.paid_at = timezone.localdate()
    invoice.save(update_fields=["status", "paid_at", "updated_at"])
    return invoice


@transaction.atomic
def mark_invoice_overdue(*, invoice: Invoice, user: User) -> Invoice:
    """Marque une facture comme impayée (échéance dépassée)."""
    require_cabinet_perm(user=user, cabinet=invoice.cabinet, perm=PERM_CHANGE)
    if invoice.status != InvoiceStatus.SENT:
        raise ValidationError(_("Seule une facture envoyée peut devenir impayée."))
    invoice.status = InvoiceStatus.OVERDUE
    invoice.save(update_fields=["status", "updated_at"])
    return invoice


@transaction.atomic
def cancel_invoice(*, invoice: Invoice, user: User) -> Invoice:
    """
    Annule une facture émise (pas de hard-delete — conformité).

    Les temps/frais restent liés (historique) ; pas de remise en facturable auto.
    """
    if invoice.status == InvoiceStatus.DRAFT:
        require_cabinet_perm(user=user, cabinet=invoice.cabinet, perm=PERM_CHANGE)
    else:
        require_cabinet_perm(user=user, cabinet=invoice.cabinet, perm=PERM_MANAGE_BILLING)
    if invoice.status == InvoiceStatus.DRAFT:
        # Brouillon : soft-delete autorisé + détache les items
        for entry in invoice.time_entries.all():
            entry.invoice = None
            entry.save(update_fields=["invoice", "updated_at"])
        for expense in invoice.expenses.all():
            expense.invoice = None
            expense.save(update_fields=["invoice", "updated_at"])
        invoice.soft_delete()
        return invoice
    if invoice.status == InvoiceStatus.PAID:
        raise ValidationError(_("Une facture payée ne peut pas être annulée (émettre un avoir)."))
    if invoice.status == InvoiceStatus.CANCELLED:
        return invoice
    invoice.status = InvoiceStatus.CANCELLED
    invoice.save(update_fields=["status", "updated_at"])
    logger.info("Facture annulée number=%s", invoice.number)
    return invoice


@transaction.atomic
def delete_time_entry(*, entry: TimeEntry, user: User) -> None:
    """Soft-delete d'une saisie non facturée."""
    require_cabinet_perm(user=user, cabinet=entry.cabinet, perm=PERM_DELETE)
    if entry.invoice_id:
        raise ValidationError(_("Impossible de supprimer une saisie déjà facturée."))
    entry.soft_delete()


@transaction.atomic
def delete_expense(*, expense: Expense, user: User) -> None:
    """Soft-delete d'un débours non facturé."""
    require_cabinet_perm(user=user, cabinet=expense.cabinet, perm=PERM_DELETE)
    if expense.invoice_id:
        raise ValidationError(_("Impossible de supprimer un débours déjà facturé."))
    expense.soft_delete()


def export_invoices_csv(*, cabinet: Cabinet, user: User) -> BinaryIO:
    """Exporte les factures du cabinet en CSV (UTF-8)."""
    require_cabinet_perm(user=user, cabinet=cabinet, perm=PERM_VIEW)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(
        [
            "number",
            "status",
            "client",
            "matter",
            "issued_at",
            "due_at",
            "paid_at",
            "subtotal",
            "tax_amount",
            "total",
            "currency",
        ]
    )
    qs = (
        Invoice.objects.filter(cabinet=cabinet)
        .select_related("client", "matter")
        .order_by("-issued_at", "-created_at")
    )
    for inv in qs:
        writer.writerow(
            [
                inv.number,
                inv.status,
                inv.client.display_name,
                inv.matter.reference if inv.matter else "",
                inv.issued_at.isoformat() if inv.issued_at else "",
                inv.due_at.isoformat() if inv.due_at else "",
                inv.paid_at.isoformat() if inv.paid_at else "",
                str(inv.subtotal),
                str(inv.tax_amount),
                str(inv.total),
                inv.currency,
            ]
        )
    stream: BinaryIO = io.BytesIO(buffer.getvalue().encode("utf-8-sig"))
    stream.seek(0)
    return stream
