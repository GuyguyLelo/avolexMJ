"""Tests smoke UI / landing / assets."""

from __future__ import annotations

import pytest
from django.urls import reverse

from tests.factories import MembershipFactory, UserFactory


@pytest.mark.django_db
def test_landing_contains_brand_and_sections(client) -> None:
    """La landing expose la marque et les modules."""
    response = client.get(reverse("core:landing"))
    assert response.status_code == 200
    content = response.content.decode()
    assert "AvoLex" in content
    assert "Ministère de la Justice" in content
    assert "République Démocratique du Congo" in content
    assert 'id="fonctionnalites"' in content
    assert reverse("accounts:register") in content


@pytest.mark.django_db
def test_landing_loads_design_css(client) -> None:
    """Les feuilles de style du design system sont référencées."""
    response = client.get(reverse("core:landing"))
    content = response.content.decode()
    assert "css/app.css" in content
    assert "css/base.css" not in content
    assert "css/landing.css" not in content


@pytest.mark.django_db
def test_app_shell_has_sidebar_and_topbar(client) -> None:
    """Le shell applicatif contient sidebar et topbar."""
    user = UserFactory(email="ui@example.com", password="Str0ng-Passw0rd!")
    MembershipFactory(user=user)
    assert client.login(username="ui@example.com", password="Str0ng-Passw0rd!")

    response = client.get(reverse("core:home"))
    assert response.status_code == 200
    content = response.content.decode()
    assert "app-sidebar" in content
    assert "app-topbar" in content
    assert "app-cabinet-banner" in content
    assert "app-cabinet-banner-marquee" in content
    assert "app-user-chip" in content
    assert reverse("accounts:profile") in content
    assert "Mon profil" in content
    assert "data-sidebar-toggle" in content
    assert "js/main.js" in content
    assert "page-header-dash--cabinet" in content
    assert "cabinet-charts-data" in content
    assert "Mandats valides" in content


@pytest.mark.django_db
def test_login_page_has_institutional_shell(client) -> None:
    """La connexion utilise le panneau institutionnel, sans fond drapeau."""
    response = client.get(reverse("accounts:login"))
    assert response.status_code == 200
    content = response.content.decode()
    assert "auth-aside" in content
    assert "auth-panel" in content
    assert "Plateforme nationale des cabinets d'avocats" in content
    assert "css/app.css" in content
