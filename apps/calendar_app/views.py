"""Vues agenda."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import QuerySet
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _g
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.calendar_app.forms import EventForm, HearingForm
from apps.calendar_app.models import Event, EventType, HearingAttachment, HearingStatus
from apps.calendar_app.services import (
    create_event,
    delete_hearing_attachment,
    events_queryset,
    hearings_queryset,
    mark_event_done,
    save_hearing_report,
    soft_delete_event,
    update_event,
    update_hearing_status,
)
from apps.core.kinshasa_courts import kinshasa_court_filter_choices
from apps.core.mixins import BreadcrumbMixin
from apps.matters.models import Matter
from apps.tenants.mixins import CabinetPermissionMixin
from apps.tenants.models import Cabinet
from apps.tenants.roles import PERM_ADD, PERM_CHANGE, PERM_DELETE, PERM_VIEW
from apps.tenants.services import is_platform_admin


def _platform_sets_no_cabinet(view: CabinetPermissionMixin, request: Any) -> None:
    """Supervision ministère : pas de cabinet courant requis pour la lecture."""
    if is_platform_admin(request.user):
        view.cabinet_required = False
    else:
        view.cabinet_required = True


def _visible_events(request: Any) -> QuerySet[Event]:
    """Événements visibles : tous cabinets pour le ministère, sinon cabinet courant."""
    related = ("matter", "assigned_to", "created_by", "matter__cabinet", "cabinet")
    if is_platform_admin(request.user):
        return Event.unscoped.select_related(*related).prefetch_related("attachments")
    return Event.objects.select_related(*related).prefetch_related("attachments")


class CalendarListView(CabinetPermissionMixin, BreadcrumbMixin, ListView):
    """Agenda : 30 jours à venir + tâches."""

    template_name = "calendar_app/event_list.html"
    context_object_name = "events"
    paginate_by = 10
    required_perm = PERM_VIEW

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [{"label": _g("Agenda")}]

    def get_queryset(self) -> QuerySet[Event]:
        now = timezone.now()
        return events_queryset(
            cabinet=self.request.cabinet,  # type: ignore[attr-defined]
            from_dt=now - timedelta(days=1),
            to_dt=now + timedelta(days=60),
            event_type=self.request.GET.get("type", ""),
            matter_id=self.request.GET.get("matter", ""),
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["event_types"] = EventType.choices
        ctx["filter_type"] = self.request.GET.get("type", "")
        ctx["filter_matter"] = self.request.GET.get("matter", "")
        ctx["matters"] = Matter.objects.order_by("reference")
        ctx["open_tasks"] = Event.objects.filter(
            event_type=EventType.TASK,
            is_done=False,
        ).order_by("starts_at")[:20]
        return ctx


class EventDetailView(CabinetPermissionMixin, BreadcrumbMixin, DetailView):
    """Fiche événement / tâche."""

    template_name = "calendar_app/event_detail.html"
    context_object_name = "event"
    required_perm = PERM_VIEW
    cabinet_required = False

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        _platform_sets_no_cabinet(self, request)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[Event]:
        return _visible_events(self.request)

    def get_breadcrumb(self) -> list[dict[str, str]]:
        if self.object.event_type == EventType.HEARING:
            return [
                {"label": _g("Audiences"), "url": reverse("hearings:list")},
                {"label": self.object.title},
            ]
        return [
            {"label": _g("Agenda"), "url": reverse("calendar:list")},
            {"label": self.object.title},
        ]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["is_platform_supervision"] = is_platform_admin(self.request.user)
        return ctx


class EventCreateView(CabinetPermissionMixin, BreadcrumbMixin, CreateView):
    """Création événement / tâche."""

    template_name = "calendar_app/event_form.html"
    form_class = EventForm
    required_perm = PERM_ADD

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Agenda"), "url": reverse("calendar:list")},
            {"label": _g("Nouvel événement")},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["matter_queryset"] = Matter.objects.order_by("reference")
        return kwargs

    def get_initial(self) -> dict[str, Any]:
        initial = super().get_initial()
        matter_id = self.request.GET.get("matter")
        if matter_id:
            initial["matter"] = matter_id
        if self.request.GET.get("type") == EventType.TASK:
            initial["event_type"] = EventType.TASK
        if self.request.GET.get("type") == EventType.HEARING:
            initial["event_type"] = EventType.HEARING
        return initial

    def form_valid(self, form: EventForm) -> HttpResponse:
        data = form.cleaned_data
        try:
            event = create_event(
                cabinet=self.request.cabinet,  # type: ignore[attr-defined]
                user=self.request.user,  # type: ignore[arg-type]
                title=data["title"],
                starts_at=data["starts_at"],
                event_type=data.get("event_type") or EventType.APPOINTMENT,
                matter=data.get("matter"),
                description=data.get("description") or "",
                ends_at=data.get("ends_at"),
                all_day=data.get("all_day") or False,
                location=data.get("location") or "",
                remind_at=data.get("remind_at"),
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _g("Événement créé."))
        return redirect("calendar:event_detail", pk=event.pk)


class EventUpdateView(CabinetPermissionMixin, BreadcrumbMixin, UpdateView):
    """Édition."""

    template_name = "calendar_app/event_form.html"
    form_class = EventForm
    context_object_name = "event"
    required_perm = PERM_CHANGE

    def get_queryset(self) -> QuerySet[Event]:
        return Event.objects.all()

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Agenda"), "url": reverse("calendar:list")},
            {"label": self.object.title, "url": reverse("calendar:event_detail", kwargs={"pk": self.object.pk})},
            {"label": _g("Modifier")},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["matter_queryset"] = Matter.objects.order_by("reference")
        return kwargs

    def form_valid(self, form: EventForm) -> HttpResponse:
        try:
            update_event(
                event=self.object,
                user=self.request.user,  # type: ignore[arg-type]
                **form.cleaned_data,
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _g("Événement mis à jour."))
        return redirect("calendar:event_detail", pk=self.object.pk)


class EventDoneView(CabinetPermissionMixin, View):
    """Marquer tâche terminée."""

    required_perm = PERM_CHANGE
    http_method_names = ("post",)

    def post(self, request: Any, pk: str) -> HttpResponse:
        event = get_object_or_404(Event, pk=pk)
        mark_event_done(event=event, user=request.user, done=True)
        messages.success(request, _g("Tâche terminée."))
        return redirect("calendar:event_detail", pk=event.pk)


class EventDeleteView(CabinetPermissionMixin, View):
    """Suppression."""

    required_perm = PERM_DELETE
    http_method_names = ("post",)

    def post(self, request: Any, pk: str) -> HttpResponse:
        event = get_object_or_404(Event, pk=pk)
        is_hearing = event.event_type == EventType.HEARING
        soft_delete_event(event=event, user=request.user)
        messages.success(request, _g("Événement supprimé."))
        if is_hearing:
            return redirect("hearings:list")
        return redirect("calendar:list")


class HearingListView(CabinetPermissionMixin, BreadcrumbMixin, ListView):
    """Liste des audiences judiciaires."""

    template_name = "calendar_app/hearing_list.html"
    context_object_name = "hearings"
    paginate_by = 15
    required_perm = PERM_VIEW
    cabinet_required = False

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        _platform_sets_no_cabinet(self, request)
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [{"label": _g("Audiences")}]

    def get_queryset(self) -> QuerySet[Event]:
        period = self.request.GET.get("period", "upcoming")
        now = timezone.now()
        platform = is_platform_admin(self.request.user)  # type: ignore[arg-type]
        kwargs: dict[str, Any] = {
            "cabinet": getattr(self.request, "cabinet", None),
            "matter_id": self.request.GET.get("matter", ""),
            "hearing_status": self.request.GET.get("status", ""),
            "court": self.request.GET.get("court", ""),
            "cabinet_id": self.request.GET.get("cabinet", "") if platform else "",
            "cross_cabinet": platform,
        }
        if period == "past":
            kwargs["to_dt"] = now
        elif period == "upcoming":
            kwargs["from_dt"] = now - timedelta(days=1)
            if not kwargs["hearing_status"]:
                kwargs["upcoming_only"] = True
        elif period == "all":
            pass
        return hearings_queryset(**kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        platform = is_platform_admin(self.request.user)  # type: ignore[arg-type]
        ctx["hearing_statuses"] = HearingStatus.choices
        ctx["filter_period"] = self.request.GET.get("period", "upcoming")
        ctx["filter_status"] = self.request.GET.get("status", "")
        ctx["filter_matter"] = self.request.GET.get("matter", "")
        ctx["filter_court"] = self.request.GET.get("court", "")
        ctx["filter_cabinet"] = self.request.GET.get("cabinet", "")
        ctx["is_platform_supervision"] = platform
        ctx["court_choices"] = kinshasa_court_filter_choices()
        if platform:
            ctx["matters"] = Matter.unscoped.order_by("reference")[:200]
            ctx["cabinets"] = Cabinet.objects.filter(is_active=True).order_by("name")
        else:
            ctx["matters"] = Matter.objects.order_by("reference")
            ctx["cabinets"] = []
        return ctx


class HearingCreateView(CabinetPermissionMixin, BreadcrumbMixin, CreateView):
    """Planifie une audience."""

    template_name = "calendar_app/hearing_form.html"
    form_class = HearingForm
    required_perm = PERM_ADD

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Audiences"), "url": reverse("hearings:list")},
            {"label": _g("Nouvelle audience")},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["matter_queryset"] = Matter.objects.order_by("reference")
        kwargs["matter_locked"] = bool(self.request.GET.get("matter"))
        return kwargs

    def get_initial(self) -> dict[str, Any]:
        initial = super().get_initial()
        matter_id = self.request.GET.get("matter")
        if matter_id:
            initial["matter"] = matter_id
        initial["hearing_status"] = HearingStatus.SCHEDULED
        return initial

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        matter_id = self.request.GET.get("matter")
        if not matter_id:
            form = ctx.get("form")
            if form is not None and "matter" in form.fields:
                matter_id = form["matter"].value()
        ctx["matter"] = Matter.objects.filter(pk=matter_id).first() if matter_id else None
        return ctx

    def form_valid(self, form: HearingForm) -> HttpResponse:
        data = form.cleaned_data
        try:
            event = create_event(
                cabinet=self.request.cabinet,  # type: ignore[attr-defined]
                user=self.request.user,  # type: ignore[arg-type]
                title=data["title"],
                starts_at=data["starts_at"],
                event_type=EventType.HEARING,
                matter=data.get("matter"),
                description=data.get("description") or "",
                ends_at=data.get("ends_at"),
                all_day=data.get("all_day") or False,
                location=data.get("location") or "",
                chamber=data.get("chamber") or "",
                hearing_status=data.get("hearing_status") or HearingStatus.SCHEDULED,
                remind_at=data.get("remind_at"),
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _g("Audience planifiée."))
        return redirect("calendar:event_detail", pk=event.pk)


class HearingUpdateView(CabinetPermissionMixin, BreadcrumbMixin, UpdateView):
    """Modifie une audience."""

    template_name = "calendar_app/hearing_form.html"
    form_class = HearingForm
    context_object_name = "hearing"
    required_perm = PERM_CHANGE

    def get_queryset(self) -> QuerySet[Event]:
        return Event.objects.filter(event_type=EventType.HEARING)

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Audiences"), "url": reverse("hearings:list")},
            {
                "label": self.object.title,
                "url": reverse("calendar:event_detail", kwargs={"pk": self.object.pk}),
            },
            {"label": _g("Modifier")},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["matter_queryset"] = Matter.objects.order_by("reference")
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["matter"] = getattr(self.object, "matter", None)
        return ctx

    def form_valid(self, form: HearingForm) -> HttpResponse:
        data = form.cleaned_data.copy()
        report_files = list(self.request.FILES.getlist("report_files"))
        try:
            update_event(
                event=self.object,
                user=self.request.user,  # type: ignore[arg-type]
                event_type=EventType.HEARING,
                **data,
            )
            if report_files:
                save_hearing_report(
                    event=self.object,
                    user=self.request.user,  # type: ignore[arg-type]
                    uploads=report_files,
                )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _g("Audience mise à jour."))
        return redirect("calendar:event_detail", pk=self.object.pk)


class HearingStatusView(CabinetPermissionMixin, View):
    """Change le statut d'une audience (tenue, reportée, annulée)."""

    required_perm = PERM_CHANGE
    http_method_names = ("post",)

    def post(self, request: Any, pk: str) -> HttpResponse:
        event = get_object_or_404(Event, pk=pk, event_type=EventType.HEARING)
        status = request.POST.get("status", "")
        try:
            update_hearing_status(
                event=event,
                user=request.user,
                hearing_status=status,
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
            return redirect("calendar:event_detail", pk=pk)
        messages.success(request, _g("Statut d'audience mis à jour."))
        return redirect("calendar:event_detail", pk=pk)


class HearingReportView(CabinetPermissionMixin, View):
    """Joint un ou plusieurs fichiers Word/PDF à une audience."""

    required_perm = PERM_CHANGE
    http_method_names = ("post",)

    def post(self, request: Any, pk: str) -> HttpResponse:
        event = get_object_or_404(Event, pk=pk, event_type=EventType.HEARING)
        uploads = list(request.FILES.getlist("report_files"))
        if not uploads and request.FILES.get("report_file"):
            uploads = [request.FILES["report_file"]]
        try:
            save_hearing_report(
                event=event,
                user=request.user,
                uploads=uploads,
                mark_held=bool(request.POST.get("mark_held")),
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
            return redirect("calendar:event_detail", pk=pk)
        messages.success(request, _g("Fichier(s) enregistré(s)."))
        return redirect("calendar:event_detail", pk=pk)


class HearingReportDownloadView(CabinetPermissionMixin, View):
    """Téléchargement du premier fichier (compatibilité) ou legacy."""

    required_perm = PERM_VIEW
    http_method_names = ("get",)
    cabinet_required = False

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        _platform_sets_no_cabinet(self, request)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, pk: str) -> HttpResponse:
        event = get_object_or_404(_visible_events(request), pk=pk, event_type=EventType.HEARING)
        attachment = event.attachments.order_by("created_at").first()
        if attachment is not None:
            return _serve_hearing_attachment(attachment, as_attachment=True)
        return _serve_legacy_hearing_report(event, as_attachment=True)


class HearingReportPreviewView(CabinetPermissionMixin, View):
    """Aperçu inline du premier PDF (compatibilité) ou legacy."""

    required_perm = PERM_VIEW
    http_method_names = ("get",)
    cabinet_required = False

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        _platform_sets_no_cabinet(self, request)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, pk: str) -> HttpResponse:
        event = get_object_or_404(_visible_events(request), pk=pk, event_type=EventType.HEARING)
        attachment = next(
            (item for item in event.attachments.all() if item.can_preview),
            None,
        )
        if attachment is not None:
            return _serve_hearing_attachment(attachment, as_attachment=False)
        if not event.hearing_report_file:
            raise Http404(_g("Aucun rapport n'est joint à cette audience."))
        if not event.hearing_report_can_preview:
            return redirect("hearings:report_download", pk=pk)
        return _serve_legacy_hearing_report(event, as_attachment=False)


