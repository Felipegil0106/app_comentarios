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


def red_de_url(url: str) -> str:
    """A que red pertenece una URL, o cadena vacia si no se reconoce."""
    u = (url or "").lower()
    for clase in _CLASES:
        if any(d in u for d in getattr(clase, "dominios", ())):
            return clase.nombre
    return ""


def comprobar_url(red: str, url: str) -> str:
    """Avisa si la URL no es de la red elegida.

    Devuelve el mensaje de error, o cadena vacia si todo encaja. Existe
    porque pegar una URL de TikTok teniendo Facebook seleccionado hacia que
    la aplicacion buscara en el sitio equivocado y devolviera cero sin
    explicar nada.
    """
    if not url or not url.strip():
        return ""
    detectada = red_de_url(url)
    if not detectada or detectada == red:
        return ""
    return (
        f"La direccion que pegaste es de {obtener(detectada).etiqueta}, pero "
        f"tienes seleccionado {obtener(red).etiqueta} en el Paso 1.\n"
        f"Cambia la red a {obtener(detectada).etiqueta} y vuelve a intentarlo."
    )
