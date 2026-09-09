"""Tests profil du compte connecté."""

from __future__ import annotations

import pytest
from django.urls import reverse

from tests.factories import MembershipFactory, UserFactory


@pytest.mark.django_db
def test_profile_requires_login(client) -> None:  # type: ignore[no-untyped-def]
    assert client.get(reverse("accounts:profile")).status_code == 302
    assert client.get(reverse("accounts:profile_update")).status_code == 302


@pytest.mark.django_db
def test_cabinet_user_can_view_and_update_profile(client) -> None:  # type: ignore[no-untyped-def]
    user = UserFactory(
        email="avocat@example.com",
        password="Str0ng-Passw0rd!",
        first_name="Jean",
        last_name="Kabila",
        phone="+243800000010",
    )
    MembershipFactory(user=user)
    assert client.login(username="avocat@example.com", password="Str0ng-Passw0rd!")

    detail = client.get(reverse("accounts:profile"))
    assert detail.status_code == 200
    content = detail.content.decode()
    assert "Mon profil" in content
    assert "Jean" in content
    assert "avocat@example.com" in content
    assert reverse("accounts:profile_update") in content

    form = client.get(reverse("accounts:profile_update"))
    assert form.status_code == 200

    updated = client.post(
        reverse("accounts:profile_update"),
        {
            "first_name": "Jeanne",
            "last_name": "Kabila",
            "phone": "+243800000099",
            "current_password": "",
            "password": "",
            "password_confirm": "",
        },
    )
    assert updated.status_code == 302
    assert updated["Location"] == reverse("accounts:profile")
    user.refresh_from_db()
    assert user.first_name == "Jeanne"
    assert user.phone == "+243800000099"


@pytest.mark.django_db
def test_profile_password_change_requires_current(client) -> None:  # type: ignore[no-untyped-def]
    user = UserFactory(email="pwd@example.com", password="Str0ng-Passw0rd!")
    MembershipFactory(user=user)
    assert client.login(username="pwd@example.com", password="Str0ng-Passw0rd!")

    bad = client.post(
        reverse("accounts:profile_update"),
        {
            "first_name": "A",
            "last_name": "B",
            "phone": "",
            "current_password": "wrong",
            "password": "New-Str0ng-Pass!",
            "password_confirm": "New-Str0ng-Pass!",
        },
    )
    assert bad.status_code == 200
    assert b"Mot de passe actuel incorrect" in bad.content
    user.refresh_from_db()
    assert user.check_password("Str0ng-Passw0rd!")

    ok = client.post(
        reverse("accounts:profile_update"),
        {
            "first_name": "A",
            "last_name": "B",
            "phone": "",
            "current_password": "Str0ng-Passw0rd!",
            "password": "New-Str0ng-Pass!",
            "password_confirm": "New-Str0ng-Pass!",
        },
    )
    assert ok.status_code == 302
    user.refresh_from_db()
    assert user.check_password("New-Str0ng-Pass!")


@pytest.mark.django_db
def test_platform_admin_can_view_profile(client) -> None:  # type: ignore[no-untyped-def]
    admin = UserFactory(
        is_platform_admin=True,
        is_super_admin=False,
        first_name="Synthia",
        last_name="K",
    )
    client.force_login(admin)
    response = client.get(reverse("accounts:profile"))
    assert response.status_code == 200
    assert b"Mon profil" in response.content
    assert b"Compte minist" in response.content
