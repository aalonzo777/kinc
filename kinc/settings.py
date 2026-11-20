"""Configuración de KINC.

Por defecto corre en modo DESARROLLO (cómodo para clases/demos).
Para producción define estas variables de entorno:
    KINC_DEBUG=False
    KINC_SECRET_KEY=<clave larga y aleatoria>
    KINC_ALLOWED_HOSTS=midominio.cl,www.midominio.cl
"""
import os
from pathlib import Path

from django.contrib.messages import constants as message_constants
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Modo y claves ──────────────────────────────────────────────────────────
ON_VERCEL = bool(os.environ.get('VERCEL'))   # Vercel define esta variable automáticamente
# En Vercel el modo es PRODUCCIÓN por defecto; en tu PC es desarrollo
DEBUG = os.environ.get('KINC_DEBUG', 'False' if ON_VERCEL else 'True').strip().lower() == 'true'

SECRET_KEY = os.environ.get('KINC_SECRET_KEY', '')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-solo-para-desarrollo-local-no-usar-en-produccion'
    else:
        raise ImproperlyConfigured('Falta la variable de entorno KINC_SECRET_KEY (obligatoria con KINC_DEBUG=False).')

_default_hosts = 'localhost,127.0.0.1,[::1]' if DEBUG else ''
ALLOWED_HOSTS = [h.strip() for h in os.environ.get('KINC_ALLOWED_HOSTS', _default_hosts).split(',') if h.strip()]
if ON_VERCEL:
    ALLOWED_HOSTS.append('.vercel.app')
if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured('Define KINC_ALLOWED_HOSTS cuando KINC_DEBUG=False.')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'core.middleware.ForcePasswordChangeMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'kinc.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'core' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.nav_badges',
            ],
        },
    },
]

WSGI_APPLICATION = 'kinc.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
# Producción (Vercel): PostgreSQL mediante la variable DATABASE_URL (por ejemplo, Neon).
# SQLite no sirve en Vercel porque no hay disco persistente.
if os.environ.get('DATABASE_URL'):
    import dj_database_url
    DATABASES = {'default': dj_database_url.config(conn_max_age=0, ssl_require=True)}
    DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True   # compatible con conexiones "pooler"

# Caché: el bloqueo de intentos de login necesita una caché COMPARTIDA entre instancias.
# En producción se guarda en la base de datos (ejecutar una vez: python manage.py createcachetable).
if os.environ.get('DATABASE_URL'):
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.db.DatabaseCache', 'LOCATION': 'kinc_cache'}}
else:
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}

# ── Contraseñas ────────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'es-cl'
TIME_ZONE = 'America/Santiago'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'core' / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Las fotos de los pacientes NO se sirven públicamente: se entregan solo a través
# de la vista protegida 'proof_image' (ver core/views.py). No mapear /media/ en el servidor web.
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ── Límites de subida y de datos ───────────────────────────────────────────
# Vercel rechaza peticiones de más de 4,5 MB (error 413), por eso el límite es 4 MB
MAX_UPLOAD_SIZE = 4 * 1024 * 1024            # 4 MB por foto
FILE_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_SIZE
DATA_UPLOAD_MAX_MEMORY_SIZE = 1 * 1024 * 1024  # 1 MB de texto por petición
DATA_UPLOAD_MAX_NUMBER_FIELDS = 200

# Fotos en producción: almacenamiento de objetos compatible con S3 (Cloudflare R2, Supabase Storage, AWS S3).
# El bucket debe ser PRIVADO: las fotos solo se entregan por la vista protegida 'proof_image'.
if os.environ.get('AWS_STORAGE_BUCKET_NAME'):
    STORAGES = {
        'default': {'BACKEND': 'storages.backends.s3.S3Storage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
    AWS_S3_ENDPOINT_URL = os.environ.get('AWS_S3_ENDPOINT_URL') or None
    AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', 'auto')
    AWS_S3_SIGNATURE_VERSION = 's3v4'
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = True
    AWS_S3_FILE_OVERWRITE = False

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = 'core.User'

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/login/'

MESSAGE_STORAGE = 'django.contrib.messages.storage.session.SessionStorage'
MESSAGE_TAGS = {message_constants.ERROR: 'danger'}  # Bootstrap usa "alert-danger"

# ── Sesión y cookies ───────────────────────────────────────────────────────
SESSION_COOKIE_AGE = 60 * 60 * 8       # la sesión caduca a las 8 horas
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'

# ── Cabeceras de seguridad ─────────────────────────────────────────────────
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'

if not DEBUG:
    # Vercel termina el HTTPS en su proxy: sin esta línea, SECURE_SSL_REDIRECT causaría un bucle infinito
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get(
        'KINC_CSRF_TRUSTED_ORIGINS', 'https://*.vercel.app' if ON_VERCEL else '').split(',') if o.strip()]
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
