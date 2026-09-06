"""Modèles facturation : temps, frais, factures, séquence légale."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.billing.storage import private_invoice_storage
from apps.core.models import TenantOwnedModel
from apps.core.money import default_currency


class InvoiceStatus(models.TextChoices):
    """Statuts de facture."""

    DRAFT = "draft", _("Brouillon")
    SENT = "sent", _("Envoyée")
    PAID = "paid", _("Payée")
    OVERDUE = "overdue", _("Impayée")
    CANCELLED = "cancelled", _("Annulée")


class InvoiceLineKind(models.TextChoices):
    """Type de ligne de facture."""

    TIME = "time", _("Temps")
    EXPENSE = "expense", _("Débours")
    OTHER = "other", _("Autre")


def invoice_pdf_upload_to(instance: Invoice, filename: str) -> str:
    """Chemin opaque pour les PDF de facture."""
    return f"{instance.cabinet_id}/invoices/{instance.pk}.pdf"


class TimeEntry(TenantOwnedModel):
    """Saisie de temps (manuel ou timer)."""

    matter = models.ForeignKey(
        "matters.Matter",
        verbose_name=_("dossier"),
        on_delete=models.CASCADE,
        related_name="time_entries",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("intervenant"),
        on_delete=models.PROTECT,
        related_name="time_entries",
    )
    description = models.CharField(_("description"), max_length=500)
    started_at = models.DateTimeField(_("début"), null=True, blank=True)
    ended_at = models.DateTimeField(_("fin"), null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(_("durée (minutes)"), default=0)
    hourly_rate = models.DecimalField(
        _("taux horaire"),
        max_digits=10,
        decimal_places=2,
        default=Decimal("250.00"),
    )
    is_billable = models.BooleanField(_("facturable"), default=True)
    invoice = models.ForeignKey(
        "billing.Invoice",
        verbose_name=_("facture"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="time_entries",
    )

    class Meta:
        verbose_name = _("Saisie de temps")
        verbose_name_plural = _("Saisies de temps")
        ordering = ("-started_at", "-created_at")
        indexes = [
            models.Index(fields=["cabinet", "matter"], name="billing_time_cab_matter"),
            models.Index(fields=["cabinet", "user", "ended_at"], name="billing_time_cab_user"),
            models.Index(
                fields=["cabinet", "invoice"],
                name="billing_time_cab_invoice",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.duration_minutes} min — {self.description[:40]}"

    @property
    def is_running(self) -> bool:
        """Timer en cours."""
        return self.started_at is not None and self.ended_at is None

    @property
    def amount(self) -> Decimal:
        """Montant HT = duree * taux."""
        hours = Decimal(self.duration_minutes) / Decimal(60)
        return (hours * self.hourly_rate).quantize(Decimal("0.01"))


class Expense(TenantOwnedModel):
    """Débours / frais rattachés à un dossier."""

    matter = models.ForeignKey(
        "matters.Matter",
        verbose_name=_("dossier"),
        on_delete=models.CASCADE,
        related_name="expenses",
    )
    description = models.CharField(_("description"), max_length=500)
    amount = models.DecimalField(_("montant"), max_digits=12, decimal_places=2)
    currency = models.CharField(_("devise"), max_length=3, default=default_currency)
    incurred_on = models.DateField(_("date du frais"))
    is_billable = models.BooleanField(_("facturable"), default=True)
    invoice = models.ForeignKey(
        "billing.Invoice",
        verbose_name=_("facture"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="expenses",
    )

    class Meta:
        verbose_name = _("Débours")
        verbose_name_plural = _("Débours")
        ordering = ("-incurred_on", "-created_at")
        indexes = [
            models.Index(fields=["cabinet", "matter"], name="billing_exp_cab_matter"),
            models.Index(fields=["cabinet", "invoice"], name="billing_exp_cab_invoice"),
        ]

    def __str__(self) -> str:
        return f"{self.amount} {self.currency} — {self.description[:40]}"


class InvoiceSequence(TenantOwnedModel):
    """Compteur de numérotation légale par cabinet et année."""

    year = models.PositiveIntegerField(_("année"))
    last_number = models.PositiveIntegerField(_("dernier numéro"), default=0)

    class Meta:
        verbose_name = _("Séquence de facture")
        verbose_name_plural = _("Séquences de factures")
        constraints = [
            models.UniqueConstraint(
                fields=("cabinet", "year"),
                condition=models.Q(is_deleted=False),
                name="uniq_invoice_sequence_cabinet_year",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.cabinet_id}:{self.year}#{self.last_number}"


class Invoice(TenantOwnedModel):
    """Facture dossier (brouillon → émise → payée / annulée)."""

    number = models.CharField(
        _("numéro"),
        max_length=32,
        blank=True,
        db_index=True,
        help_text=_("Attribué à l'émission (FAC-YYYY-NNNNN)."),
    )
    matter = models.ForeignKey(
        "matters.Matter",
        verbose_name=_("dossier"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invoices",
    )
    status = models.CharField(
        _("statut"),
        max_length=20,
        choices=InvoiceStatus.choices,
        default=InvoiceStatus.DRAFT,
        db_index=True,
    )
    issued_at = models.DateField(_("date d'émission"), null=True, blank=True)
    due_at = models.DateField(_("échéance"), null=True, blank=True)
    paid_at = models.DateField(_("payée le"), null=True, blank=True)
    tax_rate = models.DecimalField(
        _("taux de TVA (%)"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("20.00"),
    )
    subtotal = models.DecimalField(
        _("total HT"),
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    tax_amount = models.DecimalField(
        _("montant TVA"),
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    total = models.DecimalField(
        _("total TTC"),
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    currency = models.CharField(_("devise"), max_length=3, default=default_currency)
    notes = models.TextField(_("notes"), blank=True)
    pdf_file = models.FileField(
        _("PDF"),
        upload_to=invoice_pdf_upload_to,
        storage=private_invoice_storage,
        blank=True,
        max_length=512,
    )

    class Meta:
        verbose_name = _("Facture")
        verbose_name_plural = _("Factures")
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("cabinet", "number"),
                condition=models.Q(is_deleted=False) & ~models.Q(number=""),
                name="uniq_invoice_number_per_cabinet",
            ),
        ]
        indexes = [
            models.Index(fields=["cabinet", "status"], name="billing_inv_cab_status"),
        ]

    def __str__(self) -> str:
        return self.number or f"Brouillon {self.pk}"

    def clean(self) -> None:
        """Interdit le hard-delete conceptuel des factures émises."""
        super().clean()
        if self.status != InvoiceStatus.DRAFT and not self.number:
            raise ValidationError({"number": _("Une facture émise doit avoir un numéro.")})

    @property
    def is_editable(self) -> bool:
        """Seuls les brouillons sont modifiables."""
        return self.status == InvoiceStatus.DRAFT


class InvoiceLine(TenantOwnedModel):
    """Ligne figée à l'émission (snapshot)."""

    invoice = models.ForeignKey(
        Invoice,
        verbose_name=_("facture"),
        on_delete=models.CASCADE,
        related_name="lines",
    )
    kind = models.CharField(
        _("type"),
        max_length=20,
        choices=InvoiceLineKind.choices,
        default=InvoiceLineKind.OTHER,
    )
    description = models.CharField(_("description"), max_length=500)
    quantity = models.DecimalField(
        _("quantité"),
        max_digits=10,
        decimal_places=2,
        default=Decimal("1.00"),
    )
    unit_price = models.DecimalField(
        _("prix unitaire HT"),
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    amount = models.DecimalField(
        _("montant HT"),
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    source_time_entry = models.ForeignKey(
        TimeEntry,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invoice_lines",
    )
    source_expense = models.ForeignKey(
        Expense,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invoice_lines",
    )

    class Meta:
        verbose_name = _("Ligne de facture")
        verbose_name_plural = _("Lignes de facture")
        ordering = ("created_at",)

    def __str__(self) -> str:
        return self.description[:60]
