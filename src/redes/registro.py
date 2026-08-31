"""Catalogo de redes sociales disponibles en la aplicacion."""

from __future__ import annotations

from .base import ExtractorRed
from .facebook import ExtractorFacebook
from .instagram import ExtractorInstagram
from .otras_redes import ExtractorX
from .tiktok import ExtractorTikTok

# Orden en que apareceran en el desplegable de la interfaz
_CLASES = [ExtractorFacebook, ExtractorInstagram, ExtractorTikTok, ExtractorX]

_INSTANCIAS: dict[str, ExtractorRed] = {}


def obtener(nombre: str) -> ExtractorRed:
    """Devuelve el extractor de una red (lo crea la primera vez)."""
    nombre = (nombre or "").lower()
    if nombre not in _INSTANCIAS:
        for clase in _CLASES:
            if clase.nombre == nombre:
                _INSTANCIAS[nombre] = clase()
                break
        else:
            raise KeyError(f"Red social desconocida: {nombre}")
    return _INSTANCIAS[nombre]


def listar() -> list[ExtractorRed]:
    """Todas las redes, listas para mostrarlas en la interfaz."""
    return [obtener(c.nombre) for c in _CLASES]
