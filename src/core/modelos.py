"""Modelos de datos: las "fichas" que la app mueve de un lado a otro.

Un `Publicacion` es un post/foto/reel/video de una red social.
Un `Comentario` es un comentario (o respuesta) que cuelga de una publicacion.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime


def _hash(*partes: str) -> str:
    """Genera un identificador unico y estable a partir de varios textos.

    Sirve para no guardar dos veces el mismo comentario si repites la
    extraccion: el mismo texto del mismo autor en la misma publicacion
    siempre produce el mismo id.
    """
    crudo = "||".join(p.strip() for p in partes if p)
    return hashlib.sha1(crudo.encode("utf-8", errors="ignore")).hexdigest()[:20]


@dataclass
class Publicacion:
    """Una publicacion encontrada en el perfil."""

    url: str
    red: str                       # facebook, instagram, tiktok, x
    perfil: str = ""               # url o nombre del perfil de origen
    fecha: datetime | None = None  # fecha de publicacion
    tipo: str = "publicacion"      # publicacion, foto, video, reel, historia...
    texto: str = ""                # primeras palabras del post (para reconocerlo)
    n_comentarios: int = 0         # comentarios extraidos de esta publicacion
    seleccionada: bool = True      # marcada para extraer (modo manual)
    estado: str = "pendiente"      # pendiente | extraida | error | omitida
    nota: str = ""                 # mensaje de error o aclaracion
    # True cuando la fecha se dedujo del muro y NO es de fiar (por ejemplo,
    # se leyo de la hora de un comentario). Se corrige al abrir la publicacion.
    fecha_aproximada: bool = False
    # De que seccion del perfil salio (Linea de tiempo, Reels, Videos, Fotos).
    # Importa porque cada seccion va ordenada por su cuenta.
    seccion: str = ""

    @property
    def fecha_texto(self) -> str:
        if not self.fecha:
            return "sin fecha"
        texto = self.fecha.strftime("%Y-%m-%d %H:%M")
        return texto + " (aprox.)" if self.fecha_aproximada else texto

    @property
    def resumen(self) -> str:
        limpio = " ".join(self.texto.split())
        return (limpio[:90] + "…") if len(limpio) > 90 else limpio


@dataclass
class Comentario:
    """Un comentario de texto. Solo guardamos texto + emojis."""

    publicacion_url: str
    autor: str
    texto: str
    red: str = ""
    fecha: datetime | None = None
    es_respuesta: bool = False     # True si es respuesta a otro comentario
    reacciones: int = 0
    extraido_en: datetime = field(default_factory=datetime.now)

    @property
    def id(self) -> str:
        return _hash(self.publicacion_url, self.autor, self.texto)

    @property
    def fecha_texto(self) -> str:
        return self.fecha.strftime("%Y-%m-%d %H:%M") if self.fecha else ""
