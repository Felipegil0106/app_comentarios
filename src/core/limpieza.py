"""Limpieza de texto: dejamos SOLO texto y emojis.

Las redes meten en los comentarios cosas que no nos interesan:
stickers, GIFs, "Fulano envio un archivo adjunto", saltos de linea raros,
caracteres invisibles, etc. Aqui los quitamos.
"""

from __future__ import annotations

import re
import unicodedata

# Caracteres invisibles que Facebook/Instagram insertan y ensucian el CSV
_INVISIBLES = re.compile(
    "["
    "​‌‍‎‏"   # espacios de ancho cero / marcas de direccion
    "⁠﻿­"               # word-joiner, BOM, guion suave
    "‪-‮"                    # marcas de bidi
    "]"
)

# Frases que Facebook pone cuando el "comentario" en realidad es una imagen,
# GIF, sticker o archivo adjunto. Si el comentario queda vacio, se descarta.
_MARCADORES_MULTIMEDIA = [
    r"envi[oó] un archivo adjunto",
    r"sent an attachment",
    r"^\s*GIF\s*$",
    r"^\s*Sticker\s*$",
    r"^\s*Adhesivo\s*$",
    r"^\s*Imagen\s*$",
    r"^\s*Foto\s*$",
    r"^\s*Photo\s*$",
    r"^\s*Video\s*$",
    r"^\s*Reproducir\s*$",
    r"^\s*Play\s*$",
    r"^\s*Ver traducci[oó]n\s*$",
    r"^\s*See translation\s*$",
]
_RE_MULTIMEDIA = re.compile("|".join(_MARCADORES_MULTIMEDIA), re.IGNORECASE)

# Restos de interfaz que a veces se cuelan pegados al texto del comentario
_RUIDO_INTERFAZ = re.compile(
    r"\b(Me gusta|Responder|Compartir|Editado|Like|Reply|Share|Edited|"
    r"Ver m[aá]s|See more|Ver traducci[oó]n|See translation|"
    r"Autor|Author|Destacado|Top fan|Fan destacado)\b\s*$",
    re.IGNORECASE,
)

# Espacios repetidos y saltos de linea excesivos
_ESPACIOS = re.compile(r"[ \t ]+")
_SALTOS = re.compile(r"\n{3,}")


def limpiar_texto(texto: str) -> str:
    """Devuelve el comentario listo para guardar (texto + emojis).

    Devuelve cadena vacia si despues de limpiar no queda nada util,
    lo que significa que el "comentario" era solo un GIF/sticker/imagen.
    """
    if not texto:
        return ""

    # Normalizamos para que los emojis y acentos queden en una sola forma
    t = unicodedata.normalize("NFC", texto)

    # Quitamos caracteres invisibles
    t = _INVISIBLES.sub("", t)

    # Unificamos saltos de linea
    t = t.replace("\r\n", "\n").replace("\r", "\n")

    # Quitamos marcadores de multimedia linea por linea
    lineas = []
    for linea in t.split("\n"):
        if _RE_MULTIMEDIA.search(linea.strip()):
            continue
        lineas.append(linea)
    t = "\n".join(lineas)

    # Quitamos restos de botones de interfaz al final
    for _ in range(3):  # puede haber varios pegados: "…Me gusta Responder"
        nuevo = _RUIDO_INTERFAZ.sub("", t.rstrip())
        if nuevo == t:
            break
        t = nuevo

    # Colapsamos espacios y saltos sobrantes
    t = _ESPACIOS.sub(" ", t)
    t = _SALTOS.sub("\n\n", t)
    t = t.strip()

    # Si solo quedaron signos de puntuacion sueltos, lo tratamos como vacio.
    # OJO: un comentario que sea SOLO emojis SI se conserva (eso lo queremos).
    if not t:
        return ""
    if all(unicodedata.category(c).startswith("P") or c.isspace() for c in t):
        return ""

    return t


def limpiar_autor(nombre: str) -> str:
    """Deja el nombre del autor sin adornos ('Top fan', 'Autor', etc.)."""
    if not nombre:
        return "(desconocido)"
    n = _INVISIBLES.sub("", unicodedata.normalize("NFC", nombre))
    n = n.split("\n")[0]
    n = re.sub(
        r"\s*(Top fan|Fan destacado|Autor|Author|Verificado|Verified)\s*$",
        "",
        n,
        flags=re.IGNORECASE,
    )
    n = _ESPACIOS.sub(" ", n).strip()
    return n or "(desconocido)"


def solo_emojis(texto: str) -> bool:
    """True si el comentario esta compuesto unicamente por emojis/simbolos."""
    if not texto:
        return False
    return all(
        unicodedata.category(c) in ("So", "Sk", "Cf") or c.isspace()
        for c in texto
    )
