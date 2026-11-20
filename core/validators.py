"""Validadores de formato reutilizables para KINC.

Todo dato que entra por un formulario pasa por estas reglas en el SERVIDOR
(los atributos HTML como maxlength/min/max son solo una ayuda visual).
"""
import re
from urllib.parse import urlparse, parse_qs

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

# ── Nombres de personas ────────────────────────────────────────────────────
_LETTERS = "A-Za-zÁÉÍÓÚÜÑáéíóúüñ"
validate_person_name = RegexValidator(
    regex=rf"^[{_LETTERS}]+(?:[ '\-][{_LETTERS}]+)*$",
    message="Solo se permiten letras, espacios, guiones y apóstrofes (sin números ni símbolos).",
)

# ── Teléfono ───────────────────────────────────────────────────────────────
validate_phone = RegexValidator(
    regex=r"^\+?[0-9]{8,15}$",
    message="Teléfono inválido. Usa solo números (8 a 15 dígitos), con + opcional al inicio. Ej: +56912345678",
)


def normalize_phone(value):
    """Quita espacios, guiones, puntos y paréntesis: '+56 9 1234-5678' -> '+56912345678'."""
    return re.sub(r"[\s\-().]", "", value or "")


# ── Link de YouTube ────────────────────────────────────────────────────────
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}
_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_youtube_id(url):
    """Devuelve el ID de 11 caracteres de un link de YouTube, o None si no es válido."""
    raw = (url or "").strip()
    if raw and "://" not in raw:
        raw = "https://" + raw   # acepta links pegados sin https://
    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or host not in _YOUTUBE_HOSTS:
        return None

    video_id = None
    if host.endswith("youtu.be"):
        video_id = parsed.path.lstrip("/").split("/")[0]
    elif parsed.path == "/watch":
        video_id = (parse_qs(parsed.query).get("v") or [None])[0]
    else:
        match = re.match(r"^/(?:embed|shorts|v|live)/([^/?#]+)", parsed.path)
        if match:
            video_id = match.group(1)
    return video_id if video_id and _YOUTUBE_ID.match(video_id) else None


def validate_youtube_url(value):
    if not extract_youtube_id(value):
        raise ValidationError(
            "Ingresa un link válido de YouTube (youtube.com/watch?v=... o youtu.be/...)."
        )


def canonical_youtube_url(video_id):
    return f"https://www.youtube.com/watch?v={video_id}"


# ── Utilidades ─────────────────────────────────────────────────────────────
def safe_int(value, minimum=1, maximum=999_999_999):
    """Convierte a int sin lanzar error. Devuelve None si no es un entero dentro del rango."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if minimum <= number <= maximum else None
