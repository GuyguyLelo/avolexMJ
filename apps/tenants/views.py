"""Vues cabinet : sélecteur, invitations, CRUD superviseur."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import QuerySet
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _g, gettext_lazy as _
from django.views import View
from django.views.generic import (
    CreateView,
    DetailView,
    FormView,
    ListView,
    RedirectView,
    UpdateView,
)

from apps.core.dashboard import get_cabinet_overview
from apps.core.mixins import BreadcrumbMixin
from apps.tenants.forms import CabinetCreateForm, CabinetForm, InviteMemberForm
from apps.tenants.legal_areas import ensure_default_legal_practice_areas
from apps.tenants.mixins import (
    CabinetPermissionMixin,
    CabinetRequiredMixin,
    PlatformAdminRequiredMixin,
)
from apps.tenants.models import Cabinet, Membership
from apps.tenants.roles import PERM_INVITE, Role
from apps.tenants.services import (
    add_cabinet_member,
    attach_cabinet_contract,
    cabinet_practice_areas_queryset,
    cabinets_queryset,
    can_manage_members,
    create_cabinet_as_platform_admin,
    delete_cabinet_as_platform_admin,
    invite_member,
    legal_practice_areas_queryset,
    switch_cabinet,
    update_cabinet_as_platform_admin,
)


def _extra_members_from_request(request: HttpRequest) -> list[dict[str, str]]:
    """Extrait les membres additionnels saisis sur le formulaire de création."""
    emails = request.POST.getlist("extra_member_email")
    if not emails:
        return []
    first_names = request.POST.getlist("extra_member_first_name")
    last_names = request.POST.getlist("extra_member_last_name")
    phones = request.POST.getlist("extra_member_phone")
    roles = request.POST.getlist("extra_member_role")
    members: list[dict[str, str]] = []
    for idx, raw_email in enumerate(emails):
        email = raw_email.strip()
        if not email:
            continue
        role = roles[idx].strip() if idx < len(roles) else Role.LAWYER
        if role not in {choice[0] for choice in Role.choices}:
            role = Role.LAWYER
        members.append(
            {
                "email": email,
                "first_name": (first_names[idx] if idx < len(first_names) else "").strip(),
                "last_name": (last_names[idx] if idx < len(last_names) else "").strip(),
                "phone": (phones[idx] if idx < len(phones) else "").strip(),
                "role": role,
            }
        )
    return members


class SwitchCabinetView(CabinetRequiredMixin, View):
    """Change le cabinet courant (POST)."""

    cabinet_required = False  # on peut switch même si session invalide
    http_method_names = ("post",)

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Bascule vers le cabinet demandé."""
        cabinet_id = request.POST.get("cabinet_id", "")
        try:
            cabinet = switch_cabinet(
                request=request,
                user=request.user,  # type: ignore[arg-type]
                cabinet_id=cabinet_id,
            )
        except PermissionDenied:
            messages.error(request, _("Accès refusé à ce cabinet."))
            return redirect("core:home")
        except (Cabinet.DoesNotExist, ValidationError, ValueError):
            messages.error(request, _("Cabinet introuvable."))
            return redirect("core:home")

        messages.success(request, _("Cabinet actif : %(name)s") % {"name": cabinet.name})
        next_url = request.POST.get("next") or reverse("core:home")
        return HttpResponseRedirect(next_url)


class InviteMemberView(CabinetPermissionMixin, BreadcrumbMixin, FormView):
    """Invite un collaborateur dans le cabinet courant."""

    template_name = "tenants/invite_member.html"
    form_class = InviteMemberForm
    required_perm = PERM_INVITE
    success_url = "/app/"

    def get_breadcrumb(self) -> list[dict[str, str]]:
        """Fil d'Ariane invitation."""
        return [
            {"label": _g("Équipe"), "url": reverse("tenants:member_list")},
            {"label": _g("Inviter")},
        ]

    def get_success_url(self) -> str:
        """Redirige vers la liste des invitations."""
        return reverse("tenants:member_list")

    def form_valid(self, form: InviteMemberForm) -> HttpResponse:
        """Crée l'invitation et envoie l'e-mail."""
        cabinet = self.request.cabinet  # type: ignore[attr-defined]
        try:
            invitation = invite_member(
                cabinet=cabinet,
                email=form.cleaned_data["email"],
                role=form.cleaned_data["role"],
                invited_by=self.request.user,  # type: ignore[arg-type]
            )
        except (ValidationError, PermissionDenied) as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)

        accept_url = self.request.build_absolute_uri(
            reverse("accounts:accept_invitation", kwargs={"token": invitation.token})
        )
        send_mail(
            subject=str(
                _("Invitation à rejoindre %(cabinet)s sur AvoLex") % {"cabinet": cabinet.name}
            ),
            message=str(
                _(
                    "Vous êtes invité(e) à rejoindre le cabinet %(cabinet)s sur AvoLex.\n\n"
                    "Accepter l'invitation : %(url)s\n\n"
                    "Cette invitation expire le %(expires)s."
                )
                % {
                    "cabinet": cabinet.name,
                    "url": accept_url,
                    "expires": invitation.expires_at.strftime("%d/%m/%Y %H:%M"),
                }
            ),
            from_email=None,
            recipient_list=[invitation.email],
            fail_silently=False,
        )
        messages.success(
            self.request, _("Invitation envoyée à %(email)s.") % {"email": invitation.email}
        )
        return super().form_valid(form)