class HearingAttachmentDownloadView(CabinetPermissionMixin, View):
    """Téléchargement d'une pièce jointe d'audience."""

    required_perm = PERM_VIEW
    http_method_names = ("get",)
    cabinet_required = False

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        _platform_sets_no_cabinet(self, request)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, pk: str, attachment_id: str) -> HttpResponse:
        event = get_object_or_404(_visible_events(request), pk=pk, event_type=EventType.HEARING)
        attachment = get_object_or_404(event.attachments.select_related("event"), pk=attachment_id)
        return _serve_hearing_attachment(attachment, as_attachment=True)


class HearingAttachmentPreviewView(CabinetPermissionMixin, View):
    """Aperçu PDF d'une pièce jointe."""

    required_perm = PERM_VIEW
    http_method_names = ("get",)
    cabinet_required = False

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        _platform_sets_no_cabinet(self, request)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, pk: str, attachment_id: str) -> HttpResponse:
        event = get_object_or_404(_visible_events(request), pk=pk, event_type=EventType.HEARING)
        attachment = get_object_or_404(event.attachments.select_related("event"), pk=attachment_id)
        if not attachment.can_preview:
            return redirect(
                "hearings:attachment_download",
                pk=pk,
                attachment_id=attachment.pk,
            )
        return _serve_hearing_attachment(attachment, as_attachment=False)


