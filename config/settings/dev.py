"""Settings développement local (sans Docker)."""

from __future__ import annotations

from .base import *  # noqa: F403
from .base import INSTALLED_APPS, MIDDLEWARE, STORAGES

DEBUG = True

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Static files simples en local (pas de manifest)
STORAGES = {
    **STORAGES,
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}
WHITENOISE_MAX_AGE = 0
WHITENOISE_AUTOREFRESH = True

# Cache Redis optionnel : fallback mémoire si Redis indisponible au boot des tests CLI
# En dev on garde Redis ; si absent, lancer `make redis` ou adapter REDIS_URL.
# Pour un boot sans Redis, décommenter le fallback ci-dessous.
# CACHES = {
#     "default": {
#         "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
#     },
# }

CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)  # noqa: F405
CELERY_TASK_EAGER_PROPAGATES = True

# Sous Windows sans GTK/Pango, WeasyPrint tombe en stub (voir apps.billing.pdf).
BILLING_PDF_BACKEND = env("BILLING_PDF_BACKEND", default="auto")  # noqa: F405

if DEBUG and env.bool("ENABLE_DEBUG_TOOLBAR", default=False):  # noqa: F405
    INSTALLED_APPS = [*INSTALLED_APPS, "debug_toolbar"]
    MIDDLEWARE = [
        "debug_toolbar.middleware.DebugToolbarMiddleware",
        *MIDDLEWARE,
    ]
    INTERNAL_IPS = ["127.0.0.1", "localhost"]

# CSP un peu plus souple pour le debug
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ("'self'",),
        "script-src": ("'self'", "'unsafe-inline'"),
        "style-src": ("'self'", "'unsafe-inline'", "https://fonts.googleapis.com"),
        "img-src": ("'self'", "data:"),
        "font-src": ("'self'", "https://fonts.gstatic.com", "data:"),
        "connect-src": ("'self'",),
        "frame-ancestors": ("'none'",),
        "base-uri": ("'self'",),
        "form-action": ("'self'",),
    },
}
