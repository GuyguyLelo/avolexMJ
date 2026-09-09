"""Tests smoke : healthcheck et pages publiques."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse


@pytest.mark.django_db
def test_health_ok(client: Client) -> None:
    """Le healthcheck répond 200 lorsque la base est joignable."""
    response = client.get(reverse("core:health"))
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "up"
    assert data["service"] == "avolex"


@pytest.mark.django_db
def test_root_shows_login(client: Client) -> None:
    """La racine affiche directement la page de connexion."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"Login" in response.content or b"Connexion" in response.content or b"login" in response.content.lower()


@pytest.mark.django_db
def test_landing_ok(client: Client) -> None:
    """La landing page publique répond 200."""
    response = client.get(reverse("core:landing"))
    assert response.status_code == 200
    assert b"Avo" in response.content


@pytest.mark.django_db
def test_home_redirects_anonymous(client: Client) -> None:
    """La page app/ exige une authentification."""
    response = client.get(reverse("core:home"))
    assert response.status_code == 302