class HearingAttachmentDeleteView(CabinetPermissionMixin, View):
    """Suppression d'une pièce jointe."""

    required_perm = PERM_CHANGE
    http_method_names = ("post",)

    def post(self, request: Any, pk: str, attachment_id: str) -> HttpResponse:
        attachment = get_object_or_404(
            HearingAttachment.objects.select_related("event"),
            pk=attachment_id,
            event_id=pk,
            event__event_type=EventType.HEARING,
        )
        try:
            delete_hearing_attachment(attachment=attachment, user=request.user)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
            return redirect("calendar:event_detail", pk=pk)
        messages.success(request, _g("Fichier retiré."))
        return redirect("calendar:event_detail", pk=pk)


def _serve_hearing_attachment(attachment: HearingAttachment, *, as_attachment: bool) -> FileResponse:
    """Sert une pièce jointe en téléchargement ou aperçu."""
    if not attachment.file:
        raise Http404(_g("Fichier introuvable."))
    filename = attachment.original_filename or "rapport-audience.pdf"
    response = FileResponse(
        attachment.file.open("rb"),
        as_attachment=as_attachment,
        filename=filename,
        content_type=attachment.mime_type,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    if not as_attachment:
        response["Content-Security-Policy"] = (
            "default-src 'none'; img-src 'self' data:; style-src 'none'; sandbox"
        )
    return response


def _serve_legacy_hearing_report(event: Event, *, as_attachment: bool) -> FileResponse:
    """Sert le rapport legacy en téléchargement ou aperçu."""
    if not event.hearing_report_file:
        raise Http404(_g("Aucun rapport n'est joint à cette audience."))
    filename = event.hearing_report_filename or "rapport-audience.pdf"
    response = FileResponse(
        event.hearing_report_file.open("rb"),
        as_attachment=as_attachment,
        filename=filename,
        content_type=event.hearing_report_mime_type,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    if not as_attachment:
        response["Content-Security-Policy"] = (
            "default-src 'none'; img-src 'self' data:; style-src 'none'; sandbox"
        )
    return response
