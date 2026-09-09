"""Vues CRUD dossiers."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import QuerySet
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _g
from django.views import View
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView

from apps.calendar_app.models import EventType, HearingStatus
from apps.core.mixins import BreadcrumbMixin
from apps.matters.forms import MatterForm, MatterLawyerAssignForm, MatterPartyFormSet
from apps.matters.models import Matter, MatterScale, MatterStatus
from apps.matters.services import (
    archive_matter,
    assign_matter_lawyers,
    create_matter,
    matters_queryset,
    soft_delete_matter,
    update_matter,
)
from apps.tenants.mixins import CabinetPermissionMixin, PlatformAdminRequiredMixin
from apps.tenants.models import Cabinet, Membership
from apps.tenants.roles import PERM_ADD, PERM_CHANGE, PERM_VIEW, Role
from apps.tenants.services import is_platform_admin, is_super_admin, suggest_cabinets_for_practice_area


def _visible_matters(request: Any) -> QuerySet[Matter]:
    """Dossiers accessibles : tous pour le ministère, procuration valide pour le cabinet."""
    if is_platform_admin(request.user):
        return Matter.unscoped.select_related("responsible_lawyer", "cabinet")
    qs = Matter.unscoped.select_related("responsible_lawyer", "cabinet")
    cabinet = getattr(request, "cabinet", None)
    if cabinet is not None:
        from apps.procurations.services import authorized_matter_ids_for_cabinet

        qs = qs.filter(pk__in=authorized_matter_ids_for_cabinet(cabinet=cabinet))
    else:
        qs = qs.none()
    return qs


class MatterListView(CabinetPermissionMixin, BreadcrumbMixin, ListView):
    """Liste paginée + filtres."""

    template_name = "matters/matter_list.html"
    context_object_name = "matters"
    paginate_by = 10
    required_perm = PERM_VIEW
    cabinet_required = False

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        if is_platform_admin(request.user):
            self.cabinet_required = False
        else:
            self.cabinet_required = True
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [{"label": _g("Dossiers")}]

    def get_queryset(self) -> QuerySet[Matter]:
        return matters_queryset(
            cabinet=self.request.cabinet,  # type: ignore[attr-defined]
            user=self.request.user,  # type: ignore[arg-type]
            q=self.request.GET.get("q", ""),
            status=self.request.GET.get("status", ""),
            archived=self.request.GET.get("archived", ""),
            scale=self.request.GET.get("scale", ""),
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["filter_q"] = self.request.GET.get("q", "")
        ctx["filter_status"] = self.request.GET.get("status", "")
        ctx["filter_archived"] = self.request.GET.get("archived", "")
        ctx["filter_scale"] = self.request.GET.get("scale", "")
        ctx["status_choices"] = MatterStatus.choices
        ctx["scale_choices"] = MatterScale.choices
        return ctx


class MatterDetailView(CabinetPermissionMixin, BreadcrumbMixin, DetailView):
    """Fiche dossier + historique d'actions."""

    template_name = "matters/matter_detail.html"
    context_object_name = "matter"
    required_perm = PERM_VIEW
    cabinet_required = False

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        if is_platform_admin(request.user):
            self.cabinet_required = False
        else:
            self.cabinet_required = True
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[Matter]:
        return _visible_matters(self.request)

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Dossiers"), "url": reverse("matters:list")},
            {"label": self.object.reference},
        ]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        matter: Matter = self.object
        ctx["can_view_matter_history"] = is_super_admin(self.request.user)
        ctx["actions"] = (
            matter.actions.select_related("actor").all()[:50]
            if ctx["can_view_matter_history"]
            else []
        )
        ctx["can_delete_matter"] = is_platform_admin(self.request.user) and not matter.is_treated
        ctx["can_archive_matter"] = (
            is_platform_admin(self.request.user)
            and matter.status == MatterStatus.CLOSED
            and not matter.is_archived
        )
        ctx["can_edit_matter"] = is_platform_admin(self.request.user) and not matter.is_archived
        now = timezone.now()
        ctx["upcoming_hearings"] = (
            matter.events.filter(
                event_type=EventType.HEARING,
                starts_at__gte=now,
                hearing_status__in=(HearingStatus.SCHEDULED, ""),
            )
            .select_related("assigned_to")
            .order_by("starts_at")[:10]
        )
        from apps.procurations.services import get_valid_procuration, matter_has_valid_procuration

        ctx["has_valid_procuration"] = matter_has_valid_procuration(matter)
        ctx["valid_procuration"] = get_valid_procuration(matter)
        ctx["latest_procuration"] = (
            matter.procurations.select_related("granted_by").order_by("-created_at").first()
        )
        ctx["display_procuration"] = ctx["valid_procuration"] or ctx["latest_procuration"]
        ctx["parties"] = matter.parties.all().order_by("role", "name")
        ctx["assigned_lawyers"] = (
            matter.assigned_lawyers.select_related("lawyer").all()
        )
        cabinet = getattr(self.request, "cabinet", None)
        can_assign = (
            not is_platform_admin(self.request.user)
            and cabinet is not None
            and matter.cabinet_id == cabinet.pk
            and not matter.is_archived
            and ctx["has_valid_procuration"]
        )
        ctx["can_assign_lawyers"] = can_assign
        return ctx


