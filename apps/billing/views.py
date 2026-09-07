"""Vues facturation."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import QuerySet
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _g, gettext_lazy as _
from django.views import View
from django.views.generic import DetailView, FormView, ListView, TemplateView

from apps.billing.forms import ExpenseForm, InvoiceCreateForm, TimeEntryForm, TimerStartForm
from apps.billing.models import Expense, Invoice, InvoiceStatus, TimeEntry
from apps.billing.services import (
    cancel_invoice,
    create_draft_invoice,
    create_expense,
    create_time_entry,
    delete_expense,
    delete_time_entry,
    export_invoices_csv,
    issue_invoice,
    mark_invoice_overdue,
    mark_invoice_paid,
    start_timer,
    stop_timer,
    unbilled_expenses,
    unbilled_time_entries,
)
from apps.core.mixins import BreadcrumbMixin
from apps.core.money import format_money
from apps.matters.models import Matter
from apps.tenants.mixins import CabinetPermissionMixin
from apps.tenants.roles import PERM_ADD, PERM_CHANGE, PERM_DELETE, PERM_VIEW


class BillingHubView(CabinetPermissionMixin, BreadcrumbMixin, TemplateView):
    """Hub facturation : timers, liens rapides."""

    template_name = "billing/hub.html"
    required_perm = PERM_VIEW

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [{"label": _g("Facturation")}]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        cabinet = self.request.cabinet  # type: ignore[attr-defined]
        user = self.request.user
        ctx["running_timer"] = (
            TimeEntry.objects.filter(
                cabinet=cabinet,
                user=user,
                started_at__isnull=False,
                ended_at__isnull=True,
            )
            .select_related("matter")
            .first()
        )
        ctx["recent_times"] = TimeEntry.objects.select_related("matter", "user", "invoice").filter(
            cabinet=cabinet
        )[:8]
        ctx["recent_expenses"] = Expense.objects.select_related("matter").filter(cabinet=cabinet)[
            :8
        ]
        ctx["recent_invoices"] = Invoice.objects.select_related("matter").filter(cabinet=cabinet)[
            :8
        ]
        ctx["timer_form"] = TimerStartForm(matter_queryset=Matter.objects.order_by("reference"))
        return ctx


class TimeEntryListView(CabinetPermissionMixin, BreadcrumbMixin, ListView):
    """Liste des saisies de temps."""

    template_name = "billing/time_list.html"
    context_object_name = "entries"
    paginate_by = 10
    required_perm = PERM_VIEW

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Facturation"), "url": reverse("billing:hub")},
            {"label": _g("Temps")},
        ]

    def get_queryset(self) -> QuerySet[TimeEntry]:
        return TimeEntry.objects.select_related("matter", "user", "invoice").order_by("-created_at")


class TimeEntryCreateView(CabinetPermissionMixin, BreadcrumbMixin, FormView):
    """Saisie manuelle de temps."""

    template_name = "billing/time_form.html"
    form_class = TimeEntryForm
    required_perm = PERM_ADD

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Facturation"), "url": reverse("billing:hub")},
            {"label": _g("Temps"), "url": reverse("billing:time_list")},
            {"label": _g("Nouvelle saisie")},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["matter_queryset"] = Matter.objects.order_by("reference")
        return kwargs

    def form_valid(self, form: TimeEntryForm) -> HttpResponse:
        cabinet = self.request.cabinet  # type: ignore[attr-defined]
        try:
            create_time_entry(
                cabinet=cabinet,
                user=self.request.user,  # type: ignore[arg-type]
                matter=form.cleaned_data["matter"],
                description=form.cleaned_data["description"],
                duration_minutes=form.cleaned_data["duration_minutes"],
                hourly_rate=form.cleaned_data["hourly_rate"],
                is_billable=form.cleaned_data.get("is_billable", True),
            )
        except (ValidationError, PermissionDenied) as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, _("Temps enregistré."))
        return redirect("billing:time_list")


class TimerStartView(CabinetPermissionMixin, View):
    """Démarre un timer."""

    required_perm = PERM_ADD
    http_method_names = ("post",)

    def post(self, request: HttpRequest) -> HttpResponse:
        form = TimerStartForm(
            request.POST,
            matter_queryset=Matter.objects.order_by("reference"),
        )
        if not form.is_valid():
            messages.error(request, _("Impossible de démarrer le timer."))
            return redirect("billing:hub")
        try:
            start_timer(
                cabinet=request.cabinet,  # type: ignore[attr-defined]
                user=request.user,  # type: ignore[arg-type]
                matter=form.cleaned_data["matter"],
                description=form.cleaned_data.get("description") or "",
            )
        except ValidationError as exc:
            messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
            return redirect("billing:hub")
        messages.success(request, _("Timer démarré."))
        return redirect("billing:hub")


class TimerStopView(CabinetPermissionMixin, View):
    """Arrête le timer courant."""

    required_perm = PERM_CHANGE
    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        entry = get_object_or_404(TimeEntry, pk=pk)
        try:
            stop_timer(entry=entry, user=request.user)  # type: ignore[arg-type]
        except ValidationError as exc:
            messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
            return redirect("billing:hub")
        messages.success(request, _("Timer arrêté (%(m)s min).") % {"m": entry.duration_minutes})
        return redirect("billing:hub")


class TimeEntryDeleteView(CabinetPermissionMixin, View):
    """Supprime une saisie non facturée."""

    required_perm = PERM_DELETE
    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        entry = get_object_or_404(TimeEntry, pk=pk)
        try:
            delete_time_entry(entry=entry, user=request.user)  # type: ignore[arg-type]
        except ValidationError as exc:
            messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
            return redirect("billing:time_list")
        messages.success(request, _("Saisie supprimée."))
        return redirect("billing:time_list")


class ExpenseListView(CabinetPermissionMixin, BreadcrumbMixin, ListView):
    """Liste des débours."""

    template_name = "billing/expense_list.html"
    context_object_name = "expenses"
    paginate_by = 10
    required_perm = PERM_VIEW

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Facturation"), "url": reverse("billing:hub")},
            {"label": _g("Débours")},
        ]

    def get_queryset(self) -> QuerySet[Expense]:
        return Expense.objects.select_related("matter", "invoice").order_by("-incurred_on")


class ExpenseCreateView(CabinetPermissionMixin, BreadcrumbMixin, FormView):
    """Création d'un débours."""

    template_name = "billing/expense_form.html"
    form_class = ExpenseForm
    required_perm = PERM_ADD

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Facturation"), "url": reverse("billing:hub")},
            {"label": _g("Débours"), "url": reverse("billing:expense_list")},
            {"label": _g("Nouveau débours")},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["matter_queryset"] = Matter.objects.order_by("reference")
        return kwargs

    def form_valid(self, form: ExpenseForm) -> HttpResponse:
        try:
            create_expense(
                cabinet=self.request.cabinet,  # type: ignore[attr-defined]
                user=self.request.user,  # type: ignore[arg-type]
                matter=form.cleaned_data["matter"],
                description=form.cleaned_data["description"],
                amount=form.cleaned_data["amount"],
                incurred_on=form.cleaned_data["incurred_on"],
                is_billable=form.cleaned_data.get("is_billable", True),
            )
        except (ValidationError, PermissionDenied) as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, _("Débours enregistré."))
        return redirect("billing:expense_list")