class InvitationListView(RedirectView):
    """Ancienne liste d'invitations → page équipe."""

    pattern_name = "tenants:member_list"
    query_string = True


def _apply_form_errors(form: CabinetForm, exc: ValidationError) -> None:
    if hasattr(exc, "message_dict"):
        for field, errs in exc.message_dict.items():
            for err in errs:
                form.add_error(field if field != "__all__" else None, err)
        return
    form.add_error(None, exc)


class CabinetListView(PlatformAdminRequiredMixin, BreadcrumbMixin, ListView):
    """Liste des cabinets avocats (supervision)."""

    template_name = "tenants/cabinet_list.html"
    context_object_name = "cabinets"
    paginate_by = 15

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [{"label": _g("Cabinets avocats")}]

    def get_queryset(self) -> QuerySet[Cabinet]:
        return cabinets_queryset(q=self.request.GET.get("q", ""))

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["filter_q"] = self.request.GET.get("q", "")
        return ctx


class CabinetDetailView(PlatformAdminRequiredMixin, BreadcrumbMixin, DetailView):
    """Fiche cabinet avocat (supervision)."""

    template_name = "tenants/cabinet_detail.html"
    context_object_name = "cabinet"

    def get_queryset(self) -> QuerySet[Cabinet]:
        return Cabinet.objects.all()

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Cabinets avocats"), "url": reverse("tenants:cabinet_list")},
            {"label": str(self.object)},
        ]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        cabinet: Cabinet = self.object
        memberships = (
            Membership.objects.filter(cabinet=cabinet, is_active=True)
            .select_related("user")
            .order_by("role", "user__email")
        )
        ctx["memberships"] = memberships
        ctx["can_manage_members"] = can_manage_members(
            user=self.request.user,  # type: ignore[arg-type]
            cabinet=cabinet,
        )
        ctx["owner_membership"] = next(
            (m for m in memberships if m.role == Role.CAIMAN),
            None,
        )
        ctx["overview"] = get_cabinet_overview(cabinet)
        ensure_default_legal_practice_areas()
        ctx["specialty_links"] = cabinet_practice_areas_queryset(cabinet=cabinet)
        taken_ids = [link.practice_area_id for link in ctx["specialty_links"]]
        ctx["available_practice_areas"] = legal_practice_areas_queryset(active_only=True).exclude(
            pk__in=taken_ids
        )
        return ctx


class CabinetCreateView(PlatformAdminRequiredMixin, BreadcrumbMixin, CreateView):
    """Création d'un cabinet avocat (supervision)."""

    template_name = "tenants/cabinet_form.html"
    form_class = CabinetCreateForm

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["member_role_choices"] = Role.choices
        return ctx

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Cabinets avocats"), "url": reverse("tenants:cabinet_list")},
            {"label": _g("Nouveau cabinet")},
        ]

    def form_valid(self, form: CabinetCreateForm) -> HttpResponse:
        data = form.cleaned_data
        extra_members = _extra_members_from_request(self.request)
        try:
            with transaction.atomic():
                cabinet, _membership, _owner = create_cabinet_as_platform_admin(
                    actor=self.request.user,  # type: ignore[arg-type]
                    name=data["name"],
                    owner_email=data["owner_email"],
                    owner_first_name=data.get("owner_first_name") or "",
                    owner_last_name=data.get("owner_last_name") or "",
                    contract_number=data.get("contract_number") or "",
                    legal_name=data.get("legal_name") or "",
                    siret=data.get("siret") or "",
                    vat_number=data.get("vat_number") or "",
                    bar_association=data.get("bar_association") or "",
                    address_line1=data.get("address_line1") or "",
                    country="CD",
                )
                owner_email = data["owner_email"].strip().lower()
                added = 0
                for member in extra_members:
                    if member["email"].strip().lower() == owner_email:
                        continue
                    add_cabinet_member(
                        actor=self.request.user,  # type: ignore[arg-type]
                        cabinet=cabinet,
                        email=member["email"],
                        role=member["role"],
                        first_name=member["first_name"],
                        last_name=member["last_name"],
                        phone=member["phone"],
                    )
                    added += 1
                attach_cabinet_contract(
                    cabinet=cabinet,
                    uploaded=data.get("contract_file"),
                )
        except (ValidationError, PermissionDenied) as exc:
            if isinstance(exc, ValidationError):
                _apply_form_errors(form, exc)
                return self.form_invalid(form)
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        if added:
            messages.success(
                self.request,
                _g("Cabinet avocat créé avec %(count)s membre(s) additionnel(s).")
                % {"count": added},
            )
        else:
            messages.success(self.request, _g("Cabinet avocat créé."))
        return redirect("tenants:cabinet_detail", pk=cabinet.pk)