def _lawyer_queryset(cabinet: Any) -> QuerySet[Any]:
    from django.contrib.auth import get_user_model

    if cabinet is None:
        return get_user_model().objects.none()
    user_ids = Membership.objects.filter(
        cabinet=cabinet,
        is_active=True,
        role__in=(Role.CAIMAN, Role.LAWYER),
    ).values_list("user_id", flat=True)

    return get_user_model().objects.filter(pk__in=user_ids).order_by("last_name", "email")


class MatterAssignLawyersView(CabinetPermissionMixin, BreadcrumbMixin, FormView):
    """Affectation d'avocats au dossier — cabinet titulaire uniquement."""

    template_name = "matters/matter_assign_lawyers.html"
    form_class = MatterLawyerAssignForm
    required_perm = PERM_CHANGE
    cabinet_required = True
    matter: Matter

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        if is_platform_admin(request.user):
            raise PermissionDenied(
                _g("L'affectation des avocats est réservée au cabinet d'avocats.")
            )
        self.matter = get_object_or_404(_visible_matters(request), pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Dossiers"), "url": reverse("matters:list")},
            {
                "label": self.matter.reference,
                "url": reverse("matters:detail", args=[self.matter.pk]),
            },
            {"label": _g("Affecter des avocats")},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["lawyer_queryset"] = _lawyer_queryset(self.matter.cabinet)
        return kwargs

    def get_initial(self) -> dict[str, Any]:
        current = list(self.matter.assigned_lawyers.select_related("lawyer"))
        return {
            "lawyers": [item.lawyer_id for item in current],
            "lead": next((item.lawyer_id for item in current if item.is_lead), None)
            or self.matter.responsible_lawyer_id,
        }

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["matter"] = self.matter
        form: MatterLawyerAssignForm = ctx["form"]
        raw = form["lawyers"].value()
        if raw is None:
            selected: list[Any] = []
        elif isinstance(raw, (list, tuple, set)):
            selected = list(raw)
        else:
            selected = [raw]
        ctx["selected_lawyer_ids"] = {str(item.pk if hasattr(item, "pk") else item) for item in selected}
        return ctx

    def form_valid(self, form: MatterLawyerAssignForm) -> HttpResponse:
        try:
            assign_matter_lawyers(
                matter=self.matter,
                user=self.request.user,  # type: ignore[arg-type]
                lawyers=list(form.cleaned_data["lawyers"]),
                lead=form.cleaned_data.get("lead"),
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _g("Avocats affectés au dossier."))
        return redirect("matters:detail", pk=self.matter.pk)


class MatterCreateView(CabinetPermissionMixin, BreadcrumbMixin, CreateView):
    """Création dossier — ministère uniquement (sans cabinet)."""

    template_name = "matters/matter_form.html"
    form_class = MatterForm
    required_perm = PERM_ADD
    platform_write = True
    cabinet_required = False

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not is_platform_admin(request.user):
            raise PermissionDenied(_g("Seul le Ministère de la Justice peut ouvrir un dossier."))
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Dossiers"), "url": reverse("matters:list")},
            {"label": _g("Nouveau dossier")},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        return kwargs

    def get_initial(self) -> dict[str, Any]:
        initial = super().get_initial()
        practice_area = self.request.GET.get("practice_area") or ""
        if practice_area:
            initial["practice_area"] = practice_area
        return initial

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        if self.request.POST:
            ctx["parties_formset"] = MatterPartyFormSet(self.request.POST)
        else:
            ctx["parties_formset"] = MatterPartyFormSet()
        return ctx

    def form_valid(self, form: MatterForm) -> HttpResponse:
        parties_formset = MatterPartyFormSet(self.request.POST)
        if not parties_formset.is_valid():
            messages.error(self.request, _g("Erreur dans les parties du dossier."))
            return self.form_invalid(form)

        data = form.cleaned_data
        try:
            matter = create_matter(
                user=self.request.user,  # type: ignore[arg-type]
                title=data["title"],
                description=data.get("description") or "",
                practice_area=data.get("practice_area") or "",
                jurisdiction=data.get("jurisdiction") or "",
                scale=data.get("scale") or MatterScale.NATIONAL,
                status=data.get("status") or MatterStatus.OPEN,
                opened_at=data.get("opened_at"),
                closed_at=data.get("closed_at"),
                notes=data.get("notes") or "",
            )
            for party_form in parties_formset:
                if party_form.cleaned_data and not party_form.cleaned_data.get("DELETE"):
                    from apps.matters.models import MatterParty

                    party = MatterParty(
                        cabinet=None,
                        matter=matter,
                        name=party_form.cleaned_data["name"],
                        role=party_form.cleaned_data["role"],
                        is_state_entity=party_form.cleaned_data.get("is_state_entity", False),
                        notes=party_form.cleaned_data.get("notes", ""),
                        created_by=self.request.user,
                    )
                    party.save()
        except (ValidationError, PermissionDenied) as exc:
            if isinstance(exc, ValidationError) and hasattr(exc, "message_dict"):
                for field, errs in exc.message_dict.items():
                    for err in errs:
                        form.add_error(field if field != "__all__" else None, err)
                return self.form_invalid(form)
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(
            self.request,
            _g("Dossier créé. Délivrez une procuration pour rattacher un cabinet d'avocats."),
        )
        return redirect("matters:detail", pk=matter.pk)


class MatterUpdateView(PlatformAdminRequiredMixin, BreadcrumbMixin, UpdateView):
    """Édition dossier — ministère uniquement."""

    template_name = "matters/matter_form.html"
    form_class = MatterForm
    context_object_name = "matter"
    cabinet_required = False

    def get_queryset(self) -> QuerySet[Matter]:
        return Matter.unscoped.all()

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Dossiers"), "url": reverse("matters:list")},
            {
                "label": self.object.reference,
                "url": reverse("matters:detail", args=[self.object.pk]),
            },
            {"label": _g("Modifier")},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        # Utiliser le cabinet du dossier pour les avocats (si nécessaire à l'avenir)
        cabinet = self.object.cabinet
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        if self.request.POST:
            ctx["parties_formset"] = MatterPartyFormSet(self.request.POST)
        else:
            # Pre-populate with existing parties
            existing_parties = self.object.parties.all()
            initial_data = []
            for party in existing_parties:
                initial_data.append({
                    'name': party.name,
                    'role': party.role,
                    'is_state_entity': party.is_state_entity,
                    'notes': party.notes,
                })
            ctx["parties_formset"] = MatterPartyFormSet(initial=initial_data)
        return ctx

    def form_valid(self, form: MatterForm) -> HttpResponse:
        parties_formset = MatterPartyFormSet(self.request.POST)
        if not parties_formset.is_valid():
            messages.error(self.request, _g("Erreur dans les parties du dossier."))
            return self.form_invalid(form)
        
        # Nettoyer les données avant de passer au service
        cleaned_data = form.cleaned_data.copy()
        # Retirer le champ responsible_lawyer s'il est présent
        cleaned_data.pop('responsible_lawyer', None)
        
        try:
            update_matter(
                matter=self.object,
                user=self.request.user,  # type: ignore[arg-type]
                **cleaned_data,
            )
            # Update parties - delete existing and recreate
            from apps.matters.models import MatterParty
            self.object.parties.all().delete()
            for party_form in parties_formset:
                if party_form.cleaned_data and not party_form.cleaned_data.get('DELETE'):
                    MatterParty.objects.create(
                        cabinet=self.object.cabinet,
                        matter=self.object,
                        name=party_form.cleaned_data['name'],
                        role=party_form.cleaned_data['role'],
                        is_state_entity=party_form.cleaned_data.get('is_state_entity', False),
                        notes=party_form.cleaned_data.get('notes', ''),
                        created_by=self.request.user,
                    )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _g("Dossier mis à jour."))
        return redirect("matters:detail", pk=self.object.pk)


