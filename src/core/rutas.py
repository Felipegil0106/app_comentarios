"""Rutas de carpetas que usa la aplicacion.

Todo lo que la app guarda (base de datos, sesiones del navegador, registros)
vive dentro de una sola carpeta en tu usuario de Windows, para no ensuciar
la carpeta del programa.
"""

from __future__ import annotations

import os
from pathlib import Path

# Carpeta raiz del codigo fuente (…/extraer_comentarios)
RAIZ_PROYECTO = Path(__file__).resolve().parents[2]

# Carpeta donde guardamos datos del usuario.
# En Windows queda en: C:\Users\<tu_usuario>\AppData\Roaming\ExtractorComentarios
_APPDATA = os.environ.get("APPDATA") or str(Path.home())
CARPETA_DATOS = Path(_APPDATA) / "ExtractorComentarios"

# Base de datos SQLite con publicaciones y comentarios
RUTA_BD = CARPETA_DATOS / "datos.sqlite3"

# Perfiles del navegador (aqui quedan guardadas las sesiones/cookies de cada red)
CARPETA_NAVEGADORES = CARPETA_DATOS / "navegadores"

# Archivos de registro (log) por si algo falla y hay que revisarlo
CARPETA_LOGS = CARPETA_DATOS / "logs"

# Volcados de HTML para diagnostico cuando un selector deja de funcionar
CARPETA_DIAGNOSTICO = CARPETA_DATOS / "diagnostico"

# Configuracion editable (selectores de cada red social)
CARPETA_CONFIG = RAIZ_PROYECTO / "src" / "config"


def asegurar_carpetas() -> None:
    """Crea las carpetas necesarias si todavia no existen."""
    for carpeta in (
        CARPETA_DATOS,
        CARPETA_NAVEGADORES,
        CARPETA_LOGS,
        CARPETA_DIAGNOSTICO,
    ):
        carpeta.mkdir(parents=True, exist_ok=True)


def carpeta_perfil_navegador(red: str) -> Path:
    """Carpeta del perfil de navegador para una red social concreta.

    Cada red tiene su propio perfil para que las sesiones no se mezclen.
    """
    ruta = CARPETA_NAVEGADORES / red.lower()
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta
