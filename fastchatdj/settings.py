import os
from pathlib import Path
from django.conf.global_settings import CACHES

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ALLOWED_HOSTS = ["*"]

WKHTMLTOPDF_DEBUG = True
# SESSION CONFIGURATION
# SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 28800


EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
# EMAIL_USE_TLS = True
# EMAIL_HOST = 'smtp.gmail.com'

# EMAIL_PORT = 587
EMAIL_USE_SSL = True

EMAIL_USE_TLS = False
EMAIL_HOST = 'smtp.sendgrid.net'
EMAIL_PORT = 465
DEFAULT_FROM_EMAIL = 'notisimweb@gmail.com'
EMAIL_HOST_PASSWORD = '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'

# CREDENCIALES
import json

with open(os.path.join(BASE_DIR, 'credenciales.json')) as json_file:
    data = json.load(json_file)
    # POSTGRES
    POSTGRES_PASSWORD = data['POSTGRES_PASSWORD']
    POSTGRES_HOST = data['POSTGRES_HOST']
    POSTGRES_PORT = data['POSTGRES_PORT']
    POSTGRES_DBNAME = data['POSTGRES_DBNAME']

    BASE_URL_PRODUCCION = data['BASE_URL_PRODUCCION']
    # SECURITY WARNING: keep the secret key used in production secret!
    SECRET_KEY = data['SECRET_KEY']
    EMAIL_HOST_USER = data['EMAIL_HOST_USER']
    # DEFAULT_FROM_EMAIL = data['DEFAULT_FROM_EMAIL']
    # EMAIL_HOST_PASSWORD = data['EMAIL_HOST_PASSWORD']
    SENDGRID_API_KEY = data['SENDGRID_API_KEY']
    # WKHTMLTOPDF
    WKHTMLTOPDF_CMD = data['WKHTMLTOPDF_CMD']
    # SSL
    USE_SSL = data['USE_SSL']
    SECURE_SSL_REDIRECT = USE_SSL
    DEBUG = data["DEBUG"]
    DOMINIO_GENERAL = data["DOMINIO_GENERAL"]
    WINDOWS = data["WINDOWS"]
    URL_GENERAL = ("https://" if USE_SSL else "http://") + DOMINIO_GENERAL
    ADMINS = data["ADMINS"]
    CACHES_REDIS = data.get("CACHES_REDIS")
    ID_GRUPO_CLIENTE = data['ID_GRUPO_CLIENTE']
    REDIS_HOST = data['REDIS_HOST']
    REDIS_PORT = data['REDIS_PORT']
    #WHATSAPP_API_URL
    WHATSAPP_API_URL = data['WHATSAPP_API_URL']
    NODE_SECRET_KEY = data['NODE_SECRET_KEY']
    # Meta Embedded Signup (WhatsApp Cloud API) — opcional hasta que el cliente registre App en Meta.
    META_APP_ID         = data.get('META_APP_ID', '')
    META_APP_SECRET     = data.get('META_APP_SECRET', '')
    META_CONFIG_ID      = data.get('META_CONFIG_ID', '')
    META_API_VERSION    = data.get('META_API_VERSION', 'v22.0')

WKHTMLTOPDF_CMD_OPTIONS = {'encoding': 'utf8', 'quiet': True, 'enable-local-file-access': True}


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'daphne',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    # LOCAL APPS
    'autenticacion.apps.AutenticacionConfig',
    'seguridad.apps.SeguridadConfig',
    'area_geografica.apps.AreaGeograficaConfig',
    'public.apps.PublicConfig',
    'whatsapp.apps.WhatsappConfig',
    'crm.apps.CrmConfig',
    'agents_ai.apps.AgentsAiConfig',
    'voz.apps.VozConfig',
    'agenda.apps.AgendaConfig',
    # packages
    'wkhtmltopdf',
    'django_select2',
    'for_django_projects.form_utils',
    'webpush',
    'for_django_projects.pwa',
    'corsheaders',
    'channels',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # custom middlewares
    'core.custom_middleware.InitialDataApp',
    'core.custom_middleware.RequestMiddleware',
]

DATA_UPLOAD_MAX_MEMORY_SIZE = 2621440 * 10

ROOT_URLCONF = 'fastchatdj.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')]
        ,
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'fastchatdj.wsgi.application'
ASGI_APPLICATION = 'fastchatdj.asgi.application'

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer'
    }
}
if CACHES_REDIS:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                "hosts": [(REDIS_HOST, REDIS_PORT)],
            },
        },
    }

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': POSTGRES_DBNAME,
        'USER': 'postgres',
        'PASSWORD': POSTGRES_PASSWORD,
        'HOST': POSTGRES_HOST,
        'PORT': POSTGRES_PORT,
        'ATOMIC_REQUESTS': True,
    },

}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
# https://docs.djangoproject.com/en/4.1/topics/i18n/

LOGIN_URL = '/autenticacion/login/'

LANGUAGE_CODE = 'es-ec'

TIME_ZONE = 'America/Guayaquil'

USE_I18N = True

USE_L10N = True

# USE_TZ = True

AUTH_USER_MODEL = "autenticacion.Usuario"

STATIC_URL = '/static/'
STATIC_ROOT = ''

if DEBUG:
    STATICFILES_DIRS = [
        os.path.join(BASE_DIR, 'static'),
    ]
else:
    STATIC_ROOT = os.path.join(BASE_DIR, 'static')

MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
MEDIA_URL = '/media/'

# Default primary key field type
# https://docs.djangoproject.com/en/4.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

TEST_RUNNER = 'django.test.runner.DiscoverRunner'  # If you wish to delay updates to your test suite
SESSION_SERIALIZER = 'django.contrib.sessions.serializers.PickleSerializer'

SITE_STORAGE = Path(BASE_DIR) / 'media'

# SITE_STORAGE = os.path.dirname(os.path.realpath("manage.py"))
LOGIN_URL = '/login/'

FILE_CHARSET = 'utf-8'
DEFAULT_CHARSET = 'utf-8'


CORS_ORIGIN_ALLOW_ALL = True
CORS_ALLOW_ALL_ORIGINS = False

CORS_ALLOWED_ORIGINS = [
    # url produccion
    'http://127.0.0.1:8080',
    'http://127.0.0.1:8001',
    'http://127.0.0.1',
    'http://localhost:8000',
    'http://localhost:8001',
    'http://localhost:8080',
    'http://localhost:3000',
    'http://localhost',
]

CORS_ALLOWED_ORIGIN_REGEXES = [
    # url produccion
]

CORS_ORIGIN_WHITELIST = [
    # url produccion
    'http://localhost:3000'
]

CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]

CSRF_TRUSTED_ORIGINS = [
    # url produccion
    'http://localhost:3000'
]

CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
]

CORS_ALLOW_CREDENTIALS = True


X_FRAME_OPTIONS = 'SAMEORIGIN'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'whatsapp': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'agents_ai': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'crm': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}