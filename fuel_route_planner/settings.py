"""Django settings for the fuel route planner."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "django-insecure-dev-only-change-me-in-production"
)
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "fuel_planner",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "fuel_route_planner.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "fuel_route_planner.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Route and geocoding responses are cached on disk so repeat requests (and the
# /map/ page for a route already planned) never hit the external APIs again.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": BASE_DIR / ".cache",
        "TIMEOUT": 60 * 60 * 24 * 7,
        "OPTIONS": {"MAX_ENTRIES": 5000},
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
}

# --- Data files ------------------------------------------------------------
DATA_DIR = BASE_DIR / "data"
FUEL_PRICES_CSV = DATA_DIR / "fuel-prices-for-be-assessment.csv"
PLACES_CSV = DATA_DIR / "us_places.csv"
STATIONS_CSV = DATA_DIR / "stations_geocoded.csv"

# --- External services (both free, no API key) ----------------------------
# Tried in order; the second is only used if the first fails.
OSRM_BASE_URLS = os.environ.get(
    "OSRM_BASE_URLS", "https://router.project-osrm.org,https://routing.openstreetmap.de/routed-car"
).split(",")
NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
HTTP_USER_AGENT = os.environ.get("HTTP_USER_AGENT", "fuel-route-planner/1.0 (assessment)")
HTTP_TIMEOUT_SECONDS = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "12"))

# --- Trip assumptions ------------------------------------------------------
VEHICLE_RANGE_MILES = 500
VEHICLE_MPG = 10
# How far off the route (straight-line) a station may be and still count.
DEFAULT_MAX_DETOUR_MILES = 10
# Cost attached to each fuel stop when choosing stops (driver time, pulling off
# the highway). Not included in the reported fuel cost. 0 = pure cheapest fuel.
DEFAULT_STOP_PENALTY_USD = 10