class ExpenseDeleteView(CabinetPermissionMixin, View):
    """Supprime un débours non facturé."""

    required_perm = PERM_DELETE
    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        expense = get_object_or_404(Expense, pk=pk)
        try:
            delete_expense(expense=expense, user=request.user)  # type: ignore[arg-type]
        except ValidationError as exc:
            messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
            return redirect("billing:expense_list")
        messages.success(request, _("Débours supprimé."))
        return redirect("billing:expense_list")


class InvoiceListView(CabinetPermissionMixin, BreadcrumbMixin, ListView):
    """Liste des factures."""

    template_name = "billing/invoice_list.html"
    context_object_name = "invoices"
    paginate_by = 10
    required_perm = PERM_VIEW

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Facturation"), "url": reverse("billing:hub")},
            {"label": _g("Factures")},
        ]

    def get_queryset(self) -> QuerySet[Invoice]:
        qs = Invoice.objects.select_related("matter").order_by(
            "-issued_at", "-created_at"
        )
        status = self.request.GET.get("status")
        if status in InvoiceStatus.values:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["status_filter"] = self.request.GET.get("status", "")
        ctx["statuses"] = InvoiceStatus.choices
        return ctx


class InvoiceCreateView(CabinetPermissionMixin, BreadcrumbMixin, FormView):
    """Création brouillon depuis temps/frais."""

    template_name = "billing/invoice_form.html"
    form_class = InvoiceCreateForm
    required_perm = PERM_ADD

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Facturation"), "url": reverse("billing:hub")},
            {"label": _g("Factures"), "url": reverse("billing:invoice_list")},
            {"label": _g("Nouvelle facture")},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        cabinet = self.request.cabinet  # type: ignore[attr-defined]
        times = unbilled_time_entries(cabinet=cabinet)
        expenses = unbilled_expenses(cabinet=cabinet)
        kwargs["matter_queryset"] = Matter.objects.order_by("reference")
        kwargs["time_choices"] = [
            (
                str(t.pk),
                f"{t.matter.reference} — {t.description} ({t.duration_minutes} min, {format_money(t.amount)})",
            )
            for t in times
        ]
        kwargs["expense_choices"] = [
            (
                str(e.pk),
                f"{e.matter.reference} — {e.description} ({format_money(e.amount)})",
            )
            for e in expenses
        ]
        return kwargs

    def form_valid(self, form: InvoiceCreateForm) -> HttpResponse:
        try:
            invoice = create_draft_invoice(
                cabinet=self.request.cabinet,  # type: ignore[attr-defined]
                user=self.request.user,  # type: ignore[arg-type]
                matter=form.cleaned_data["matter"],
                time_entry_ids=form.cleaned_data.get("time_entries") or [],
                expense_ids=form.cleaned_data.get("expenses") or [],
                tax_rate=form.cleaned_data["tax_rate"],
                notes=form.cleaned_data.get("notes") or "",
            )
        except (ValidationError, PermissionDenied) as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, _("Brouillon de facture créé."))
        return redirect("billing:invoice_detail", pk=invoice.pk)


