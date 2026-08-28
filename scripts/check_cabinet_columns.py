import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from django.db import connection

with connection.cursor() as cursor:
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'tenants_cabinet'
          AND column_name IN ('contract_file', 'contract_file_name', 'contract_number')
        ORDER BY column_name
        """
    )
    print("columns:", cursor.fetchall())
    cursor.execute(
        "SELECT name FROM django_migrations WHERE app = 'tenants' ORDER BY id"
    )
    print("migrations:", [r[0] for r in cursor.fetchall()])
