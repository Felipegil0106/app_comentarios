"""Extractor de Instagram.

Escrito aplicando todo lo que costo sangre en Facebook:

  * La fecha NUNCA se deduce de la cuadricula. Se abre la publicacion y se
    lee su <time datetime>. Si no se puede saber con certeza cual es el de
    la publicacion, se deja SIN fecha antes que poner una equivocada.
  * Se baja menos de una pantalla por vuelta, porque Instagram tambien
    descarta del DOM lo que queda fuera de la vista.
  * Se sondea la fecha durante el recorrido, en una pestaña aparte, para
    cortar en cuanto se pasa el rango en vez de barrer el perfil entero.
  * Los comentarios se leen dentro de un panel ANCLADO, para no mezclar con
    las «publicaciones sugeridas» que Instagram enseña debajo.
  * Si una publicacion da cero comentarios se guarda la pagina para poder
    ver que cambio, en vez de adivinar.

Diferencia a favor de Instagram: publica la fecha exacta en el HTML
(<time datetime="...">), asi que no hay que interpretar «hace 3 h».
"""

from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Page

from ..core.limpieza import limpiar_autor, limpiar_texto
from ..core.modelos import Comentario, Publicacion
from ..core.rutas import CARPETA_CONFIG, CARPETA_DIAGNOSTICO
from .base import ExtractorRed, OpcionesExtraccion, Progreso
from .js_instagram import (
    JS_ALTURA_PAGINA,
    JS_ANCLAR_PANEL,
    JS_DATOS_PUBLICACION,
    JS_DESPLAZAR,
    JS_DESPLAZAR_PANEL,
    JS_ENLACES_PUBLICACIONES,
    JS_IR_A,
    JS_IR_AL_FONDO,
    JS_LEER_COMENTARIOS,
    JS_POSICION,
    JS_PULSAR_BOTONES,
    JS_SESION_INICIADA,
)


def _cargar_config() -> dict:
    with open(CARPETA_CONFIG / "instagram.json", "r", encoding="utf-8") as f:
        return json.load(f)


def _fecha_iso(valor: str) -> datetime | None:
    """Convierte '2026-08-20T14:32:00.000Z' a hora local."""
    if not valor:
        return None
    try:
        t = valor.replace("Z", "+00:00")
        d = datetime.fromisoformat(t)
        if d.tzinfo is not None:
            d = d.astimezone().replace(tzinfo=None)
        return d
    except ValueError:
        return None


