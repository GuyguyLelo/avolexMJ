"""URLs tenants."""

from __future__ import annotations

from django.urls import path

from apps.tenants import jurisdiction_views, member_views, practice_views, state_entity_views, views

app_name = "tenants"

urlpatterns = [
    path("switch/", views.SwitchCabinetView.as_view(), name="switch"),
    path("equipe/", member_views.MemberListView.as_view(), name="member_list"),
    path("equipe/nouveau/", member_views.MemberCreateView.as_view(), name="member_create"),
    path(
        "equipe/<uuid:pk>/modifier/",
        member_views.MemberUpdateView.as_view(),
        name="member_update",
    ),
    path(
        "equipe/<uuid:pk>/retirer/",
        member_views.MemberDeleteView.as_view(),
        name="member_delete",
    ),
    path(
        "specialites/",
        practice_views.CabinetSpecialtyListView.as_view(),
        name="specialty_list",
    ),
    path(
        "specialites/ajouter/",
        practice_views.CabinetSpecialtyAddView.as_view(),
        name="specialty_add",
    ),
    path(
        "specialites/<uuid:pk>/retirer/",
        practice_views.CabinetSpecialtyRemoveView.as_view(),
        name="specialty_remove",
    ),
    path(
        "matieres/",
        practice_views.PracticeAreaListView.as_view(),
        name="practice_area_list",
    ),
    path(
        "matieres/nouveau/",
        practice_views.PracticeAreaCreateView.as_view(),
        name="practice_area_create",
    ),
    path(
        "matieres/<uuid:pk>/modifier/",
        practice_views.PracticeAreaUpdateView.as_view(),
        name="practice_area_update",
    ),
    path(
        "matieres/<uuid:pk>/supprimer/",
        practice_views.PracticeAreaDeleteView.as_view(),
        name="practice_area_delete",
    ),
    path(
        "juridictions/",
        jurisdiction_views.JurisdictionListView.as_view(),
        name="jurisdiction_list",
    ),
    path(
        "juridictions/nouveau/",
        jurisdiction_views.JurisdictionCreateView.as_view(),
        name="jurisdiction_create",
    ),
    path(
        "juridictions/<uuid:pk>/modifier/",
        jurisdiction_views.JurisdictionUpdateView.as_view(),
        name="jurisdiction_update",
    ),
    path(
        "juridictions/<uuid:pk>/supprimer/",
        jurisdiction_views.JurisdictionDeleteView.as_view(),
        name="jurisdiction_delete",
    ),
    path(
        "entites-etatiques/",
        state_entity_views.StateEntityListView.as_view(),
        name="state_entity_list",
    ),
    path(
        "entites-etatiques/nouveau/",
        state_entity_views.StateEntityCreateView.as_view(),
        name="state_entity_create",
    ),
    path(
        "entites-etatiques/<uuid:pk>/modifier/",
        state_entity_views.StateEntityUpdateView.as_view(),
        name="state_entity_update",
    ),
    path(
        "entites-etatiques/<uuid:pk>/supprimer/",
        state_entity_views.StateEntityDeleteView.as_view(),
        name="state_entity_delete",
    ),
    path("invitations/", views.InvitationListView.as_view(), name="invitation_list"),
    path("invitations/new/", views.InviteMemberView.as_view(), name="invite"),
    path("", views.CabinetListView.as_view(), name="cabinet_list"),
    path("nouveau/", views.CabinetCreateView.as_view(), name="cabinet_create"),
    path("<uuid:pk>/contrat/", views.CabinetContractDownloadView.as_view(), name="cabinet_contract_download"),
    path(
        "<uuid:pk>/contrat/apercu/",
        views.CabinetContractPreviewView.as_view(),
        name="cabinet_contract_preview",
    ),
    path("<uuid:pk>/", views.CabinetDetailView.as_view(), name="cabinet_detail"),
    path("<uuid:pk>/modifier/", views.CabinetUpdateView.as_view(), name="cabinet_update"),
    path("<uuid:pk>/supprimer/", views.CabinetDeleteView.as_view(), name="cabinet_delete"),
    path(
        "<uuid:cabinet_pk>/membres/nouveau/",
        member_views.MemberCreateView.as_view(),
        name="cabinet_member_create",
    ),
    path(
        "<uuid:cabinet_pk>/membres/<uuid:pk>/modifier/",
        member_views.MemberUpdateView.as_view(),
        name="cabinet_member_update",
    ),
    path(
        "<uuid:cabinet_pk>/membres/<uuid:pk>/retirer/",
        member_views.MemberDeleteView.as_view(),
        name="cabinet_member_delete",
    ),
    path(
        "<uuid:cabinet_pk>/specialites/ajouter/",
        practice_views.CabinetSpecialtyAddView.as_view(),
        name="cabinet_specialty_add",
    ),
    path(
        "<uuid:cabinet_pk>/specialites/<uuid:pk>/retirer/",
        practice_views.CabinetSpecialtyRemoveView.as_view(),
        name="cabinet_specialty_remove",
    ),
]
