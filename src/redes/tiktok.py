"""Extractor de TikTok.

TikTok tiene una ventaja que ni Facebook ni Instagram tienen: el
identificador del video LLEVA LA FECHA DENTRO. Es un numero de 19 cifras
cuyos 32 bits altos son la marca de tiempo Unix:

    7318472936482910234 >> 32  ->  30/12/2023 14:32

Eso cambia el juego. En Facebook e Instagram habia que abrir cada
publicacion para saber su fecha (y pelear con que la pagina traia varias).
Aqui la fecha sale de la propia URL, sin abrir nada: el recorrido del perfil
filtra por fecha al instante y para en cuanto se sale del rango.

Del resto, se aplica todo lo aprendido:
  - los comentarios viven en un panel con scroll propio, que se ancla
  - nunca se lee de document.body: la pagina trae los videos siguientes
  - si el reproductor salta a otro video, se corta
  - si algo sale a cero, se guarda la pagina para diagnosticarla
"""

from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Page

from ..core.limpieza import limpiar_autor, limpiar_texto
from ..core.modelos import Comentario, Publicacion
from ..core.rutas import CARPETA_CONFIG, CARPETA_DIAGNOSTICO
from .base import ExtractorRed, OpcionesExtraccion, Progreso
from .js_tiktok import (
    JS_ALTURA_PAGINA,
    JS_ANCLAR_PANEL,
    JS_DATOS_PUBLICACION,
    JS_DESPLAZAR,
    JS_DESPLAZAR_PANEL,
    JS_ENLACES_PUBLICACIONES,
    JS_ESTADO_PAGINA,
    JS_IR_A,
    JS_IR_AL_FONDO,
    JS_LEER_COMENTARIOS,
    JS_POSICION,
    JS_PULSAR_BOTONES,
    JS_SESION_INICIADA,
)

# TikTok se lanzo en 2016; nada anterior puede ser real
_MINIMO = datetime(2016, 1, 1)


def _cargar_config() -> dict:
    with open(CARPETA_CONFIG / "tiktok.json", "r", encoding="utf-8") as f:
        return json.load(f)


def fecha_desde_id(id_video: str) -> datetime | None:
    """Saca la fecha de publicacion del propio identificador del video.

    Los identificadores de TikTok son numeros de 64 bits cuyos 32 bits altos
    son la marca de tiempo Unix. No hace falta abrir el video ni leer nada
    de la pagina: la fecha esta en la URL.

    Devuelve None si el numero no produce una fecha creible, para no
    inventarse nada si TikTok cambiara de formato.
    """
    if not id_video or not id_video.isdigit():
        return None
    try:
        epoch = int(id_video) >> 32
        fecha = datetime.fromtimestamp(epoch)
    except (ValueError, OSError, OverflowError):
        return None
    if not (_MINIMO <= fecha <= datetime.now() + timedelta(days=2)):
        return None
    return fecha


