"""
WSGI config for sowafinance project.
"""

import os
from django.core.wsgi import get_wsgi_application

# ✅ Use the inner package ONLY (no double prefix)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sowafinance.settings")

application = get_wsgi_application()
