import os
import socket
from pathlib import Path

from django.core.mail import utils as mail_utils

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent.parent

if load_dotenv:
    load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-1+-8%0v0b$k1x3*si=k_+9=op-95$f&wiadk3s!mt)zvy!dn$*',
)

DEBUG = os.environ.get('DJANGO_DEBUG', 'True') == 'True'

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'allauth.socialaccount.providers.yandex',
    'accounts',
    'tasks',
    'assignments',
    'sandbox',
    'stats',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'assignments.context_processors.now',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'ru-ru'

TIME_ZONE = 'Europe/Moscow'

USE_I18N = True

USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'accounts.User'

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

SITE_ID = 1

EMAIL_BACKEND = os.environ.get('DJANGO_EMAIL_BACKEND', '')
if not EMAIL_BACKEND:
    EMAIL_BACKEND = (
        'django.core.mail.backends.smtp.EmailBackend'
        if os.environ.get('DJANGO_EMAIL_HOST')
        else 'django.core.mail.backends.console.EmailBackend'
    )
EMAIL_HOST = os.environ.get('DJANGO_EMAIL_HOST', '')
EMAIL_PORT = int(os.environ.get('DJANGO_EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.environ.get('DJANGO_EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('DJANGO_EMAIL_HOST_PASSWORD', '')
EMAIL_USE_SSL = os.environ.get('DJANGO_EMAIL_USE_SSL', 'False') == 'True'
EMAIL_USE_TLS = os.environ.get('DJANGO_EMAIL_USE_TLS', 'True') == 'True' and not EMAIL_USE_SSL
DEFAULT_FROM_EMAIL = os.environ.get(
    'DJANGO_DEFAULT_FROM_EMAIL', EMAIL_HOST_USER or 'noreply@example.com'
)

_raw_fqdn = socket.getfqdn()
_mail_fqdn = _raw_fqdn.strip('.')
if not _mail_fqdn or '..' in _mail_fqdn:
    _mail_fqdn = 'localhost'
if _mail_fqdn != _raw_fqdn:
    mail_utils.DNS_NAME._fqdn = _mail_fqdn

LOGIN_REDIRECT_URL = 'home'
LOGIN_URL = 'account_login'
LOGOUT_REDIRECT_URL = 'home'

ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'first_name*', 'last_name*', 'password1*', 'password2*']
ACCOUNT_EMAIL_VERIFICATION = 'mandatory'
ACCOUNT_EMAIL_CONFIRMATION_EXPIRE_DAYS = 3
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_LOGOUT_ON_GET = True
ACCOUNT_SIGNUP_REDIRECT_URL = 'home'

ACCOUNT_FORMS = {
    'signup': 'accounts.forms.CustomSignupForm',
}

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': ['email', 'profile'],
        'AUTH_PARAMS': {'access_type': 'online'},
    },
    'yandex': {
        'SCOPE': ['login:email', 'login:info'],
    },
}