class ExtractorTikTok(ExtractorRed):
    nombre = "tiktok"
    etiqueta = "TikTok"
    url_inicio = "https://www.tiktok.com/"
    implementado = True
    ayuda = (
        "Pega la URL del perfil, por ejemplo:\n"
        "  https://www.tiktok.com/@nombredeusuario\n\n"
        "Necesitas haber iniciado sesion (boton 'Abrir navegador e iniciar sesion').\n"
        "TikTok es la red mas estricta con la automatizacion: deja el navegador\n"
        "visible para resolver a mano cualquier captcha que aparezca."
    )

    def __init__(self) -> None:
        self.cfg = _cargar_config()

    # ------------------------------------------------------------------ sesion

    def sesion_iniciada(self, pagina: Page) -> bool:
        try:
            pagina.goto(self.url_inicio, wait_until="domcontentloaded", timeout=30_000)
            pagina.wait_for_timeout(3000)
            return bool(pagina.evaluate(JS_SESION_INICIADA))
        except Exception:
            return False

    # ----------------------------------------------------------- normalizacion

    def normalizar_url_perfil(self, url: str) -> str:
        u = (url or "").strip()
        if not u:
            return ""
        if not u.startswith("http"):
            if "tiktok.com" in u:
                u = "https://" + u.lstrip("/")
            else:
                usuario = u.lstrip("@").strip("/")
                u = f"https://www.tiktok.com/@{usuario}"
        return u.split("?")[0].rstrip("/")

    @staticmethod
    def _identificador_publicacion(url: str) -> str:
        m = re.search(r"/(?:video|photo)/(\d+)", url or "")
        return m.group(1) if m else ""

    @classmethod
    def _normalizar_url_publicacion(cls, href: str) -> str:
        if not href or "tiktok.com" not in href:
            return ""
        ruta = urlsplit(href).path
        m = re.search(r"/(@[^/]+)/(video|photo)/(\d+)", ruta)
        if not m:
            return ""
        return f"https://www.tiktok.com/{m.group(1)}/{m.group(2)}/{m.group(3)}"

    @staticmethod
    def _tipo_publicacion(url: str) -> str:
        return "foto" if "/photo/" in url else "video"

    # ------------------------------------------------------ FASE 1: descubrir

    def descubrir_publicaciones(
        self, pagina: Page, opciones: OpcionesExtraccion, progreso: Progreso
    ) -> list[Publicacion]:
        url_perfil = self.normalizar_url_perfil(opciones.url_perfil)
        if not url_perfil:
            raise ValueError("Falta la URL del perfil de TikTok.")

        desde = opciones.desde or _MINIMO
        hasta = opciones.hasta or datetime.now()
        encontradas: dict[str, Publicacion] = {}

        progreso.log(f"Abriendo el perfil: {url_perfil}")
        progreso.log(
            "La fecha de cada video sale de su identificador, asi que no hace "
            "falta abrirlos uno a uno para saber cuando se publicaron."
        )
        pagina.goto(url_perfil, wait_until="domcontentloaded", timeout=60_000)
        pagina.wait_for_timeout(3500)
        self._cerrar_estorbos(pagina)

        # Antes de nada, contamos que estamos viendo. Un muro de acceso, un
        # captcha y una pagina que no cargo dan los tres cero enlaces, asi que
        # sin esto no hay forma de distinguirlos.
        self._informar_estado(pagina, progreso, "al abrir el perfil")

        if "/login" in pagina.url:
            raise RuntimeError(
                "TikTok pidio iniciar sesion. Usa el boton "
                "'Abrir navegador e iniciar sesion' y vuelve a intentarlo."
            )

        try:
            alto = int(pagina.evaluate("() => window.innerHeight") or 900)
        except Exception:
            alto = 900
        paso = max(300, int(alto * 0.60))

        patrones = self.cfg["patrones_url_publicacion"]
        sin_nuevas = rondas_al_final = sin_fecha = 0
        limite = time.monotonic() + max(1, opciones.minutos_por_seccion) * 60

        for ronda in range(1, opciones.max_desplazamientos + 1):
            if progreso.cancelado():
                break
            if not opciones.exhaustivo and time.monotonic() > limite:
                progreso.log("   Se agoto el tiempo asignado al recorrido.")
                break

            try:
                crudos = pagina.evaluate(JS_ENLACES_PUBLICACIONES, patrones)
            except Exception as e:
                progreso.log(f"   Aviso al leer la pagina: {str(e)[:90]}")
                crudos = []

            antes = len(encontradas)
            rechazados = 0
            for item in crudos:
                url = self._normalizar_url_publicacion(item.get("href", ""))
                if not url:
                    rechazados += 1
                    continue
                if url in encontradas:
                    continue
                identificador = self._identificador_publicacion(url)
                fecha = fecha_desde_id(identificador)
                if fecha is None:
                    sin_fecha += 1
                encontradas[url] = Publicacion(
                    url=url,
                    red=self.nombre,
                    perfil=url_perfil,
                    fecha=fecha,
                    tipo=self._tipo_publicacion(url),
                    texto=(item.get("texto") or "")[:300],
                    seccion="Perfil",
                )
            nuevas = len(encontradas) - antes
            sin_nuevas = 0 if nuevas else sin_nuevas + 1

            if ronda == 1 or (ronda == 5 and not encontradas):
                progreso.log(
                    f"   Vuelta {ronda}: {len(crudos)} enlaces vistos, "
                    f"{rechazados} descartados, {len(encontradas)} reconocidos."
                )
                if crudos and not encontradas:
                    ejemplos = [c.get("href", "")[:80] for c in crudos[:3]]
                    progreso.log(
                        "   ⚠ Veo enlaces pero no reconozco ninguno. Ejemplos:\n"
                        + "\n".join(f"      {e}" for e in ejemplos)
                    )
                elif not crudos and ronda == 5:
                    # Cinco vueltas sin ver ni un enlace: aqui pasa algo que
                    # no es «este perfil no publica». Hay que verlo.
                    self._informar_estado(pagina, progreso, "tras 5 vueltas sin enlaces")
                    ruta = self.guardar_diagnostico(pagina, "tiktok_sin_enlaces")
                    progreso.log(f"   Guarde la pagina en: {ruta}")

            con_fecha = [p for p in encontradas.values() if p.fecha]
            progreso.paso(
                min(len(encontradas), opciones.max_publicaciones),
                opciones.max_publicaciones,
                f"Explorando el perfil… {len(encontradas)} publicaciones "
                f"(vuelta {ronda})",
            )

            # La cuadricula va de lo mas nuevo a lo mas viejo y ya sabemos la
            # fecha de todo lo visto: en cuanto la mas antigua se sale del
            # rango, lo que queda debajo tambien. Sin abrir ni un video.
            if con_fecha and not opciones.exhaustivo:
                mas_antigua = min(p.fecha for p in con_fecha)
                if mas_antigua < desde - timedelta(days=1):
                    progreso.log(
                        f"   La mas antigua vista es del {mas_antigua:%d/%m/%Y}: "
                        "ya pasamos el rango. Fin del recorrido."
                    )
                    break

            if len([p for p in con_fecha if desde <= p.fecha <= hasta]) \
                    >= opciones.max_publicaciones:
                progreso.log("   Se alcanzo el maximo de publicaciones configurado.")
                break

            try:
                estado = pagina.evaluate(JS_DESPLAZAR, paso) or {}
            except Exception:
                estado = {}
            pagina.wait_for_timeout(random.randint(700, 1200))

            if estado.get("al_final") or not estado.get("se_movio"):
                altura_antes = estado.get("altura", 0)
                try:
                    y = int(pagina.evaluate(JS_POSICION) or 0)
                    pagina.evaluate(JS_IR_A, max(0, y - 700))
                    pagina.wait_for_timeout(500)
                    pagina.evaluate(JS_IR_AL_FONDO)
                except Exception:
                    pass
                pagina.wait_for_timeout(2500)
                try:
                    ahora = pagina.evaluate(JS_ALTURA_PAGINA)
                except Exception:
                    ahora = altura_antes
                if ahora > altura_antes + 200:
                    rondas_al_final = 0
                else:
                    rondas_al_final += 1
                    if rondas_al_final >= 4:
                        progreso.log("   Se llego al final del perfil.")
                        break
            else:
                rondas_al_final = 0

            if sin_nuevas >= 3:
                pagina.wait_for_timeout(1500)
            if sin_nuevas >= (45 if opciones.exhaustivo else 25):
                progreso.log("   No aparecen publicaciones nuevas.")
                if not encontradas:
                    ruta = self.guardar_diagnostico(pagina, "tiktok_perfil_vacio")
                    progreso.log(f"   ⚠ Ninguna publicacion reconocida. Guarde: {ruta}")
                break

        en_rango, sin_confirmar, fuera = [], [], []
        for pub in encontradas.values():
            if pub.fecha is None:
                pub.seleccionada = False
                pub.nota = "El identificador no dio una fecha creible"
                sin_confirmar.append(pub)
            elif desde <= pub.fecha <= hasta:
                pub.seleccionada = True
                en_rango.append(pub)
            else:
                fuera.append(pub)

        progreso.log(
            f"Publicaciones vistas: {len(encontradas)} → {len(en_rango)} dentro "
            f"del rango, {len(fuera)} fuera, {len(sin_confirmar)} sin fecha."
        )
        en_rango.sort(key=lambda p: p.fecha or datetime.min, reverse=True)
        tope = 300 if opciones.exhaustivo else 30
        return en_rango[: opciones.max_publicaciones] + sin_confirmar[:tope]

    # ---------------------------------------------------- FASE 2: comentarios

    def extraer_comentarios(
        self,
        pagina: Page,
        publicacion: Publicacion,
        opciones: OpcionesExtraccion,
        progreso: Progreso,
    ) -> list[Comentario]:
        identificador = self._identificador_publicacion(publicacion.url)
        progreso.log(f"Abriendo publicacion: {publicacion.url}")
        pagina.goto(publicacion.url, wait_until="domcontentloaded", timeout=60_000)
        pagina.wait_for_timeout(3000)
        self._cerrar_estorbos(pagina)

        # La fecha ya la sabemos por el identificador; confirmamos con la
        # pagina solo si podemos hacerlo sin ambiguedad.
        anunciados = ""
        try:
            datos = pagina.evaluate(JS_DATOS_PUBLICACION, identificador) or {}
            if datos.get("epoch") and datos.get("confianza") != "ninguna":
                try:
                    publicacion.fecha = datetime.fromtimestamp(int(datos["epoch"]))
                    publicacion.fecha_aproximada = False
                except (OSError, OverflowError, ValueError):
                    pass
            if datos.get("texto") and not publicacion.texto:
                publicacion.texto = datos["texto"]
            anunciados = datos.get("anunciados") or ""
            if anunciados:
                progreso.log(f"   TikTok anuncia {anunciados} comentarios.")
        except Exception:
            pass

        if opciones.verificar_rango_al_extraer and publicacion.fecha \
                and opciones.desde and opciones.hasta \
                and not (opciones.desde <= publicacion.fecha <= opciones.hasta):
            publicacion.estado = "omitida"
            publicacion.nota = (
                f"Fuera del rango (fecha real {publicacion.fecha:%d/%m/%Y})")
            progreso.log(f"   ↷ Omitida: es del {publicacion.fecha:%d/%m/%Y}.")
            return []

        acumulados: dict[str, dict] = {}
        sin_nuevos = 0
        anclado_avisado = False

        for vuelta in range(1, 81):
            if progreso.cancelado():
                break

            # ¿Salto el reproductor a otro video? Entonces lo que venga ya no
            # es de esta publicacion.
            actual = self._identificador_publicacion(pagina.url)
            if identificador and actual and actual != identificador:
                progreso.log(
                    "   El reproductor salto a otro video; corto aqui para no "
                    "mezclar comentarios."
                )
                break

            pulsados = 0
            for clave, tope in (("boton_mas_comentarios", 10),
                                ("boton_ver_respuestas", 10)):
                try:
                    pulsados += pagina.evaluate(
                        JS_PULSAR_BOTONES, [self.cfg[clave], tope]) or 0
                except Exception:
                    pass
            pagina.wait_for_timeout(random.randint(700, 1200))

            # Re-anclamos cada vuelta: al principio la lista aun no existe y
            # despues TikTok reemplaza nodos al cargar mas comentarios.
            try:
                ancla = pagina.evaluate(JS_ANCLAR_PANEL) or {}
            except Exception:
                ancla = {}
            if ancla.get("ok") and not anclado_avisado:
                anclado_avisado = True
                progreso.log("   Panel de comentarios anclado a esta publicacion.")

            crudos, ambito, bloques = self._leer_comentarios_crudos(pagina)
            if vuelta == 1:
                progreso.log(f"   Leyendo comentarios de: {ambito} ({bloques} bloques)")

            nuevos = 0
            for c in crudos:
                clave = f"{(c.get('autor') or '').strip()}|{(c.get('texto') or '').strip()}"
                if clave not in acumulados:
                    acumulados[clave] = c
                    nuevos += 1

            progreso.paso(
                len(acumulados),
                max(len(acumulados), opciones.max_comentarios_por_publicacion),
                f"Cargando comentarios… {len(acumulados)} leidos",
            )
            if len(acumulados) >= opciones.max_comentarios_por_publicacion:
                progreso.log("Se alcanzo el maximo de comentarios configurado.")
                break

            movido = False
            try:
                estado = pagina.evaluate(JS_DESPLAZAR_PANEL) or {}
                movido = bool(estado.get("se_movio"))
            except Exception:
                pass
            pagina.wait_for_timeout(700)

            sin_nuevos = 0 if nuevos else sin_nuevos + 1
            if pulsados == 0 and not movido and sin_nuevos >= 3:
                break
            if sin_nuevos >= 8:
                break

        comentarios: list[Comentario] = []
        descartados = 0
        for c in acumulados.values():
            texto = limpiar_texto(c.get("texto", ""))
            if not texto:
                descartados += 1
                continue
            if c.get("es_respuesta") and not opciones.incluir_respuestas:
                continue
            comentarios.append(
                Comentario(
                    publicacion_url=publicacion.url,
                    red=self.nombre,
                    autor=limpiar_autor(c.get("autor", "")),
                    texto=texto,
                    fecha=None,
                    es_respuesta=bool(c.get("es_respuesta")),
                )
            )
            if len(comentarios) >= opciones.max_comentarios_por_publicacion:
                break

        if descartados:
            progreso.log(
                f"Se ignoraron {descartados} comentarios sin texto "
                "(eran GIF, sticker o imagen)."
            )
        if not comentarios and not acumulados:
            ruta = self.guardar_diagnostico(pagina, "tiktok_sin_comentarios")
            progreso.log(
                f"⚠ No se encontro ningun comentario. Guarde la pagina en:\n   {ruta}"
            )
        if anunciados:
            progreso.log(
                f"Comentarios de texto extraidos: {len(comentarios)} "
                f"(TikTok anunciaba {anunciados})"
            )
        else:
            progreso.log(f"Comentarios de texto extraidos: {len(comentarios)}")
        return comentarios

    # -------------------------------------------------------------- auxiliares

    def _informar_estado(self, pagina: Page, progreso: Progreso, cuando: str) -> None:
        """Cuenta en el registro que pagina estamos viendo de verdad.

        Un muro de acceso, un captcha y una pagina que no cargo producen todos
        cero enlaces. Distinguirlos a ciegas es imposible; con esto se ve.
        """
        try:
            e = pagina.evaluate(JS_ESTADO_PAGINA) or {}
        except Exception as err:
            progreso.log(f"   No se pudo leer el estado de la pagina: {str(err)[:80]}")
            return

        progreso.log(
            f"   Estado {cuando}: {e.get('enlaces_total', 0)} enlaces en total, "
            f"{e.get('enlaces_video', 0)} de video · «{str(e.get('titulo'))[:50]}»"
        )
        # Si ya hay enlaces a videos, la pagina esta bien: no hay nada que
        # avisar aunque tenga poco texto (un perfil es casi todo miniaturas).
        if e.get("enlaces_video"):
            return

        if e.get("hay_captcha"):
            progreso.log(
                "   ⚠ TikTok esta pidiendo una VERIFICACION (captcha). "
                "Resuelvela a mano en la ventana del navegador y vuelve a "
                "pulsar «Buscar publicaciones»."
            )
        elif e.get("hay_login"):
            progreso.log(
                "   ⚠ TikTok esta pidiendo INICIAR SESION para ver este perfil. "
                "Usa «Abrir navegador e iniciar sesion», o pega las URLs de los "
                "videos a mano en el Paso 4."
            )
        elif e.get("parece_vacio"):
            progreso.log(
                "   ⚠ La pagina esta practicamente vacia: no llego a cargar. "
                "Prueba con el boton 🔄 de recargar."
            )
        elif not e.get("enlaces_video"):
            progreso.log(
                "   ⚠ La pagina cargo pero no trae enlaces a videos. "
                f"Primeras palabras: «{str(e.get('texto'))[:120]}»"
            )

    def _leer_comentarios_crudos(self, pagina: Page) -> tuple[list[dict], str, int]:
        try:
            datos = pagina.evaluate(
                JS_LEER_COMENTARIOS,
                [self.cfg["selectores_bloque_comentario"],
                 self.cfg["selectores_autor"],
                 self.cfg["selectores_texto"]],
            )
        except Exception:
            return [], "error al leer", 0
        if isinstance(datos, dict):
            return (datos.get("comentarios") or [],
                    datos.get("ambito", ""),
                    datos.get("bloques", 0))
        return datos or [], "", 0

    def _cerrar_estorbos(self, pagina: Page) -> None:
        """Cierra cookies y ventanas emergentes.

        En cookies se elige siempre la opcion que menos datos comparte.
        """
        try:
            pagina.evaluate(
                JS_PULSAR_BOTONES,
                ["(rechazar|decline|solo cookies necesarias|"
                 "denegar|reject all|solo esenciales)", 2],
            )
            pagina.wait_for_timeout(600)
        except Exception:
            pass
        try:
            pagina.evaluate(
                JS_PULSAR_BOTONES, [self.cfg["boton_cerrar_dialogo"], 2])
            pagina.wait_for_timeout(400)
        except Exception:
            pass

    def guardar_diagnostico(self, pagina: Page, etiqueta: str = "tiktok") -> Path:
        marca = datetime.now().strftime("%Y%m%d_%H%M%S")
        destino = CARPETA_DIAGNOSTICO / f"{etiqueta}_{marca}.html"
        try:
            destino.write_text(pagina.content(), encoding="utf-8", errors="ignore")
            pagina.screenshot(
                path=str(CARPETA_DIAGNOSTICO / f"{etiqueta}_{marca}.png"))
        except Exception:
            pass
        return destino