class ExtractorInstagram(ExtractorRed):
    nombre = "instagram"
    etiqueta = "Instagram"
    url_inicio = "https://www.instagram.com/"
    implementado = True
    ayuda = (
        "Pega la URL del perfil, por ejemplo:\n"
        "  https://www.instagram.com/nombredeusuario/\n\n"
        "Necesitas haber iniciado sesion (boton 'Abrir navegador e iniciar sesion').\n"
        "Instagram limita mucho el ritmo: si ves avisos, baja el maximo de\n"
        "publicaciones y deja el navegador visible para resolverlos a mano."
    )

    def __init__(self) -> None:
        self.cfg = _cargar_config()

    # ------------------------------------------------------------------ sesion

    def sesion_iniciada(self, pagina: Page) -> bool:
        try:
            pagina.goto(self.url_inicio, wait_until="domcontentloaded", timeout=30_000)
            pagina.wait_for_timeout(2500)
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
            u = ("https://" + u.lstrip("/")) if "instagram.com" in u \
                else "https://www.instagram.com/" + u.strip("/")
        u = u.split("?")[0].rstrip("/")
        return u + "/"

    @staticmethod
    def _codigo_publicacion(url: str) -> str:
        """El codigo corto de la publicacion (lo que va tras /p/, /reel/ o /tv/)."""
        m = re.search(r"/(?:p|reel|tv)/([A-Za-z0-9_-]+)", url or "")
        return m.group(1) if m else ""

    @classmethod
    def _normalizar_url_publicacion(cls, href: str) -> str:
        """Deja la URL de la publicacion siempre en la misma forma.

        OJO con el nombre de usuario: dentro de un perfil, Instagram escribe
        los enlaces como /usuario/p/CODIGO/, no como /p/CODIGO/. Por eso hay
        que BUSCAR el tramo en la ruta, no exigir que empiece por el.
        Exigirlo hacia que se descartaran en silencio todas las publicaciones.
        """
        if not href or "instagram.com" not in href:
            return ""
        ruta = urlsplit(href).path
        # El codigo corto tiene al menos 5 caracteres; asi no confundimos
        # rutas como /reels/audio/ con una publicacion.
        m = re.search(r"/(p|reel|tv)/([A-Za-z0-9_-]{5,})", ruta)
        if not m:
            return ""
        return f"https://www.instagram.com/{m.group(1)}/{m.group(2)}/"

    @staticmethod
    def _tipo_publicacion(url: str) -> str:
        if "/reel/" in url:
            return "reel"
        if "/tv/" in url:
            return "video"
        return "publicacion"

    # ------------------------------------------------------ FASE 1: descubrir

    def descubrir_publicaciones(
        self, pagina: Page, opciones: OpcionesExtraccion, progreso: Progreso
    ) -> list[Publicacion]:
        url_perfil = self.normalizar_url_perfil(opciones.url_perfil)
        if not url_perfil:
            raise ValueError("Falta la URL del perfil de Instagram.")

        desde = opciones.desde or datetime(2010, 1, 1)
        hasta = opciones.hasta or datetime.now()
        encontradas: dict[str, Publicacion] = {}

        progreso.log(f"Abriendo el perfil: {url_perfil}")
        aux: Page | None = None
        try:
            aux = pagina.context.new_page()
        except Exception:
            progreso.log("   (sin pestaña auxiliar: ire mas lento)")
        try:
            self._recorrer_perfil(
                pagina, aux, url_perfil, encontradas, opciones, progreso, desde
            )
        finally:
            if aux is not None:
                try:
                    aux.close()
                except Exception:
                    pass

        # Comprobamos las fechas que falten (las sondas ya confirmaron varias)
        pendientes = [p for p in encontradas.values() if p.fecha is None]
        if opciones.verificar_fechas and pendientes and not progreso.cancelado():
            self._verificar_fechas(pagina, pendientes, progreso, desde, opciones)

        en_rango, sin_confirmar, fuera = [], [], []
        for pub in encontradas.values():
            if pub.fecha is None:
                pub.seleccionada = False
                if not pub.nota:
                    pub.nota = "Sin fecha - revisala antes de incluirla"
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
        sin_confirmar.sort(key=lambda p: p.url)
        tope = 300 if opciones.exhaustivo else 30
        return en_rango[: opciones.max_publicaciones] + sin_confirmar[:tope]

    def _recorrer_perfil(
        self,
        pagina: Page,
        aux: Page | None,
        url_perfil: str,
        encontradas: dict[str, Publicacion],
        opciones: OpcionesExtraccion,
        progreso: Progreso,
        desde: datetime,
    ) -> None:
        pagina.goto(url_perfil, wait_until="domcontentloaded", timeout=60_000)
        pagina.wait_for_timeout(3000)
        self._cerrar_estorbos(pagina)

        if "/accounts/login" in pagina.url:
            raise RuntimeError(
                "Instagram pidio iniciar sesion. Usa el boton "
                "'Abrir navegador e iniciar sesion' y vuelve a intentarlo."
            )

        try:
            alto = int(pagina.evaluate("() => window.innerHeight") or 900)
        except Exception:
            alto = 900
        paso = max(300, int(alto * 0.60))

        patrones = self.cfg["patrones_url_publicacion"]
        sin_nuevas = rondas_al_final = sondas = 0
        limite = time.monotonic() + max(1, opciones.minutos_por_seccion) * 60

        for ronda in range(1, opciones.max_desplazamientos + 1):
            if progreso.cancelado():
                return
            if (not opciones.exhaustivo and time.monotonic() > limite
                    and sondas >= 1):
                progreso.log("   Se agoto el tiempo asignado al recorrido.")
                return

            try:
                crudos = pagina.evaluate(JS_ENLACES_PUBLICACIONES, patrones)
            except Exception as e:
                progreso.log(f"   Aviso al leer la pagina: {str(e)[:90]}")
                crudos = []

            # Contamos cuantos enlaces vemos y cuantos reconocemos. Si la app
            # ve enlaces pero no reconoce ninguno, el problema esta en la
            # normalizacion, no en el recorrido: sin esto no se distingue.
            rechazados = 0
            antes = len(encontradas)
            for item in crudos:
                url = self._normalizar_url_publicacion(item.get("href", ""))
                if not url:
                    rechazados += 1
                    continue
                if url in encontradas:
                    continue
                encontradas[url] = Publicacion(
                    url=url,
                    red=self.nombre,
                    perfil=url_perfil,
                    fecha=_fecha_iso(item.get("fecha_iso", "")),
                    tipo=self._tipo_publicacion(url),
                    texto=(item.get("texto") or "")[:300],
                    seccion="Perfil",
                )
            nuevas = len(encontradas) - antes
            sin_nuevas = 0 if nuevas else sin_nuevas + 1

            if ronda == 1 or (ronda == 5 and not encontradas):
                progreso.log(
                    f"   Vuelta {ronda}: {len(crudos)} enlaces con pinta de "
                    f"publicacion, {rechazados} descartados, "
                    f"{len(encontradas)} reconocidos."
                )
                if crudos and not encontradas:
                    ejemplos = [c.get("href", "")[:80] for c in crudos[:3]]
                    progreso.log(
                        "   ⚠ Veo enlaces pero no reconozco ninguno. Ejemplos:\n"
                        + "\n".join(f"      {e}" for e in ejemplos)
                    )

            progreso.paso(
                min(len(encontradas), opciones.max_publicaciones),
                opciones.max_publicaciones,
                f"Explorando el perfil… {len(encontradas)} publicaciones "
                f"(vuelta {ronda})",
            )

            # SONDA: la cuadricula va de lo mas nuevo a lo mas viejo, pero no
            # muestra fechas. Preguntamos la de la ultima descubierta; cuando
            # se sale del rango, todo lo que queda debajo tambien.
            if aux is not None and ronda % 5 == 0 and nuevas:
                ultima = list(encontradas.values())[-1]
                fecha = self._sonda_fecha(aux, ultima.url)
                sondas += 1
                if fecha:
                    ultima.fecha = fecha
                    progreso.log(
                        f"   Sonda {sondas}: por la publicacion del "
                        f"{fecha:%d/%m/%Y} ({len(encontradas)} vistas)"
                    )
                    if fecha < desde - timedelta(days=1):
                        progreso.log("   Ya pasamos el rango de fechas. Fin del recorrido.")
                        return

            if len([p for p in encontradas.values()
                    if p.fecha and p.fecha >= desde]) >= opciones.max_publicaciones:
                progreso.log("   Se alcanzo el maximo de publicaciones configurado.")
                return

            try:
                estado = pagina.evaluate(JS_DESPLAZAR, paso) or {}
            except Exception:
                estado = {}
            pagina.wait_for_timeout(random.randint(700, 1200))

            if estado.get("al_final") or not estado.get("se_movio"):
                altura_antes = estado.get("altura", 0)
                try:  # rebote: despierta la carga perezosa
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
                        return
            else:
                rondas_al_final = 0

            if sin_nuevas >= 3:
                pagina.wait_for_timeout(1500)
            if sin_nuevas >= (45 if opciones.exhaustivo else 25):
                progreso.log("   No aparecen publicaciones nuevas.")
                if not encontradas:
                    ruta = self.guardar_diagnostico(pagina, "instagram_perfil_vacio")
                    progreso.log(
                        "   ⚠ No se reconocio NINGUNA publicacion. Guarde la "
                        f"pagina para revisarla en:\n      {ruta}"
                    )
                return

    # ------------------------------------------------------------- fechas

    def _sonda_fecha(self, aux: Page, url: str) -> datetime | None:
        """Lee la fecha exacta en una pestaña aparte (no perdemos el scroll)."""
        codigo = self._codigo_publicacion(url)
        try:
            aux.goto(url, wait_until="domcontentloaded", timeout=30_000)
            for intento in range(3):
                aux.wait_for_timeout(400 if intento == 0 else 600)
                datos = aux.evaluate(JS_DATOS_PUBLICACION, codigo) or {}
                if datos.get("fecha"):
                    return _fecha_iso(datos["fecha"])
        except Exception:
            return None
        return None

    def _verificar_fechas(
        self,
        pagina: Page,
        publicaciones: list[Publicacion],
        progreso: Progreso,
        desde: datetime,
        opciones: OpcionesExtraccion,
    ) -> None:
        total = len(publicaciones)
        progreso.log(f"Comprobando la fecha de {total} publicaciones…")
        seguidas_antiguas = confirmadas = 0

        for i, pub in enumerate(publicaciones, start=1):
            if progreso.cancelado():
                progreso.log("Comprobacion detenida por el usuario.")
                return
            progreso.paso(i, total, f"Comprobando fecha {i} de {total}")
            codigo = self._codigo_publicacion(pub.url)
            try:
                pagina.goto(pub.url, wait_until="domcontentloaded", timeout=45_000)
                datos = {}
                for intento in range(4):
                    pagina.wait_for_timeout(350 if intento == 0 else 550)
                    datos = pagina.evaluate(JS_DATOS_PUBLICACION, codigo) or {}
                    if datos.get("fecha"):
                        break
                fecha = _fecha_iso(datos.get("fecha", ""))
                if fecha:
                    pub.fecha = fecha
                    pub.fecha_aproximada = False
                    pub.nota = ""
                    confirmadas += 1
                else:
                    pub.nota = "No se pudo leer la fecha de esta publicacion"
                if datos.get("texto") and not pub.texto:
                    pub.texto = datos["texto"]

                if fecha and not opciones.exhaustivo:
                    seguidas_antiguas = seguidas_antiguas + 1 if fecha < desde else 0
                    if seguidas_antiguas >= 20:
                        progreso.log(
                            "   Ya solo salen publicaciones anteriores al rango; "
                            "dejo de comprobar."
                        )
                        return
            except Exception as e:
                pub.nota = f"No se pudo comprobar la fecha: {str(e)[:80]}"
            pagina.wait_for_timeout(random.randint(250, 500))

        progreso.log(f"Fechas confirmadas: {confirmadas} de {total}.")

    # ---------------------------------------------------- FASE 2: comentarios

    def extraer_comentarios(
        self,
        pagina: Page,
        publicacion: Publicacion,
        opciones: OpcionesExtraccion,
        progreso: Progreso,
    ) -> list[Comentario]:
        progreso.log(f"Abriendo publicacion: {publicacion.url}")
        codigo = self._codigo_publicacion(publicacion.url)
        pagina.goto(publicacion.url, wait_until="domcontentloaded", timeout=60_000)
        pagina.wait_for_timeout(2500)
        self._cerrar_estorbos(pagina)

        fecha_publicacion_iso = ""
        try:
            datos = pagina.evaluate(JS_DATOS_PUBLICACION, codigo) or {}
            fecha_publicacion_iso = datos.get("fecha", "") or ""
            exacta = _fecha_iso(fecha_publicacion_iso)
            if exacta:
                publicacion.fecha = exacta
            if datos.get("texto") and not publicacion.texto:
                publicacion.texto = datos["texto"]
            if datos.get("anunciados"):
                progreso.log(f"   Instagram anuncia: {datos['anunciados']}")
        except Exception:
            exacta = None

        # Red de seguridad del modo automatico
        if (opciones.verificar_rango_al_extraer and exacta and opciones.desde
                and opciones.hasta
                and not (opciones.desde <= exacta <= opciones.hasta)):
            publicacion.estado = "omitida"
            publicacion.nota = f"Fuera del rango (fecha real {exacta:%d/%m/%Y})"
            progreso.log(f"   ↷ Omitida: es del {exacta:%d/%m/%Y}.")
            return []

        acumulados: dict[str, dict] = {}
        sin_nuevos = 0
        anclado_avisado = False

        for vuelta in range(1, 81):
            if progreso.cancelado():
                break

            pulsados = 0
            for clave, tope in (
                ("boton_mas_comentarios", 10),
                ("boton_ver_respuestas", 10),
                ("boton_ver_mas_texto", 20),
            ):
                try:
                    pulsados += pagina.evaluate(
                        JS_PULSAR_BOTONES, [self.cfg[clave], tope]) or 0
                except Exception:
                    pass
            pagina.wait_for_timeout(random.randint(700, 1200))

            # Re-anclamos cada vuelta: al principio no hay panel que anclar y
            # despues Instagram reemplaza nodos al cargar mas comentarios.
            try:
                ancla = pagina.evaluate(JS_ANCLAR_PANEL) or {}
            except Exception:
                ancla = {}
            if ancla.get("ok") and not anclado_avisado:
                anclado_avisado = True
                progreso.log("   Panel de comentarios anclado a esta publicacion.")

            crudos, _ = self._leer_comentarios_crudos(
                pagina, codigo, fecha_publicacion_iso)
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
                if not estado.get("encontrado"):
                    pagina.evaluate(JS_DESPLAZAR, 800)
                    movido = True
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
                    fecha=_fecha_iso(c.get("fecha", "")),
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
            ruta = self.guardar_diagnostico(pagina, "instagram_sin_comentarios")
            progreso.log(
                "⚠ No se encontro ningun comentario. Guarde la pagina en:\n"
                f"   {ruta}"
            )
        progreso.log(f"Comentarios de texto extraidos: {len(comentarios)}")
        return comentarios

    # -------------------------------------------------------------- auxiliares

    def _leer_comentarios_crudos(
        self, pagina: Page, codigo: str, fecha_publicacion: str
    ) -> tuple[list[dict], str]:
        try:
            datos = pagina.evaluate(
                JS_LEER_COMENTARIOS, [codigo, fecha_publicacion])
        except Exception:
            return [], "error"
        if isinstance(datos, dict):
            return datos.get("comentarios") or [], datos.get("modo", "")
        return datos or [], "instagram"

    def _cerrar_estorbos(self, pagina: Page) -> None:
        """Cierra el aviso de cookies y las ventanas emergentes.

        En cookies elegimos siempre la opcion que menos datos comparte.
        """
        try:
            pagina.evaluate(
                JS_PULSAR_BOTONES,
                ["(rechazar|decline|solo permitir cookies esenciales|"
                 "permitir cookies necesarias)", 2],
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

    def guardar_diagnostico(self, pagina: Page, etiqueta: str = "instagram") -> Path:
        marca = datetime.now().strftime("%Y%m%d_%H%M%S")
        destino = CARPETA_DIAGNOSTICO / f"{etiqueta}_{marca}.html"
        try:
            destino.write_text(pagina.content(), encoding="utf-8", errors="ignore")
            pagina.screenshot(
                path=str(CARPETA_DIAGNOSTICO / f"{etiqueta}_{marca}.png"))
        except Exception:
            pass
        return destino