class MatterDeleteView(PlatformAdminRequiredMixin, View):
    """Suppression logique — ministère uniquement."""

    http_method_names = ("post",)
    cabinet_required = False

    def post(self, request: Any, pk: str) -> HttpResponse:
        matter = get_object_or_404(Matter.unscoped.all(), pk=pk)
        try:
            soft_delete_matter(matter=matter, user=request.user)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
            return redirect("matters:detail", pk=pk)
        messages.success(request, _g("Dossier supprimé."))
        return redirect("matters:list")


class MatterArchiveView(PlatformAdminRequiredMixin, View):
    """Archive un dossier clos — ministère uniquement."""

    http_method_names = ("post",)
    cabinet_required = False

    def post(self, request: Any, pk: str) -> HttpResponse:
        matter = get_object_or_404(Matter.unscoped.all(), pk=pk)
        try:
            archive_matter(matter=matter, user=request.user)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
            return redirect("matters:detail", pk=pk)
        messages.success(request, _g("Dossier archivé."))
        return redirect("matters:detail", pk=pk)


class MatterCreateContextView(CabinetPermissionMixin, View):
    """JSON : clients, avocats et cabinets spécialisés pour l'ouverture d'un dossier."""

    required_perm = PERM_ADD
    platform_write = True
    http_method_names = ("get",)

    def get(self, request: Any, *args: Any, **kwargs: Any) -> JsonResponse:
        if not is_platform_admin(request.user):
            raise PermissionDenied(_g("Seul le Ministère de la Justice peut ouvrir un dossier."))
        practice_area = request.GET.get("practice_area") or ""
        cabinet = Cabinet.objects.filter(is_active=True).first()
        lawyers = []
        if cabinet:
            lawyers = [
                {"id": str(item.pk), "label": item.full_name or item.email}
                for item in _lawyer_queryset(cabinet)
            ]
        suggested = [
            {
                "id": str(item.pk),
                "name": item.name,
                "city": item.city,
                "bar_association": item.bar_association,
            }
            for item in suggest_cabinets_for_practice_area(practice_area_name=practice_area)
        ]
        return JsonResponse(
            {
                "cabinet_id": str(cabinet.pk) if cabinet is not None else "",
                "lawyers": lawyers,
                "suggested_cabinets": suggested,
            }
        )
