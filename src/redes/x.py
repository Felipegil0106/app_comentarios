"""Extractor de X (antes Twitter).

Comparte con TikTok la mejor propiedad de todas: el identificador del tuit
LLEVA LA FECHA DENTRO. X usa identificadores «snowflake», cuyos bits altos
son los milisegundos desde su propia epoca (4 de noviembre de 2010):

    (1750000000000000000 >> 22) + 1288834974657  ->  23/01/2024

Asi que la fecha sale de la URL, sin abrir el tuit. Con un cuidado: los
identificadores anteriores a esa fecha NO son snowflake y darian fechas
absurdas; se descartan.

En X los «comentarios» son las RESPUESTAS al tuit. Se aplican las mismas
defensas que en las otras redes:
  - se lee solo dentro de la conversacion, nunca de document.body: debajo
    X pone «Descubre mas», con tuits de otros que no responden a este
  - el tuit original tiene la misma forma que una respuesta, y se distingue
    porque su identificador es el de la URL
  - se baja menos de una pantalla, con rebote al llegar al fondo
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
from .js_x import (
    JS_ALTURA_PAGINA,
    JS_ANCLAR_PANEL,
    JS_DESPLAZAR,
    JS_ENLACES_PUBLICACIONES,
    JS_ESTADO_PAGINA,
    JS_IDS_INCRUSTADOS,
    JS_IR_A,
    JS_IR_AL_FONDO,
    JS_LEER_RESPUESTAS,
    JS_POSICION,
    JS_PULSAR_BOTONES,
    JS_SESION_INICIADA,
)

# X empezo a usar identificadores «snowflake» el 4 de noviembre de 2010.
_EPOCA_MS = 1288834974657
_MINIMO = datetime(2010, 11, 5)


def _cargar_config() -> dict:
    with open(CARPETA_CONFIG / "x.json", "r", encoding="utf-8") as f:
        return json.load(f)


def fecha_desde_id(id_tuit: str) -> datetime | None:
    """Saca la fecha de publicacion del identificador del tuit.

    Los identificadores de X son «snowflake»: sus bits altos son los
    milisegundos transcurridos desde el 4 de noviembre de 2010. No hace falta
    abrir el tuit.

    Devuelve None si el numero no da una fecha creible. Es importante: los
    tuits anteriores a noviembre de 2010 llevan identificadores cortos que no
    son snowflake, y descifrarlos daria fechas inventadas.
    """
    if not id_tuit or not id_tuit.isdigit() or len(id_tuit) < 15:
        return None
    try:
        ms = (int(id_tuit) >> 22) + _EPOCA_MS
        fecha = datetime.fromtimestamp(ms / 1000)
    except (ValueError, OSError, OverflowError):
        return None
    if not (_MINIMO <= fecha <= datetime.now() + timedelta(days=2)):
        return None
    return fecha


class ExtractorX(ExtractorRed):
    nombre = "x"
    etiqueta = "X (Twitter)"
    url_inicio = "https://x.com/"
    dominios = ("x.com", "twitter.com")
    implementado = True
    ayuda = (
        "Pega la URL del perfil, por ejemplo:\n"
        "  https://x.com/nombredeusuario\n\n"
        "En X los «comentarios» son las respuestas a cada publicacion.\n\n"
        "X casi siempre exige iniciar sesion para ver nada. Si no te deja:\n"
        "usa «Abrir este perfil en el navegador», entra tu en esa ventana,\n"
        "marca «La pagina ya esta abierta» y pulsa Buscar publicaciones.\n"
        "Al entrar, usa usuario y contraseña de X, no el boton de Google."
    )

    def __init__(self) -> None:
        self.cfg = _cargar_config()

    # ------------------------------------------------------------------ sesion

    def abrir_login(self, pagina: Page) -> None:
        pagina.goto("https://x.com/i/flow/login",
                    wait_until="domcontentloaded", timeout=45_000)

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
        if u.startswith("@"):
            u = u[1:]
        if not u.startswith("http"):
            if "x.com" in u or "twitter.com" in u:
                u = "https://" + u.lstrip("/")
            else:
                u = "https://x.com/" + u.strip("/")
        u = u.replace("://twitter.com", "://x.com").replace("://www.x.com", "://x.com")
        return u.split("?")[0].rstrip("/")

    @staticmethod
    def _usuario_de_url(url: str) -> str:
        m = re.search(r"(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})", url or "")
        return m.group(1) if m else ""

    @staticmethod
    def _identificador_publicacion(url: str) -> str:
        m = re.search(r"/status/(\d+)", url or "")
        return m.group(1) if m else ""

    @classmethod
    def _normalizar_url_publicacion(cls, href: str) -> str:
        if not href:
            return ""
        if "x.com" not in href and "twitter.com" not in href:
            return ""
        ruta = urlsplit(href).path
        m = re.match(r"^/([A-Za-z0-9_]{1,15})/status/(\d{15,20})", ruta)
        if not m:
            return ""
        return f"https://x.com/{m.group(1)}/status/{m.group(2)}"

    # ------------------------------------------------------ FASE 1: descubrir

    def descubrir_publicaciones(
        self, pagina: Page, opciones: OpcionesExtraccion, progreso: Progreso
    ) -> list[Publicacion]:
        url_perfil = self.normalizar_url_perfil(opciones.url_perfil)
        if not url_perfil:
            raise ValueError("Falta la URL del perfil de X.")
        usuario = self._usuario_de_url(url_perfil).lower()

        desde = opciones.desde or _MINIMO
        hasta = opciones.hasta or datetime.now()
        encontradas: dict[str, Publicacion] = {}

        if opciones.usar_pagina_actual:
            progreso.log(
                "   Modo asistido: leo la pagina que ya tienes abierta, "
                f"sin navegar. ({pagina.url[:70]})"
            )
        else:
            progreso.log(f"Abriendo el perfil: {url_perfil}")
            pagina.goto(url_perfil, wait_until="domcontentloaded", timeout=60_000)
        progreso.log(
            "La fecha de cada publicacion sale de su identificador, asi que no "
            "hace falta abrirlas para saber cuando se publicaron."
        )
        pagina.wait_for_timeout(3000)
        self._cerrar_estorbos(pagina)
        self._informar_estado(pagina, progreso, "al abrir el perfil")

        if not opciones.usar_pagina_actual:
            try:
                estado = pagina.evaluate(JS_ESTADO_PAGINA) or {}
            except Exception:
                estado = {}
            if estado.get("hay_login"):
                raise RuntimeError(
                    "X llevo a su pantalla de acceso en vez de mostrar el perfil.\n\n"
                    "X exige cuenta para ver casi todo. Lo que mejor funciona:\n"
                    "1) «Abrir este perfil en el navegador» (Paso 2)\n"
                    "2) inicia sesion tu en esa ventana, con usuario y contraseña\n"
                    "   de X (no con el boton de Google, que bloquea la entrada\n"
                    "   desde navegadores automatizados)\n"
                    "3) marca «La pagina ya esta abierta» y vuelve a buscar."
                )

        try:
            alto = int(pagina.evaluate("() => window.innerHeight") or 900)
        except Exception:
            alto = 900
        paso = max(300, int(alto * 0.55))

        sin_nuevas = rondas_al_final = 0
        limite = time.monotonic() + max(1, opciones.minutos_por_seccion) * 60

        for ronda in range(1, opciones.max_desplazamientos + 1):
            if progreso.cancelado():
                break
            if not opciones.exhaustivo and time.monotonic() > limite:
                progreso.log("   Se agoto el tiempo asignado al recorrido.")
                break

            try:
                crudos = pagina.evaluate(JS_ENLACES_PUBLICACIONES) or []
            except Exception as e:
                progreso.log(f"   Aviso al leer la pagina: {str(e)[:90]}")
                crudos = []
            if not crudos:
                crudos = self._ids_incrustados(pagina, usuario, progreso,
                                               avisar=(ronda == 1))

            antes = len(encontradas)
            ajenos = 0
            for item in crudos:
                url = self._normalizar_url_publicacion(item.get("href", ""))
                if not url:
                    continue
                # En la cronologia salen tambien tuits de otros (retuits y
                # citas). Nos quedamos con los del perfil que se pidio.
                if usuario and self._usuario_de_url(url).lower() != usuario:
                    ajenos += 1
                    continue
                if url in encontradas:
                    continue
                identificador = self._identificador_publicacion(url)
                encontradas[url] = Publicacion(
                    url=url,
                    red=self.nombre,
                    perfil=url_perfil,
                    fecha=fecha_desde_id(identificador),
                    tipo="publicacion",
                    seccion="Perfil",
                )
            nuevas = len(encontradas) - antes
            sin_nuevas = 0 if nuevas else sin_nuevas + 1

            if ronda == 1 or (ronda == 5 and not encontradas):
                progreso.log(
                    f"   Vuelta {ronda}: {len(crudos)} enlaces vistos, "
                    f"{ajenos} de otras cuentas, {len(encontradas)} reconocidos."
                )

            con_fecha = [p for p in encontradas.values() if p.fecha]
            progreso.paso(
                min(len(encontradas), opciones.max_publicaciones),
                opciones.max_publicaciones,
                f"Explorando el perfil… {len(encontradas)} publicaciones "
                f"(vuelta {ronda})",
            )

            # La cronologia va de lo mas nuevo a lo mas viejo y ya sabemos la
            # fecha de todo lo visto: en cuanto la mas antigua se sale del
            # rango, lo que queda debajo tambien. Sin abrir ni un tuit.
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
            pagina.wait_for_timeout(random.randint(800, 1300))

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
                        progreso.log("   Se llego al final de la cronologia.")
                        break
            else:
                rondas_al_final = 0

            if sin_nuevas >= 3:
                pagina.wait_for_timeout(1500)
            if sin_nuevas >= (45 if opciones.exhaustivo else 25):
                progreso.log("   No aparecen publicaciones nuevas.")
                if not encontradas:
                    ruta = self.guardar_diagnostico(pagina, "x_perfil_vacio")
                    progreso.log(f"   ⚠ Ninguna publicacion reconocida. Guarde: {ruta}")
                break

        en_rango, sin_fecha, fuera = [], [], []
        for pub in encontradas.values():
            if pub.fecha is None:
                pub.seleccionada = False
                pub.nota = "El identificador no dio una fecha creible"
                sin_fecha.append(pub)
            elif desde <= pub.fecha <= hasta:
                pub.seleccionada = True
                en_rango.append(pub)
            else:
                fuera.append(pub)

        progreso.log(
            f"Publicaciones vistas: {len(encontradas)} → {len(en_rango)} dentro "
            f"del rango, {len(fuera)} fuera, {len(sin_fecha)} sin fecha."
        )
        en_rango.sort(key=lambda p: p.fecha or datetime.min, reverse=True)
        tope = 300 if opciones.exhaustivo else 30
        return en_rango[: opciones.max_publicaciones] + sin_fecha[:tope]

    # ---------------------------------------------------- FASE 2: respuestas

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

        if publicacion.fecha is None:
            publicacion.fecha = fecha_desde_id(identificador)

        if (opciones.verificar_rango_al_extraer and publicacion.fecha
                and opciones.desde and opciones.hasta
                and not (opciones.desde <= publicacion.fecha <= opciones.hasta)):
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

            # ¿Nos movio X a otra publicacion? Entonces lo que venga ya no es
            # de esta.
            actual = self._identificador_publicacion(pagina.url)
            if identificador and actual and actual != identificador:
                progreso.log(
                    "   La pagina salto a otra publicacion; corto aqui para no "
                    "mezclar respuestas."
                )
                break

            try:
                pulsados = pagina.evaluate(
                    JS_PULSAR_BOTONES,
                    [self.cfg["boton_mas_respuestas"], 8]) or 0
            except Exception:
                pulsados = 0
            pagina.wait_for_timeout(random.randint(800, 1300))

            try:
                ancla = pagina.evaluate(
                    JS_ANCLAR_PANEL, self.cfg["selectores_conversacion"]) or {}
            except Exception:
                ancla = {}
            if ancla.get("ok") and not anclado_avisado:
                anclado_avisado = True
                progreso.log("   Conversacion anclada a esta publicacion.")

            crudos, ambito, bloques = self._leer_respuestas(pagina, identificador)
            if vuelta == 1:
                progreso.log(f"   Leyendo respuestas de: {ambito} ({bloques} tuits)")

            nuevos = 0
            for c in crudos:
                clave = f"{(c.get('autor') or '').strip()}|{(c.get('texto') or '').strip()}"
                if clave not in acumulados:
                    acumulados[clave] = c
                    nuevos += 1

            progreso.paso(
                len(acumulados),
                max(len(acumulados), opciones.max_comentarios_por_publicacion),
                f"Cargando respuestas… {len(acumulados)} leidas",
            )
            if len(acumulados) >= opciones.max_comentarios_por_publicacion:
                progreso.log("Se alcanzo el maximo de comentarios configurado.")
                break

            movido = False
            try:
                estado = pagina.evaluate(JS_DESPLAZAR, 700) or {}
                movido = bool(estado.get("se_movio"))
            except Exception:
                pass
            pagina.wait_for_timeout(800)

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
            fecha = fecha_desde_id(c.get("id", "")) or None
            comentarios.append(
                Comentario(
                    publicacion_url=publicacion.url,
                    red=self.nombre,
                    autor=limpiar_autor(c.get("autor", "")),
                    texto=texto,
                    fecha=fecha,
                    es_respuesta=True,
                )
            )
            if len(comentarios) >= opciones.max_comentarios_por_publicacion:
                break

        if descartados:
            progreso.log(
                f"Se ignoraron {descartados} respuestas sin texto "
                "(eran solo imagen, GIF o video)."
            )
        if not comentarios and not acumulados:
            ruta = self.guardar_diagnostico(pagina, "x_sin_respuestas")
            progreso.log(
                f"⚠ No se encontro ninguna respuesta. Guarde la pagina en:\n   {ruta}"
            )
        progreso.log(f"Respuestas de texto extraidas: {len(comentarios)}")
        return comentarios

    # -------------------------------------------------------------- auxiliares

    def _leer_respuestas(
        self, pagina: Page, id_original: str
    ) -> tuple[list[dict], str, int]:
        try:
            datos = pagina.evaluate(
                JS_LEER_RESPUESTAS,
                [id_original,
                 self.cfg["selectores_bloque"],
                 self.cfg["selector_texto"],
                 self.cfg["selector_autor"],
                 self.cfg["selectores_conversacion"]],
            )
        except Exception:
            return [], "error al leer", 0
        if isinstance(datos, dict):
            return (datos.get("comentarios") or [],
                    datos.get("ambito", ""),
                    datos.get("bloques", 0))
        return datos or [], "", 0

    def _ids_incrustados(
        self, pagina: Page, usuario: str, progreso: Progreso, avisar: bool = False
    ) -> list[dict]:
        """Saca las publicaciones del HTML cuando la cronologia no se pinta."""
        try:
            ids = pagina.evaluate(JS_IDS_INCRUSTADOS) or []
        except Exception:
            return []
        validos = [i for i in ids if fecha_desde_id(i)]
        if validos and avisar:
            progreso.log(
                f"   La cronologia no se dibujo, pero encontre {len(validos)} "
                "publicaciones en los datos que trae la pagina."
            )
        return [
            {"href": f"https://x.com/{usuario}/status/{i}", "autor": usuario, "id": i}
            for i in validos
        ]

    def _informar_estado(self, pagina: Page, progreso: Progreso, cuando: str) -> None:
        try:
            e = pagina.evaluate(JS_ESTADO_PAGINA) or {}
        except Exception as err:
            progreso.log(f"   No se pudo leer el estado: {str(err)[:80]}")
            return
        progreso.log(
            f"   Estado {cuando}: {e.get('enlaces_status', 0)} enlaces a "
            f"publicaciones, {e.get('tuits', 0)} tuits · "
            f"«{str(e.get('titulo'))[:45]}»"
        )
        if e.get("enlaces_status"):
            return
        if e.get("hay_login"):
            progreso.log("   ⚠ X esta pidiendo iniciar sesion.")
        elif e.get("parece_vacio"):
            progreso.log("   ⚠ La pagina esta vacia: no llego a cargar.")
        elif not e.get("hay_sesion"):
            progreso.log(
                "   ⚠ Sin sesion iniciada. X enseña muy poco a las visitas."
            )

    def _cerrar_estorbos(self, pagina: Page) -> None:
        try:
            pagina.evaluate(
                JS_PULSAR_BOTONES,
                ["(rechazar|decline|solo cookies necesarias|reject)", 2])
            pagina.wait_for_timeout(500)
        except Exception:
            pass
        try:
            pagina.evaluate(
                JS_PULSAR_BOTONES, [self.cfg["boton_cerrar_dialogo"], 2])
            pagina.wait_for_timeout(400)
        except Exception:
            pass

    def guardar_diagnostico(self, pagina: Page, etiqueta: str = "x") -> Path:
        marca = datetime.now().strftime("%Y%m%d_%H%M%S")
        destino = CARPETA_DIAGNOSTICO / f"{etiqueta}_{marca}.html"
        try:
            destino.write_text(pagina.content(), encoding="utf-8", errors="ignore")
            pagina.screenshot(
                path=str(CARPETA_DIAGNOSTICO / f"{etiqueta}_{marca}.png"))
        except Exception:
            pass
        return destino