class CabinetUpdateView(PlatformAdminRequiredMixin, BreadcrumbMixin, UpdateView):
    """Édition d'un cabinet avocat (supervision)."""

    template_name = "tenants/cabinet_form.html"
    form_class = CabinetForm
    context_object_name = "cabinet"

    def get_queryset(self) -> QuerySet[Cabinet]:
        return Cabinet.objects.all()

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Cabinets avocats"), "url": reverse("tenants:cabinet_list")},
            {
                "label": str(self.object),
                "url": reverse("tenants:cabinet_detail", args=[self.object.pk]),
            },
            {"label": _g("Modifier")},
        ]

    def form_valid(self, form: CabinetForm) -> HttpResponse:
        cleaned = form.cleaned_data.copy()
        contract_upload = cleaned.pop("contract_file", None)
        try:
            update_cabinet_as_platform_admin(
                actor=self.request.user,  # type: ignore[arg-type]
                cabinet=self.object,
                **cleaned,
            )
            attach_cabinet_contract(cabinet=self.object, uploaded=contract_upload)
        except (ValidationError, PermissionDenied) as exc:
            if isinstance(exc, ValidationError):
                _apply_form_errors(form, exc)
                return self.form_invalid(form)
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _g("Cabinet avocat mis à jour."))
        return redirect("tenants:cabinet_detail", pk=self.object.pk)


class CabinetDeleteView(PlatformAdminRequiredMixin, View):
    """Suppression logique d'un cabinet (supervision)."""

    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        cabinet = get_object_or_404(Cabinet, pk=pk)
        try:
            delete_cabinet_as_platform_admin(
                actor=request.user,  # type: ignore[arg-type]
                cabinet=cabinet,
            )
        except PermissionDenied as exc:
            messages.error(request, str(exc))
            return redirect("tenants:cabinet_detail", pk=pk)
        messages.success(request, _g("Cabinet avocat supprimé."))
        return redirect("tenants:cabinet_list")


class CabinetContractDownloadView(PlatformAdminRequiredMixin, View):
    """Téléchargement du contrat joint au cabinet."""

    http_method_names = ("get",)

    def get(self, request: HttpRequest, pk: str) -> HttpResponse:
        cabinet = get_object_or_404(Cabinet, pk=pk)
        return _serve_cabinet_contract(cabinet, as_attachment=True)


class CabinetContractPreviewView(PlatformAdminRequiredMixin, View):
    """Aperçu inline du contrat (PDF ou image)."""

    http_method_names = ("get",)

    def get(self, request: HttpRequest, pk: str) -> HttpResponse:
        cabinet = get_object_or_404(Cabinet, pk=pk)
        if not cabinet.contract_file:
            raise Http404(_g("Aucun contrat n'est joint à ce cabinet."))
        if not cabinet.contract_can_preview:
            return redirect("tenants:cabinet_contract_download", pk=pk)
        return _serve_cabinet_contract(cabinet, as_attachment=False)


def _serve_cabinet_contract(cabinet: Cabinet, *, as_attachment: bool) -> FileResponse:
    """Sert le contrat en téléchargement ou en aperçu."""
    if not cabinet.contract_file:
        raise Http404(_g("Aucun contrat n'est joint à ce cabinet."))
    filename = cabinet.contract_file_name or "contrat-cabinet.pdf"
    response = FileResponse(
        cabinet.contract_file.open("rb"),
        as_attachment=as_attachment,
        filename=filename,
        content_type=cabinet.contract_file_mime_type,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    if not as_attachment:
        response["Content-Security-Policy"] = (
            "default-src 'none'; img-src 'self' data:; style-src 'none'; sandbox"
        )
    return response


__all__ = [
    "CabinetContractDownloadView",
    "CabinetContractPreviewView",
    "CabinetCreateView",
    "CabinetDeleteView",
    "CabinetDetailView",
    "CabinetListView",
    "CabinetUpdateView",
    "InvitationListView",
    "InviteMemberView",
    "SwitchCabinetView",
]