class InvoiceDetailView(CabinetPermissionMixin, BreadcrumbMixin, DetailView):
    """Détail facture + actions."""

    template_name = "billing/invoice_detail.html"
    context_object_name = "invoice"
    required_perm = PERM_VIEW

    def get_queryset(self) -> QuerySet[Invoice]:
        return Invoice.objects.select_related("matter", "cabinet").prefetch_related(
            "lines"
        )

    def get_breadcrumb(self) -> list[dict[str, str]]:
        crumbs = [
            {"label": _g("Facturation"), "url": reverse("billing:hub")},
            {"label": _g("Factures"), "url": reverse("billing:invoice_list")},
        ]
        inv = getattr(self, "object", None)
        if inv is not None:
            crumbs.append({"label": inv.number or _g("Brouillon")})
        return crumbs


class InvoiceIssueView(CabinetPermissionMixin, View):
    """Émet une facture brouillon."""

    required_perm = PERM_CHANGE
    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        invoice = get_object_or_404(Invoice, pk=pk)
        try:
            issue_invoice(invoice=invoice, user=request.user)  # type: ignore[arg-type]
        except ValidationError as exc:
            messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
            return redirect("billing:invoice_detail", pk=pk)
        messages.success(request, _("Facture émise : %(n)s") % {"n": invoice.number})
        return redirect("billing:invoice_detail", pk=pk)


class InvoiceMarkPaidView(CabinetPermissionMixin, View):
    """Marque payée."""

    required_perm = PERM_CHANGE
    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        invoice = get_object_or_404(Invoice, pk=pk)
        try:
            mark_invoice_paid(invoice=invoice, user=request.user)  # type: ignore[arg-type]
        except ValidationError as exc:
            messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
            return redirect("billing:invoice_detail", pk=pk)
        messages.success(request, _("Facture marquée comme payée."))
        return redirect("billing:invoice_detail", pk=pk)


class InvoiceMarkOverdueView(CabinetPermissionMixin, View):
    """Marque impayée."""

    required_perm = PERM_CHANGE
    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        invoice = get_object_or_404(Invoice, pk=pk)
        try:
            mark_invoice_overdue(invoice=invoice, user=request.user)  # type: ignore[arg-type]
        except ValidationError as exc:
            messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
            return redirect("billing:invoice_detail", pk=pk)
        messages.success(request, _("Facture marquée impayée."))
        return redirect("billing:invoice_detail", pk=pk)


class InvoiceCancelView(CabinetPermissionMixin, View):
    """Annule une facture (ou soft-delete brouillon)."""

    required_perm = PERM_CHANGE
    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        invoice = get_object_or_404(Invoice, pk=pk)
        try:
            cancel_invoice(invoice=invoice, user=request.user)  # type: ignore[arg-type]
        except ValidationError as exc:
            messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
            return redirect("billing:invoice_detail", pk=pk)
        messages.success(request, _("Facture annulée / supprimée."))
        return redirect("billing:invoice_list")


class InvoicePdfDownloadView(CabinetPermissionMixin, View):
    """Téléchargement PDF protégé."""

    required_perm = PERM_VIEW
    http_method_names = ("get",)

    def get(self, request: HttpRequest, pk: str) -> HttpResponse:
        invoice = get_object_or_404(
            Invoice.objects.select_related("cabinet", "matter", "created_by"),
            pk=pk,
        )
        from apps.billing.services import (
            invoice_needs_pdf,
            render_invoice_pdf_bytes,
            store_invoice_pdf,
        )

        if invoice.status == InvoiceStatus.DRAFT:
            pdf_bytes = render_invoice_pdf_bytes(invoice)
            filename = f"proforma-{invoice.pk}.pdf"
            response = FileResponse(
                BytesIO(pdf_bytes),
                as_attachment=True,
                filename=filename,
                content_type="application/pdf",
            )
        else:
            if invoice_needs_pdf(invoice):
                pdf_bytes = render_invoice_pdf_bytes(invoice)
                store_invoice_pdf(invoice=invoice, pdf_bytes=pdf_bytes)
                invoice.refresh_from_db()
            response = FileResponse(
                invoice.pdf_file.open("rb"),
                as_attachment=True,
                filename=f"{invoice.number or invoice.pk}.pdf",
                content_type="application/pdf",
            )
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        return response


class InvoiceExportCsvView(CabinetPermissionMixin, View):
    """Export CSV des factures."""

    required_perm = PERM_VIEW
    http_method_names = ("get",)

    def get(self, request: HttpRequest) -> HttpResponse:
        stream = export_invoices_csv(
            cabinet=request.cabinet,  # type: ignore[attr-defined]
            user=request.user,  # type: ignore[arg-type]
        )
        response = HttpResponse(stream.read(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="factures.csv"'
        return response
