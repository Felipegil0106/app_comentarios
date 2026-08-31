"""Contrato comun para todas las redes sociales.

Cada red (Facebook, Instagram, TikTok, X) implementa esta misma interfaz.
Asi la interfaz grafica no necesita saber nada de cada red en concreto:
solo llama a `descubrir_publicaciones` y `extraer_comentarios`.

Para agregar una red nueva basta con crear una clase que herede de
`ExtractorRed` y registrarla en `registro.py`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from playwright.sync_api import Page

from ..core.modelos import Comentario, Publicacion


@dataclass
class Progreso:
    """Canal para informar al usuario mientras la extraccion corre."""

    log: Callable[[str], None] = lambda m: None
    paso: Callable[[int, int, str], None] = lambda hecho, total, msg: None
    cancelado: Callable[[], bool] = lambda: False

    def aviso(self, mensaje: str) -> None:
        self.log(mensaje)


@dataclass
class OpcionesExtraccion:
    """Todo lo que el usuario configura antes de extraer."""

    url_perfil: str = ""
    desde: datetime | None = None
    hasta: datetime | None = None
    max_publicaciones: int = 100
    max_comentarios_por_publicacion: int = 1000
    incluir_respuestas: bool = True
    max_desplazamientos: int = 60
    urls_manuales: list[str] = field(default_factory=list)
    # Tras recorrer el muro, abre cada publicacion para leer su fecha EXACTA.
    # Es mas lento pero imprescindible: la fecha que se ve en el muro puede ser
    # la de un comentario, no la de la publicacion.
    verificar_fechas: bool = True
    # Recorrer tambien las pestañas Reels / Videos / Fotos del perfil, no solo
    # la linea de tiempo. Facebook no lista todos los reels en el muro, asi que
    # sin esto siempre faltarian publicaciones.
    buscar_en_pestanas: bool = True
    # Minutos maximos recorriendo CADA seccion. Sin este tope, una pestaña
    # como «Videos» puede tirarse media hora bajando por todo el historial
    # del perfil aunque el rango de fechas sea de tres dias.
    minutos_por_seccion: int = 8
    # Modo exhaustivo: prioriza NO dejarse ninguna publicacion por encima de la
    # velocidad. Quita el tope de tiempo, sube todos los umbrales de parada y
    # comprueba la fecha de todos los candidatos. Es mucho mas lento.
    exhaustivo: bool = False
    # Al abrir cada publicacion se lee su fecha EXACTA. Si esta activo y la
    # fecha real cae fuera del rango, se omite. Solo se usa en modo automatico:
    # cuando el usuario elige las publicaciones a mano, manda su eleccion.
    verificar_rango_al_extraer: bool = False


class ExtractorRed(ABC):
    """Clase base. Cada red social hereda de aqui."""

    nombre: str = "red"          # identificador interno, minusculas
    etiqueta: str = "Red social"  # nombre visible en la interfaz
    url_inicio: str = ""          # pagina para iniciar sesion
    implementado: bool = False    # False = todavia es un esqueleto
    ayuda: str = ""               # texto de ayuda que se muestra en la app
    # Dominios que maneja esta red. Sirven para avisar cuando la URL pegada
    # no corresponde a la red elegida, en vez de buscar en el sitio
    # equivocado y devolver cero sin explicar por que.
    dominios: tuple[str, ...] = ()

    # ------------------------------------------------------------------ sesion

    @abstractmethod
    def sesion_iniciada(self, pagina: Page) -> bool:
        """True si el navegador ya tiene sesion abierta en esta red."""

    def abrir_login(self, pagina: Page) -> None:
        """Lleva el navegador a la pantalla de inicio de sesion."""
        pagina.goto(self.url_inicio, wait_until="domcontentloaded")

    # ------------------------------------------------------------------- fases

    @abstractmethod
    def descubrir_publicaciones(
        self, pagina: Page, opciones: OpcionesExtraccion, progreso: Progreso
    ) -> list[Publicacion]:
        """Fase 1: recorre el perfil y lista las publicaciones del rango de fechas."""

    @abstractmethod
    def extraer_comentarios(
        self,
        pagina: Page,
        publicacion: Publicacion,
        opciones: OpcionesExtraccion,
        progreso: Progreso,
    ) -> list[Comentario]:
        """Fase 2: abre una publicacion y devuelve sus comentarios de texto."""

    # -------------------------------------------------------------- utilidades

    def normalizar_url_perfil(self, url: str) -> str:
        """Corrige/completa la URL del perfil que escribio el usuario."""
        return url.strip()

    def publicacion_desde_url(self, url: str) -> Publicacion:
        """Crea una publicacion 'vacia' a partir de una URL pegada a mano."""
        return Publicacion(url=url.strip(), red=self.nombre, tipo="publicacion")


class ExtractorNoImplementado(ExtractorRed):
    """Plantilla para las redes que todavia no estan listas.

    Aparecen en la interfaz (para que veas hacia donde va la app) pero
    avisan claramente que aun no funcionan.
    """

    implementado = False

    def sesion_iniciada(self, pagina: Page) -> bool:  # pragma: no cover
        return False

    def descubrir_publicaciones(self, pagina, opciones, progreso):  # pragma: no cover
        raise NotImplementedError(
            f"{self.etiqueta} todavia no esta implementado. "
            "Por ahora usa Facebook."
        )

    def extraer_comentarios(self, pagina, publicacion, opciones, progreso):  # pragma: no cover
        raise NotImplementedError(
            f"{self.etiqueta} todavia no esta implementado."
        )
