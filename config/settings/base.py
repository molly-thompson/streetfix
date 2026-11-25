"""Shared configuration elements and global project settings."""

import os
from pathlib import Path

from django.contrib.messages import constants as messages

BASE_DIR = Path(__file__).resolve().parent.parent.parent


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "allauth",
    "allauth.account",
    "cloudinary",
    "colorfield",
    # Local
    "intake",
    "employees",
    "analytics",
    "site_settings",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "global_login_required.GlobalLoginRequiredMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"


# Authentication

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

LOGIN_URL = "/auth/login/"
LOGIN_REDIRECT_URL = "/employees/"
ACCOUNT_LOGOUT_REDIRECT_URL = "/"

ACCOUNT_LOGIN_METHODS = ["email"]
ACCOUNT_SIGNUP_FIELDS = [
    "first_name",
    "last_name",
    "email*",
    "username*",
    "password1*",
    "password2*",
]
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_ADAPTER = "config.adapters.NoSignupAccountAdapter"

# Let Allauth and Django admin handle their own authentication,
# rather than applying the project's global login requirement.
PUBLIC_PATHS = [
    r"^/auth/.*",
    r"^/site-admin/.*",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "site_settings.context_processors.theme_settings",
            ],
        },
    },
]


# Field work
# Where officers start and end their day, used to estimate travel times.
FIELD_DEPOT = {
    "name": "Council House, Victoria Square",
    "lat": 52.4797,
    "lng": -1.9026,
}
# Look up street addresses for job locations with OpenStreetMap's Nominatim.
REVERSE_GEOCODING = True
GEOCODER_USER_AGENT = os.environ.get("GEOCODER_USER_AGENT", "reporting field app")
# Store officers' site photos on Cloudinary when it is configured.
OFFICER_PHOTOS_ON_CLOUDINARY = bool(os.environ.get("CLOUDINARY_URL"))
OFFICER_PHOTO_FOLDER = os.environ.get("OFFICER_PHOTO_FOLDER", "work-photos")

# Public report submission stays disabled until deployment safeguards are ready.
INTAKE_PUBLIC_REPORTING_ENABLED = os.environ.get(
    "INTAKE_PUBLIC_REPORTING_ENABLED", ""
).lower() in ("1", "true", "yes")

# WSGI META key of a client-address header that the hosting edge sets and
# clients cannot forge. Used to rate limit public actions per address.
INTAKE_CLIENT_IP_HEADER = os.environ.get("INTAKE_CLIENT_IP_HEADER", "REMOTE_ADDR")

# Text shown before a reporter's random reference code. Empty by default.
INTAKE_REFERENCE_PREFIX = os.environ.get("INTAKE_REFERENCE_PREFIX", "")

# Engine assessments are opt-in. The service must listen on loopback only.
TRIAGE_ENGINE_URL = os.environ.get("TRIAGE_ENGINE_URL", "http://127.0.0.1:8001")
TRIAGE_ENGINE_SERVICE_TOKEN = os.environ.get("TRIAGE_ENGINE_SERVICE_TOKEN", "")

# Name of a signed Cloudinary upload preset that uses authenticated delivery.
# Report photos are disabled until it is configured.
INTAKE_PHOTO_UPLOAD_PRESET = os.environ.get("INTAKE_PHOTO_UPLOAD_PRESET", "")

# Public intake maps remain disabled until a deployment supplies a tile
# provider, attribution, and initial map centre.
INTAKE_MAP = {
    "tile_url": os.environ.get("INTAKE_MAP_TILE_URL", ""),
    "attribution": os.environ.get("INTAKE_MAP_ATTRIBUTION", ""),
    "latitude": os.environ.get("INTAKE_MAP_LATITUDE", ""),
    "longitude": os.environ.get("INTAKE_MAP_LONGITUDE", ""),
    "zoom": os.environ.get("INTAKE_MAP_ZOOM", "13"),
}

# Look up map coordinates for postcodes in public reports (postcodes.io).
POSTCODE_LOOKUP = True


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",  # noqa
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",  # noqa
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",  # noqa
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",  # noqa
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = "en-gb"

TIME_ZONE = "Europe/London"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = "static/"

STATICFILES_DIRS = [
    BASE_DIR / "static",
]

STATIC_ROOT = BASE_DIR / "staticfiles"

# Uploaded files, such as officers' site photos
MEDIA_URL = "media/"

MEDIA_ROOT = BASE_DIR / "media"


STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Security

# Explicit security defaults
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

# Extended security baseline
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"


# Messages

MESSAGE_TAGS = {
    messages.INFO: "primary",
    messages.ERROR: "danger",
}
