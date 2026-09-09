# AvoLex

SaaS B2B de gestion de cabinet d'avocats (multi-tenant).

Stack : **Python 3.12 · Django 5 · PostgreSQL 16 · Redis · Celery · WeasyPrint**.

> Installation locale **sans Docker** (< 5 minutes si PostgreSQL et Redis sont déjà installés).

## Prérequis

- Python **3.12+** (CI en 3.12 ; local OK en 3.13)
- PostgreSQL **16** (base + rôle locaux)
- Redis **7+** (cache + broker Celery)
- [WeasyPrint — dépendances système](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html) (Pango, GDK-PixBuf…)
- Optionnel : GNU Make

### PostgreSQL (exemple Windows)

Le service `postgresql-x64-16` doit tourner. Créer la base avec le script fourni
(mot de passe superuser `postgres` = `123456` par défaut local) :

```powershell
$env:PGPASSWORD='123456'
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -h 127.0.0.1 -f scripts\setup_db.sql
```

Cela crée la base `AvoLexMJ_db` (propriétaire `postgres`), alignée avec `.env.example`.
Adapter `DATABASE_URL` dans `.env` si besoin.

## Installation rapide

```powershell
cd D:\Developpement\python\projets\AvoLex
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements\dev.txt
copy .env.example .env
# Préparer PostgreSQL (une fois) :
# & "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -h 127.0.0.1 -f scripts\setup_db.sql
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Ouvrir http://127.0.0.1:8000/ — healthcheck : http://127.0.0.1:8000/health/

### Compte de démonstration

Après `seed_demo` :

| Champ | Valeur |
|-------|--------|
| E-mail | `ngamika@gmail.com` |
| Mot de passe | `@12345678` |
| App | http://127.0.0.1:8000/app/ |
| API | http://127.0.0.1:8000/api/v1/clients/ (session auth) |

### SuperAdmin et Administrateur

```bash
# SuperAdmin (tous les droits + gestion des comptes)
python manage.py create_platform_admin --email SuperAdmin --password "@SuperAdmin123"

# Administrateur ministère (cabinets, dossiers, procurations)
python manage.py create_platform_admin --as-administrator --email Admin --password "@Admin12345"
```

| Rôle | Droits |
|------|--------|
| **SuperAdmin** | Toutes les fonctionnalités ; crée Administrateurs et comptes cabinets |
| **Administrateur** | Cabinets avocats, dossiers, procurations, matières, supervision |
| **Compte cabinet** | Dossiers / actes couverts par une procuration valide |

| Champ | SuperAdmin | Administrateur |
|-------|------------|----------------|
| Identifiant | `SuperAdmin` | `Admin` |
| Mot de passe | `@SuperAdmin123` | `@Admin12345` (commande) ou `@12345678` (seed) |
| Accueil | `/app/supervision/` | `/app/supervision/` |

### Modules disponibles

| Module | URL |
|--------|-----|
| Cabinets avocats (superviseur) | `/cabinets/` |
| Clients | `/clients/` |
| Dossiers | `/dossiers/` |
| Agenda | `/agenda/` |
| Audiences | `/audiences/` |
| Documents | `/documents/` |
| Facturation | `/billing/` |
| API REST | `/api/v1/` |

**Rôles** (mapping cahier des charges) : Administrateur → `owner`, Avocat → `lawyer`, Assistant → `secretary` / `associate`.

### Avec Make

```bash
make install
make env
make migrate
make run
```

## Commandes utiles

| Action | Commande |
|--------|----------|
| Serveur | `python manage.py runserver` |
| Migrations | `python manage.py migrate` |
| Tests | `pytest` |
| Lint | `ruff check apps config tests` |
| Format | `ruff format apps config tests` |
| Types | `mypy apps config` |
| Celery worker | `celery -A config worker -l info` |
| Celery beat | `celery -A config beat -l info` |
| Superuser | `python manage.py createsuperuser` |
| Pre-commit | `pre-commit install` |

## Architecture

```
avolex/
├── config/           # settings (base/dev/prod/test), urls, wsgi/asgi, celery
├── apps/             # apps métier
│   ├── accounts/     # User (email) — auth complète étape 2
│   ├── tenants/      # cabinets (étape 2)
│   ├── clients/      # étape 4
│   ├── matters/      # étape 5
│   ├── calendar_app/ # étape 6
│   ├── documents/    # étape 7
│   ├── billing/      # étape 8
│   ├── subscriptions/# étape 10
│   └── core/         # pages transverses, context processors
├── templates/
├── static/
├── tests/
└── docs/
```

Settings : `DJANGO_SETTINGS_MODULE=config.settings.dev` (défaut via `manage.py`).

## Variables d'environnement

Voir [`.env.example`](.env.example). Obligatoires en local : `SECRET_KEY`, `DATABASE_URL`.

## CI

GitHub Actions (`.github/workflows/ci.yml`) : ruff, mypy, pytest contre PostgreSQL 16 (service container CI uniquement — pas de Docker Compose local).

## Auth & multi-tenant (étape 2)

| URL | Description |
|-----|-------------|
| `/accounts/register/` | Inscription + création cabinet (Owner) |
| `/accounts/login/` | Connexion e-mail |
| `/accounts/password-reset/` | Mot de passe oublié |
| `/accounts/invitations/<token>/` | Accepter une invitation |
| `/cabinets/` | CRUD cabinets avocats (superviseur) |
| `/cabinets/switch/` | Basculer de cabinet (POST) |
| `/cabinets/invitations/` | Liste / envoi d’invitations |

Isolation : middleware `CabinetMiddleware` + `TenantManager` (fail-closed sans cabinet courant).

## Notes

- **Pas de Docker Compose** dans ce dépôt (choix produit). PostgreSQL et Redis s’installent nativement.
- Les documents métier seront stockés dans `private_media/` (hors webroot).
- Couverture métier ≥ 80 % exigée à partir des apps fonctionnelles (étape 2+).
- N+1 : utiliser la fixture pytest-django `django_assert_num_queries` (pas de paquet séparé `django-assert-num-queries`).
