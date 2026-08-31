"""Extractor de Facebook.

Funciona en dos fases:

  FASE 1 - Descubrir publicaciones
      Abre el perfil, baja por el muro y va anotando las publicaciones
      (post, foto, video, reel) junto con su fecha, hasta salirse del
      rango de fechas que pediste.

  FASE 2 - Extraer comentarios
      Abre cada publicacion seleccionada, cambia el orden a "Todos los
      comentarios", pulsa "Ver mas comentarios" / "Ver mas respuestas"
      hasta que no queden, y lee el texto de cada comentario.

De cada comentario guardamos SOLO texto y emojis. Los que son unicamente
un GIF, sticker o imagen se descartan.
"""

from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.sync_api import Page

from ..core.fechas import desde_epoch, interpretar_fecha
from ..core.limpieza import limpiar_autor, limpiar_texto
from ..core.modelos import Comentario, Publicacion
from ..core.rutas import CARPETA_CONFIG, CARPETA_DIAGNOSTICO
from .base import ExtractorRed, OpcionesExtraccion, Progreso
from .js_facebook import (
    JS_ABRIR_COMENTARIOS,
    JS_ABRIR_ORDEN,
    JS_ALTURA_PAGINA,
    JS_ANCLAR_PANEL,
    JS_COMENTARIOS_ANUNCIADOS,
    JS_DATOS_PUBLICACION,
    JS_DESPLAZAR,
    JS_DESPLAZAR_PANEL,
    JS_ELEGIR_OPCION_MENU,
    JS_IR_A,
    JS_IR_AL_FONDO,
    JS_POSICION,
    JS_ENLACES_PUBLICACIONES,
    JS_LEER_COMENTARIOS,
    JS_PULSAR_BOTONES,
)


def _cargar_config() -> dict:
    ruta = CARPETA_CONFIG / "facebook.json"
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


class ExtractorFacebook(ExtractorRed):
    nombre = "facebook"
    etiqueta = "Facebook"
    url_inicio = "https://www.facebook.com/"
    dominios = ("facebook.com", "fb.com", "fb.watch")
    implementado = True
    ayuda = (
        "Pega la URL del perfil o pagina, por ejemplo:\n"
        "  https://www.facebook.com/nombredelapagina\n"
        "  https://www.facebook.com/profile.php?id=100001234567890\n\n"
        "Necesitas haber iniciado sesion (boton 'Abrir navegador e iniciar sesion').\n"
        "Solo se puede extraer de contenido que tu cuenta pueda ver."
    )

    def __init__(self) -> None:
        self.cfg = _cargar_config()

    # ------------------------------------------------------------------ sesion

    def sesion_iniciada(self, pagina: Page) -> bool:
        """Comprueba si el navegador ya tiene la sesion de Facebook abierta."""
        try:
            pagina.goto(
                "https://www.facebook.com/me",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            pagina.wait_for_timeout(2500)
            url = pagina.url.lower()
            if "login" in url or "checkpoint" in url or "recover" in url:
                return False
            # Si sigue apareciendo el formulario de correo/contraseña, no hay sesion
            if pagina.locator('input[name="email"]').count() > 0:
                visible = pagina.locator('input[name="email"]').first.is_visible()
                if visible:
                    return False
            return True
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
            if "facebook.com" in u:
                u = "https://" + u.lstrip("/")
            else:
                u = "https://www.facebook.com/" + u.strip("/")
        # Forzamos www para que la version sea siempre la de escritorio
        u = u.replace("://m.facebook.com", "://www.facebook.com")
        u = u.replace("://mbasic.facebook.com", "://www.facebook.com")
        u = u.replace("://web.facebook.com", "://www.facebook.com")
        return u.split("?")[0] if "profile.php" not in u else u

    # ------------------------------------------------------ FASE 1: descubrir

    def descubrir_publicaciones(
        self, pagina: Page, opciones: OpcionesExtraccion, progreso: Progreso
    ) -> list[Publicacion]:
        url_perfil = self.normalizar_url_perfil(opciones.url_perfil)
        if not url_perfil:
            raise ValueError("Falta la URL del perfil de Facebook.")

        desde = opciones.desde or datetime(2004, 1, 1)
        hasta = opciones.hasta or datetime.now()
        encontradas: dict[str, Publicacion] = {}

        # Recorremos varias secciones del perfil, no solo la linea de tiempo.
        # Motivo: Facebook agrupa los reels, videos y fotos en pestañas propias
        # y la linea de tiempo NO los lista todos. Si el perfil publica sobre
        # todo reels, mirando solo el muro siempre faltarian publicaciones.
        secciones = self._secciones_del_perfil(url_perfil, opciones)
        progreso.log(f"Voy a recorrer {len(secciones)} secciones del perfil.")

        for indice, (nombre, url_seccion) in enumerate(secciones, start=1):
            if progreso.cancelado():
                progreso.log("Busqueda cancelada por el usuario.")
                break

            antes_seccion = len(encontradas)
            progreso.log(f"── Sección {indice}/{len(secciones)}: {nombre} ──")
            try:
                self._recorrer_seccion(
                    pagina, url_seccion, nombre, encontradas,
                    url_perfil, opciones, progreso, desde, hasta,
                )
            except Exception as e:
                progreso.log(f"   No se pudo recorrer «{nombre}»: {str(e)[:120]}")
                continue

            nuevas = len(encontradas) - antes_seccion
            progreso.log(
                f"   «{nombre}» aporto {nuevas} publicaciones nuevas "
                f"(total acumulado: {len(encontradas)})."
            )

        # Antes de filtrar, corregimos las fechas abriendo cada publicacion.
        # Es el paso que evita que se cuelen fechas leidas de un comentario.
        candidatas = list(encontradas.values())
        if opciones.verificar_fechas and candidatas and not progreso.cancelado():

            def merece_comprobar(p: Publicacion) -> bool:
                if p.fecha is None:
                    return True
                if p.fecha_aproximada:
                    # La fecha real es SIEMPRE anterior o igual a la aproximada
                    # (un comentario va despues del post). Asi que solo podemos
                    # descartarla si incluso la aproximada ya es anterior al
                    # inicio del rango. Si es posterior a `hasta` hay que
                    # comprobarla igual: el post puede ser perfectamente valido
                    # y tener un comentario reciente.
                    return p.fecha >= desde
                return (desde - timedelta(days=2)) <= p.fecha <= (hasta + timedelta(days=2))

            a_comprobar = [p for p in candidatas if merece_comprobar(p)]
            tope = (
                len(a_comprobar) if opciones.exhaustivo
                else max(opciones.max_publicaciones * 3, 60)
            )
            if len(a_comprobar) > tope:
                progreso.log(
                    f"   Hay {len(a_comprobar)} fechas por comprobar; me quedo "
                    f"con las {tope} primeras (las mas recientes del perfil)."
                )
                a_comprobar = a_comprobar[:tope]
            if a_comprobar:
                self.verificar_fechas(
                    pagina, a_comprobar, progreso, desde,
                    saltar_secciones=not opciones.exhaustivo,
                )

        # Filtramos por rango de fechas.
        #
        # Regla de oro: una fecha APROXIMADA nunca cuenta como dentro del rango.
        # Una publicacion vieja con un comentario reciente tendria la fecha del
        # comentario (que si cae en el rango) y se colaria como si fuera nueva.
        # Solo entran las que tienen fecha CONFIRMADA.
        en_rango: list[Publicacion] = []
        sin_confirmar: list[Publicacion] = []
        fuera_de_rango: list[Publicacion] = []
        for pub in encontradas.values():
            if pub.fecha is None:
                pub.seleccionada = False
                pub.nota = "Sin fecha - no se pudo leer la fecha real"
                sin_confirmar.append(pub)
            elif pub.fecha_aproximada:
                pub.seleccionada = False
                pub.nota = "Fecha SIN CONFIRMAR - podria ser mucho mas antigua"
                sin_confirmar.append(pub)
            elif self._en_rango(pub, desde, hasta):
                pub.seleccionada = True
                en_rango.append(pub)
            else:
                fuera_de_rango.append(pub)

        # Contamos todo lo visto para que sea facil detectar si falta algo
        progreso.log(
            f"Publicaciones vistas: {len(encontradas)} "
            f"→ {len(en_rango)} dentro del rango (fecha confirmada), "
            f"{len(fuera_de_rango)} fuera de rango, "
            f"{len(sin_confirmar)} sin fecha confirmada."
        )
        if fuera_de_rango:
            fechas = sorted(p.fecha for p in fuera_de_rango)
            progreso.log(
                f"   Las descartadas por fecha van del {fechas[0]:%d/%m/%Y} "
                f"al {fechas[-1]:%d/%m/%Y}."
            )

        en_rango.sort(key=lambda p: p.fecha or datetime.min, reverse=True)
        if len(en_rango) > opciones.max_publicaciones:
            progreso.log(
                f"⚠ Se encontraron {len(en_rango)} publicaciones en el rango pero el "
                f"limite esta en {opciones.max_publicaciones}. Se quedan las mas "
                "recientes; sube «Maximo de publicaciones» para verlas todas."
            )

        # Las de fecha dudosa van al final y DESMARCADAS. Enseñamos solo unas
        # pocas: al recorrer las pestañas sale el historial entero del perfil y
        # llenar la tabla con cientos de videos antiguos solo estorba.
        sin_confirmar.sort(key=lambda p: p.fecha or datetime.min, reverse=True)
        # En modo exhaustivo enseñamos muchas mas dudosas: el objetivo ahi es
        # que no se te escape nada, aunque tengas que revisar mas a mano.
        TOPE_DUDOSAS = 300 if opciones.exhaustivo else 30
        if len(sin_confirmar) > TOPE_DUDOSAS:
            progreso.log(
                f"   {len(sin_confirmar)} publicaciones sin fecha confirmada "
                f"(casi todas antiguas). Muestro solo las {TOPE_DUDOSAS} mas recientes."
            )
        resultado = (
            en_rango[: opciones.max_publicaciones] + sin_confirmar[:TOPE_DUDOSAS]
        )

        progreso.log(
            f"Listo: {len(en_rango)} publicaciones marcadas, todas con fecha "
            f"confirmada entre {desde:%d/%m/%Y} y {hasta:%d/%m/%Y}."
        )
        if sin_confirmar:
            progreso.log(
                "Las que aparecen desmarcadas al final tienen la fecha sin "
                "confirmar: reviselas antes de incluirlas."
            )
        if not resultado:
            progreso.log(
                "No se encontro nada. Prueba a: 1) ampliar el rango de fechas, "
                "2) confirmar que la URL es de un perfil o pagina publica, "
                "3) usar la pestaña 'Pegar URLs a mano'."
            )
        return resultado

    def _secciones_del_perfil(
        self, url_perfil: str, opciones: OpcionesExtraccion
    ) -> list[tuple[str, str]]:
        """Devuelve las paginas del perfil que hay que recorrer.

        La linea de tiempo no lista todo: Facebook manda los reels, los videos
        y las fotos a sus propias pestañas. Recorriendolas todas y juntando el
        resultado conseguimos la lista completa (las repetidas se descartan
        solas, porque la URL de la publicacion es la clave).
        """
        secciones: list[tuple[str, str]] = [("Linea de tiempo", url_perfil)]
        if not opciones.buscar_en_pestanas:
            return secciones

        if "profile.php" in url_perfil:
            # Perfiles con id numerico: las pestañas van por parametro
            separador = "&" if "?" in url_perfil else "?"
            for nombre, clave in (
                ("Reels", "reels_tab"),
                ("Videos", "videos"),
                ("Fotos", "photos"),
            ):
                secciones.append((nombre, f"{url_perfil}{separador}sk={clave}"))
        else:
            base = url_perfil.rstrip("/")
            for nombre, ruta in (
                ("Reels", "reels"),
                ("Videos", "videos"),
                ("Fotos", "photos"),
            ):
                secciones.append((nombre, f"{base}/{ruta}"))
        return secciones

    def _sonda_fecha(self, aux: Page, url: str) -> datetime | None:
        """Lee la fecha exacta de una publicacion en una pestaña APARTE.

        Se usa una pestaña auxiliar a proposito: si navegaramos con la pestaña
        principal perderiamos el punto por el que ibamos bajando la seccion y
        habria que empezar de cero.
        """
        identificador = self._identificador_publicacion(url)
        try:
            aux.goto(url, wait_until="domcontentloaded", timeout=30_000)
            for intento in range(3):
                aux.wait_for_timeout(300 if intento == 0 else 500)
                datos = aux.evaluate(JS_DATOS_PUBLICACION, identificador) or {}
                if datos.get("creacion"):
                    return desde_epoch(datos["creacion"])
        except Exception:
            return None
        return None

    def _recorrer_seccion(
        self,
        pagina: Page,
        url_seccion: str,
        nombre: str,
        encontradas: dict[str, Publicacion],
        url_perfil: str,
        opciones: OpcionesExtraccion,
        progreso: Progreso,
        desde: datetime,
        hasta: datetime,
    ) -> None:
        """Recorre una seccion del perfil, con pestaña auxiliar para las sondas.

        La pestaña auxiliar sirve para ir preguntando fechas SIN perder el punto
        por el que vamos bajando. Es la optimizacion clave: las pestañas van de
        lo mas nuevo a lo mas viejo, pero las rejillas de miniaturas no muestran
        fechas, asi que sin sondas no habia forma de saber cuando ya habiamos
        pasado el rango… y acabábamos recorriendo miles de publicaciones para
        quedarnos con veinte.
        """
        aux: Page | None = None
        try:
            aux = pagina.context.new_page()
        except Exception:
            progreso.log("   (no se pudo abrir pestaña auxiliar; ire sin sondas)")
        try:
            self._recorrer_seccion_interna(
                pagina, aux, url_seccion, nombre, encontradas,
                url_perfil, opciones, progreso, desde, hasta,
            )
        finally:
            if aux is not None:
                try:
                    aux.close()
                except Exception:
                    pass

    def _recorrer_seccion_interna(
        self,
        pagina: Page,
        aux: Page | None,
        url_seccion: str,
        nombre: str,
        encontradas: dict[str, Publicacion],
        url_perfil: str,
        opciones: OpcionesExtraccion,
        progreso: Progreso,
        desde: datetime,
        hasta: datetime,
    ) -> None:
        """Abre una seccion del perfil y baja recogiendo enlaces."""
        pagina.goto(url_seccion, wait_until="domcontentloaded", timeout=60_000)
        pagina.wait_for_timeout(2500)
        self._cerrar_estorbos(pagina)

        if "login" in pagina.url.lower():
            raise RuntimeError(
                "Facebook pidio iniciar sesion. Usa el boton "
                "'Abrir navegador e iniciar sesion' y vuelve a intentarlo."
            )

        patrones = self.cfg["patrones_url_publicacion"]

        # Cuanto bajamos en cada vuelta. Es CLAVE que sea MENOS de una pantalla:
        # Facebook borra del DOM las publicaciones que quedan fuera de la vista,
        # asi que si saltaramos dos pantallas de golpe, los posts que quedan en
        # medio desaparecerian sin que nos diera tiempo a leerlos. Con un 60% de
        # la ventana siempre hay solape y no se escapa ninguno.
        try:
            alto_ventana = int(pagina.evaluate("() => window.innerHeight") or 900)
        except Exception:
            alto_ventana = 900
        paso_scroll = max(300, int(alto_ventana * 0.60))

        rondas_sin_nuevas = 0
        rondas_sin_recientes = 0
        rondas_al_final = 0
        limite = time.monotonic() + max(1, opciones.minutos_por_seccion) * 60

        sondas_hechas = 0

        for ronda in range(1, opciones.max_desplazamientos + 1):
            if progreso.cancelado():
                return
            # El tope de tiempo solo entra en juego cuando ya llevamos un rato
            # sin ver nada del rango de fechas. Mientras sigan apareciendo
            # publicaciones que nos interesan NO cortamos por reloj: el tope
            # esta para no recorrer diez años de historial, no para dejarnos
            # publicaciones validas fuera.
            if (not opciones.exhaustivo
                    and time.monotonic() > limite
                    and rondas_sin_recientes >= 5):
                progreso.log(
                    f"   «{nombre}»: se agoto el tiempo asignado "
                    f"({opciones.minutos_por_seccion} min) y ya no aparecen "
                    "publicaciones del rango. Paso a la siguiente."
                )
                return

            try:
                crudos = pagina.evaluate(JS_ENLACES_PUBLICACIONES, patrones)
            except Exception as e:
                progreso.log(f"   Aviso al leer la pagina: {str(e)[:100]}")
                crudos = []

            antes = len(encontradas)
            hubo_reciente = self._registrar_enlaces(
                crudos, encontradas, url_perfil, desde, nombre
            )
            nuevas = len(encontradas) - antes

            progreso.paso(
                min(len(encontradas), opciones.max_publicaciones),
                opciones.max_publicaciones,
                f"{nombre}: {len(encontradas)} publicaciones vistas (vuelta {ronda})",
            )

            rondas_sin_nuevas = 0 if nuevas else rondas_sin_nuevas + 1
            rondas_sin_recientes = 0 if hubo_reciente else rondas_sin_recientes + 1

            # SONDA: cada pocas vueltas preguntamos la fecha real de la ultima
            # publicacion descubierta en esta seccion. Como la seccion va de lo
            # mas nuevo a lo mas viejo, esa es la mas antigua vista hasta ahora:
            # en cuanto se sale del rango, todo lo que quede debajo tambien.
            if aux is not None and ronda % 6 == 0 and nuevas:
                de_seccion = [
                    p for p in encontradas.values() if p.seccion == nombre
                ]
                if de_seccion:
                    ultima = de_seccion[-1]
                    fecha = self._sonda_fecha(aux, ultima.url)
                    sondas_hechas += 1
                    if fecha:
                        ultima.fecha = fecha
                        ultima.fecha_aproximada = False
                        progreso.log(
                            f"   Sonda {sondas_hechas}: por la publicacion "
                            f"del {fecha:%d/%m/%Y} ({len(de_seccion)} vistas)"
                        )
                        if fecha < desde - timedelta(days=1):
                            progreso.log(
                                f"   «{nombre}»: ya pasamos el rango de fechas. "
                                "Fin de la seccion."
                            )
                            return

            # Ya bajamos lo suficiente: solo aparecen publicaciones mas viejas
            # que la fecha inicial durante muchas vueltas seguidas.
            #
            # El margen de 2 dias existe porque algunas fechas son aproximadas
            # (salen de la hora de un comentario, que es POSTERIOR al post).
            # Sin margen pararíamos antes de tiempo y dejariamos fuera posts validos.
            # OJO: solo miramos las fechas de ESTA seccion. Si usaramos todas
            # las encontradas, al entrar en la pestaña Reels ya arrastrariamos
            # las fechas viejas de la linea de tiempo y daríamos la seccion por
            # agotada nada mas empezar, dejandonos publicaciones del rango.
            con_fecha = [
                p for p in encontradas.values() if p.fecha and p.seccion == nombre
            ]
            umbral_sin_recientes = 40 if opciones.exhaustivo else 15
            if con_fecha and rondas_sin_recientes >= umbral_sin_recientes and ronda >= 12:
                if min(p.fecha for p in con_fecha) < desde - timedelta(days=2):
                    progreso.log(
                        f"   «{nombre}»: alcanzadas publicaciones anteriores al rango."
                    )
                    return

            if len([p for p in encontradas.values()
                    if self._en_rango(p, desde, hasta)]) >= opciones.max_publicaciones:
                progreso.log("   Se alcanzo el maximo de publicaciones configurado.")
                return

            # Bajamos con JavaScript (fiable) en vez de con la rueda del raton
            try:
                estado = pagina.evaluate(JS_DESPLAZAR, paso_scroll)
            except Exception:
                estado = {"al_final": False, "se_movio": True, "altura": 0}
            pagina.wait_for_timeout(random.randint(650, 1100))

            # Si llegamos al fondo de lo cargado, esperamos a que Facebook traiga
            # mas contenido. Solo damos la seccion por terminada si la pagina deja
            # de crecer varias veces seguidas.
            if estado.get("al_final") or not estado.get("se_movio"):
                altura_antes = estado.get("altura", 0)
                # "Rebote": subimos un poco y volvemos al fondo. Si ya estamos
                # abajo del todo, scrollBy no mueve nada y no se dispara ningun
                # evento nuevo, asi que el cargador perezoso de Facebook se
                # queda dormido y no trae mas publicaciones. Este vaiven es lo
                # que hace una persona y despierta la carga.
                try:
                    y = int(pagina.evaluate(JS_POSICION) or 0)
                    pagina.evaluate(JS_IR_A, max(0, y - 700))
                    pagina.wait_for_timeout(500)
                    pagina.evaluate(JS_IR_AL_FONDO)
                except Exception:
                    pass
                pagina.wait_for_timeout(2500)

                try:
                    altura_ahora = pagina.evaluate(JS_ALTURA_PAGINA)
                except Exception:
                    altura_ahora = altura_antes
                if altura_ahora > altura_antes + 200:
                    rondas_al_final = 0          # sigue cargando, seguimos
                else:
                    rondas_al_final += 1
                    if rondas_al_final >= 4:
                        progreso.log(f"   «{nombre}»: se llego al final.")
                        return
            else:
                rondas_al_final = 0

            # Nada nuevo puede significar que aun esta cargando, no que se acabo
            if rondas_sin_nuevas >= 3:
                pagina.wait_for_timeout(1500)
            if rondas_sin_nuevas >= (45 if opciones.exhaustivo else 25):
                progreso.log(f"   «{nombre}»: no aparecen publicaciones nuevas.")
                return

    def _registrar_enlaces(
        self,
        crudos: list[dict],
        encontradas: dict[str, Publicacion],
        url_perfil: str,
        desde: datetime,
        seccion: str = "",
    ) -> bool:
        """Convierte los enlaces crudos en publicaciones. Devuelve True si vio
        alguna publicacion mas nueva que `desde` (sirve para saber cuando parar).

        OJO con las fechas: dentro de cada publicacion del muro tambien hay
        enlaces de COMENTARIOS ("15 h", "2 dias") que apuntan a la misma URL.
        Si tomaramos esa hora como fecha de la publicacion, todas saldrian
        corridas hacia adelante. Por eso marcamos esas fechas como aproximadas
        y luego se corrigen abriendo la publicacion.
        """
        hubo_reciente = False
        for item in crudos:
            href = item.get("href", "")
            url = self._normalizar_url_publicacion(href)
            if not url:
                continue

            es_de_comentario = self._enlace_de_comentario(href)
            fecha = self._fecha_desde_enlace(item)
            tipo = self._tipo_publicacion(url)
            texto = self._texto_del_bloque(item.get("cuerpo", ""))

            existente = encontradas.get(url)
            if existente:
                # Completamos lo que faltaba. Una fecha fiable siempre gana
                # a una aproximada.
                if fecha is not None and (
                    existente.fecha is None
                    or (existente.fecha_aproximada and not es_de_comentario)
                ):
                    existente.fecha = fecha
                    existente.fecha_aproximada = es_de_comentario
                if not existente.texto and texto:
                    existente.texto = texto
            else:
                encontradas[url] = Publicacion(
                    url=url,
                    red=self.nombre,
                    perfil=url_perfil,
                    fecha=fecha,
                    tipo=tipo,
                    texto=texto,
                    fecha_aproximada=bool(fecha) and es_de_comentario,
                    seccion=seccion,
                )

            if fecha and fecha >= desde:
                hubo_reciente = True
        return hubo_reciente

    def verificar_fechas(
        self,
        pagina: Page,
        publicaciones: list[Publicacion],
        progreso: Progreso,
        desde: datetime | None = None,
        saltar_secciones: bool = True,
    ) -> None:
        """Abre cada publicacion y lee su fecha EXACTA y su texto real.

        Facebook incrusta en el HTML de cada publicacion un campo
        "creation_time" con la fecha exacta en formato Unix. Esa es la unica
        fuente de fecha realmente fiable, y de paso obtenemos el texto del post
        (en el muro lo que se veia era el comentario destacado, no el post).
        """
        total = len(publicaciones)
        progreso.log(
            f"Comprobando la fecha real de {total} publicaciones "
            "(se abre cada una; puedes detenerlo cuando quieras)…"
        )
        corregidas = 0
        seguidas_antiguas = 0
        comprobadas = 0
        ambiguas = 0

        seccion_actual = publicaciones[0].seccion if publicaciones else ""
        i = 0
        while i < total:
            pub = publicaciones[i]
            i += 1
            if progreso.cancelado():
                progreso.log("Comprobacion de fechas detenida por el usuario.")
                break

            # Cada seccion (Linea de tiempo, Reels, Videos…) va ordenada por su
            # cuenta. Al cambiar de seccion hay que reiniciar el contador de
            # "antiguas seguidas": si no, al terminar la primera se daria todo
            # por acabado y nunca se llegaria a las recientes de las demas.
            if pub.seccion != seccion_actual:
                seccion_actual = pub.seccion
                seguidas_antiguas = 0

            progreso.paso(i, total, f"Comprobando fecha {i} de {total}")
            try:
                pagina.goto(pub.url, wait_until="domcontentloaded", timeout=45_000)

                # En vez de esperar un tiempo fijo, preguntamos enseguida y solo
                # insistimos si aun no esta. La fecha suele venir ya en el HTML
                # inicial, asi que casi siempre acertamos al primer intento.
                identificador = self._identificador_publicacion(pub.url)
                datos = {}
                for intento in range(4):
                    pagina.wait_for_timeout(250 if intento == 0 else 450)
                    try:
                        datos = pagina.evaluate(
                            JS_DATOS_PUBLICACION, identificador) or {}
                    except Exception:
                        datos = {}
                    if datos.get("creacion"):
                        break

                exacta = desde_epoch(datos.get("creacion")) if datos.get("creacion") else None
                comprobadas += 1
                if exacta is None and (datos.get("fechas_en_pagina") or 0) > 1:
                    ambiguas += 1
                if exacta:
                    if pub.fecha is None or abs((exacta - pub.fecha).total_seconds()) > 3600:
                        corregidas += 1
                    pub.fecha = exacta
                    pub.fecha_aproximada = False
                    pub.nota = ""
                else:
                    pub.nota = (
                        "Fecha ambigua: la pagina traia varias y ninguna es "
                        "claramente de esta publicacion"
                        if (datos.get("fechas_en_pagina") or 0) > 1
                        else "No se pudo leer la fecha exacta"
                    )

                if datos.get("texto"):
                    pub.texto = datos["texto"]

                # Dentro de una seccion el orden es de lo mas nuevo a lo mas
                # viejo. Si encadenamos varias anteriores al rango, el resto de
                # ESA seccion sera aun mas antiguo: la saltamos entera y pasamos
                # a la siguiente (no abandonamos la comprobacion por completo).
                if desde and exacta and saltar_secciones:
                    # 20 seguidas, no 12: las secciones no siempre van en orden
                    # perfecto (publicaciones fijadas arriba, reordenaciones de
                    # Facebook) y con un umbral corto se saltaban publicaciones
                    # validas que venian despues.
                    seguidas_antiguas = seguidas_antiguas + 1 if exacta < desde else 0
                    if seguidas_antiguas >= 20:
                        saltadas = 0
                        while (i < total
                               and publicaciones[i].seccion == seccion_actual):
                            i += 1
                            saltadas += 1
                        progreso.log(
                            f"   «{seccion_actual or 'seccion'}»: ya solo salen "
                            f"publicaciones anteriores al rango; me salto "
                            f"{saltadas} y paso a la siguiente seccion."
                        )
                        seguidas_antiguas = 0
                        continue
            except Exception as e:
                pub.nota = f"No se pudo comprobar la fecha: {str(e)[:80]}"
            # Pausa corta para no atropellar a Facebook
            pagina.wait_for_timeout(random.randint(200, 450))

        resumen = (
            f"Fechas comprobadas: {comprobadas} de {total}. "
            f"Se corrigieron {corregidas}."
        )
        if ambiguas:
            resumen += (
                f" {ambiguas} quedaron sin fecha por ser ambigua: prefiero "
                "dejarlas sin confirmar antes que ponerles una fecha erronea."
            )
        progreso.log(resumen)

    @staticmethod
    def _enlace_de_comentario(href: str) -> bool:
        """True si el enlace es el permalink de un COMENTARIO, no del post."""
        h = (href or "").lower()
        return "comment_id=" in h or "reply_comment_id=" in h

    # ---------------------------------------------------- FASE 2: comentarios

    def extraer_comentarios(
        self,
        pagina: Page,
        publicacion: Publicacion,
        opciones: OpcionesExtraccion,
        progreso: Progreso,
    ) -> list[Comentario]:
        progreso.log(f"Abriendo publicacion: {publicacion.url}")
        pagina.goto(publicacion.url, wait_until="domcontentloaded", timeout=60_000)
        pagina.wait_for_timeout(2500)
        self._cerrar_estorbos(pagina)

        # Fecha exacta de la publicacion (mas fiable que la leida en el muro)
        fecha_exacta: datetime | None = None
        try:
            datos = pagina.evaluate(
                JS_DATOS_PUBLICACION,
                self._identificador_publicacion(publicacion.url),
            )
            if datos.get("creacion"):
                fecha_exacta = desde_epoch(datos["creacion"])
                if fecha_exacta:
                    publicacion.fecha = fecha_exacta
            if datos.get("texto") and not publicacion.texto:
                publicacion.texto = datos["texto"]
        except Exception:
            pass

        # Red de seguridad del modo automatico: si la fecha real se sale del
        # rango que pediste, no gastamos tiempo leyendo sus comentarios.
        if (
            opciones.verificar_rango_al_extraer
            and fecha_exacta is not None
            and opciones.desde
            and opciones.hasta
            and not (opciones.desde <= fecha_exacta <= opciones.hasta)
        ):
            publicacion.estado = "omitida"
            publicacion.nota = (
                f"Fuera del rango (fecha real {fecha_exacta:%d/%m/%Y})"
            )
            progreso.log(
                f"   ↷ Omitida: su fecha real es {fecha_exacta:%d/%m/%Y}, "
                "fuera del rango pedido."
            )
            return []

        # Los reels se abren en el reproductor inmersivo con el panel de
        # comentarios CERRADO. Sin pulsar «Comentar» no hay nada que leer,
        # por muchos comentarios que tenga la publicacion.
        anunciados = self._abrir_panel_comentarios(pagina, progreso)

        self._ordenar_todos_los_comentarios(pagina, progreso)

        # Vamos ACUMULANDO lo que leemos en cada vuelta.
        #
        # En el reproductor de reels solo damos por buenos los comentarios que
        # estan en pantalla (los de fuera pertenecen a las tarjetas de otros
        # reels). Como el panel se va desplazando, hay que ir juntando lo que
        # aparece en cada momento: con una unica lectura final solo tendriamos
        # el ultimo trozo visible.
        acumulados: dict[str, dict] = {}
        modo = ""
        en_reels = "/reel/" in publicacion.url.lower()
        rondas_sin_nuevos = 0

        # Guardamos el identificador del reel para detectar si el reproductor
        # se nos escapa a la siguiente tarjeta.
        id_original = self._identificador_reel(publicacion.url)
        anclado_alguna_vez = False

        for vuelta in range(1, 81):
            if progreso.cancelado():
                break

            # ¿Se movio el carrusel a otro reel? Entonces todo lo que venga ya
            # no es de esta publicacion: paramos con lo que llevamos.
            desviado = False
            if id_original:
                id_actual = self._identificador_reel(pagina.url)
                if id_actual and id_actual != id_original:
                    progreso.log(
                        "   El reproductor salto a otro reel; corto aqui para no "
                        "mezclar comentarios."
                    )
                    break

            # Re-anclamos el panel EN CADA VUELTA, no una sola vez al principio.
            #
            # Hace falta por dos motivos: al abrir los comentarios todavia hay
            # tan pocos que el panel no desborda y no se puede anclar; y cuando
            # se pulsa «Ver mas comentarios» Facebook reemplaza el nodo, con lo
            # que un ancla puesta antes se quedaria apuntando a un elemento
            # muerto y dejariamos de leer. Solo re-anclamos mientras la URL
            # siga siendo la de esta publicacion.
            if not desviado:
                try:
                    ancla = pagina.evaluate(
                        JS_ANCLAR_PANEL,
                        [self.cfg["selectores_texto_comentario"],
                         self.cfg["prefijo_comentario_aria"]],
                    ) or {}
                except Exception:
                    ancla = {}
                if ancla.get("ok") and not anclado_alguna_vez:
                    anclado_alguna_vez = True
                    progreso.log("   Panel de comentarios anclado a esta publicacion.")

            pulsados = 0
            try:
                pulsados += pagina.evaluate(
                    JS_PULSAR_BOTONES, [self.cfg["boton_mas_comentarios"], 15]
                )
            except Exception:
                pass
            try:
                pagina.evaluate(
                    JS_PULSAR_BOTONES, [self.cfg["boton_ver_mas_texto"], 25]
                )
            except Exception:
                pass

            pagina.wait_for_timeout(random.randint(600, 1000))

            # Recogemos ANTES de desplazar, para no perder lo que se ve ahora
            crudos, modo_actual, detectado = self._leer_comentarios_crudos(pagina)
            if modo_actual:
                modo = modo_actual
            en_reels = en_reels or detectado
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

            # En el reproductor de reels NO se puede mover la pagina: ese gesto
            # es justo el que salta al reel siguiente. Solo el panel.
            movido = False
            try:
                estado = pagina.evaluate(JS_DESPLAZAR_PANEL) or {}
                movido = bool(estado.get("se_movio"))
                if not en_reels and not estado.get("encontrado"):
                    pagina.evaluate(JS_DESPLAZAR, 900)
                    movido = True
            except Exception:
                pass
            pagina.wait_for_timeout(700)

            rondas_sin_nuevos = 0 if nuevos else rondas_sin_nuevos + 1
            if pulsados == 0 and not movido and rondas_sin_nuevos >= 3:
                break  # ya no hay nada mas que cargar
            if rondas_sin_nuevos >= 8:
                break

        crudos = list(acumulados.values())
        if modo == "mensajes":
            progreso.log(
                "   (leidos con el metodo alternativo, el del visor de reels)"
            )

        comentarios: list[Comentario] = []
        descartados = 0
        vistos: set[str] = set()

        for c in crudos:
            texto = limpiar_texto(c.get("texto", ""))
            if not texto:
                descartados += 1  # era solo GIF / sticker / imagen
                continue
            es_respuesta = bool(c.get("es_respuesta"))
            if es_respuesta and not opciones.incluir_respuestas:
                continue

            autor = limpiar_autor(c.get("autor", ""))
            clave = f"{autor}|{texto}"
            if clave in vistos:
                continue
            vistos.add(clave)

            comentarios.append(
                Comentario(
                    publicacion_url=publicacion.url,
                    red=self.nombre,
                    autor=autor,
                    texto=texto,
                    fecha=interpretar_fecha(c.get("fecha", "")),
                    es_respuesta=es_respuesta,
                    reacciones=int(c.get("reacciones") or 0),
                )
            )
            if len(comentarios) >= opciones.max_comentarios_por_publicacion:
                break

        if descartados:
            progreso.log(
                f"Se ignoraron {descartados} comentarios sin texto "
                "(eran GIF, sticker o imagen)."
            )

        # Si no salio ni uno, guardamos la pagina para poder ver que cambio.
        # Sin esto habria que adivinar por que fallo.
        if not comentarios and not crudos:
            ruta = self.guardar_diagnostico(pagina, "sin_comentarios")
            progreso.log(
                "⚠ No se encontro ningun comentario en esta publicacion. "
                f"Guarde la pagina para revisarla en:\n   {ruta}"
            )

        if anunciados:
            progreso.log(
                f"Comentarios de texto extraidos: {len(comentarios)} "
                f"(Facebook anunciaba {anunciados})"
            )
        else:
            progreso.log(f"Comentarios de texto extraidos: {len(comentarios)}")
        return comentarios

    # -------------------------------------------------------------- auxiliares

    def _abrir_panel_comentarios(self, pagina: Page, progreso: Progreso) -> str:
        """Pulsa «Comentar» para que Facebook cargue los comentarios.

        Es imprescindible en los reels: se abren en el reproductor inmersivo
        con el panel plegado (aria-expanded="false") y los comentarios ni
        siquiera estan en la pagina hasta que se pulsa el boton.

        Devuelve el numero de comentarios que anuncia Facebook, si lo encuentra.
        """
        patron = self.cfg.get(
            "boton_abrir_comentarios", "^(comentar|comment)$"
        )

        anunciados = ""
        try:
            anunciados = pagina.evaluate(JS_COMENTARIOS_ANUNCIADOS, patron) or ""
        except Exception:
            pass
        if anunciados:
            progreso.log(f"   Facebook anuncia {anunciados} comentarios.")

        for intento in range(1, 4):
            crudos, _, _ = self._leer_comentarios_crudos(pagina)
            if crudos:
                return anunciados  # ya estan cargados, no hay que tocar nada

            try:
                resultado = pagina.evaluate(JS_ABRIR_COMENTARIOS, patron)
            except Exception:
                resultado = ""

            if not resultado:
                return anunciados  # no hay boton: publicacion normal
            if resultado != "ya_abierto":
                progreso.log(f"   Abriendo el panel de comentarios ({resultado})…")
            pagina.wait_for_timeout(2500 if intento == 1 else 1800)

        return anunciados

    def _leer_comentarios_crudos(self, pagina: Page) -> tuple[list[dict], str, bool]:
        """Lee los comentarios que hay cargados ahora mismo en la pagina.

        Devuelve (lista, modo, en_reels). El modo indica que estrategia funciono:
          "articulos" -> publicaciones normales
          "mensajes"  -> reels y visor de fotos (no usan role="article")
        """
        try:
            datos = pagina.evaluate(
                JS_LEER_COMENTARIOS,
                [self.cfg["prefijo_comentario_aria"],
                 self.cfg["selectores_texto_comentario"]],
            )
        except Exception:
            return [], "error", False

        # El JS devuelve un objeto; toleramos la forma antigua (lista) por si
        # alguien edita el archivo de configuracion y se queda a medias.
        if isinstance(datos, dict):
            return (
                datos.get("comentarios") or [],
                datos.get("modo", ""),
                bool(datos.get("en_reels")),
            )
        return datos or [], "articulos", False

    def _ordenar_todos_los_comentarios(self, pagina: Page, progreso: Progreso) -> None:
        """Cambia el orden de comentarios a 'Todos los comentarios'.

        Es un paso clave: por defecto Facebook muestra solo los 'mas
        relevantes' y esconde muchisimos comentarios.
        """
        try:
            abierto = pagina.evaluate(
                JS_ABRIR_ORDEN, self.cfg["boton_orden_comentarios"]
            )
            if not abierto:
                return
            pagina.wait_for_timeout(900)
            elegido = pagina.evaluate(
                JS_ELEGIR_OPCION_MENU, self.cfg["opcion_todos_los_comentarios"]
            )
            if elegido:
                progreso.log(f"Orden de comentarios cambiado a: {elegido}")
                pagina.wait_for_timeout(2000)
            else:
                pagina.keyboard.press("Escape")
        except Exception:
            pass

    def _cerrar_estorbos(self, pagina: Page) -> None:
        """Cierra el aviso de cookies y las ventanas emergentes de inicio de sesion.

        En cookies elegimos siempre la opcion que MENOS datos comparte
        (rechazar las opcionales). Nunca 'aceptar todas'.
        """
        try:
            pagina.evaluate(
                JS_PULSAR_BOTONES, [self.cfg["boton_rechazar_cookies"], 2]
            )
            pagina.wait_for_timeout(700)
        except Exception:
            pass
        # Ventana emergente "Inicia sesion para continuar"
        try:
            dialogos = pagina.locator('div[role="dialog"]')
            if dialogos.count():
                cerrar = dialogos.first.locator(
                    '[aria-label="Cerrar"], [aria-label="Close"]'
                )
                if cerrar.count():
                    cerrar.first.click(timeout=2500)
                    pagina.wait_for_timeout(500)
        except Exception:
            pass

    @staticmethod
    def _normalizar_url_publicacion(href: str) -> str:
        """Deja la URL de la publicacion limpia y siempre igual.

        Facebook agrega basura de seguimiento (__cft__, __tn__, etc.) que hace
        que la misma publicacion parezca 20 URLs distintas. Aqui la quitamos.
        """
        if not href or "facebook.com" not in href:
            return ""
        partes = urlsplit(href)
        ruta = partes.path.rstrip("/")
        if not ruta or ruta == "":
            ruta = "/"

        consulta = parse_qs(partes.query)
        conservar: dict[str, str] = {}
        for clave in ("story_fbid", "id", "fbid", "v"):
            if clave in consulta and consulta[clave]:
                conservar[clave] = consulta[clave][0]

        # Descartamos enlaces que no son publicaciones
        if ruta.startswith(("/login", "/privacy", "/policies", "/help", "/ads")):
            return ""
        # Un enlace a comentario concreto lo tratamos como su publicacion
        if not ruta and not conservar:
            return ""

        base = f"https://www.facebook.com{ruta}"
        if conservar:
            base += "?" + urlencode(conservar)

        # La URL debe apuntar a UNA publicacion concreta. Sin esta comprobacion
        # se colaban enlaces genericos como facebook.com/reel (el feed de
        # descubrimiento), que cada vez que se abre muestra un reel distinto y
        # no corresponde a ninguna publicacion del perfil.
        if not ExtractorFacebook._tiene_identificador(base):
            return ""
        return base

    @staticmethod
    def _identificador_publicacion(url: str) -> str:
        """Identificador de la publicacion, sacado de su URL.

        Es lo que permite elegir la fecha correcta cuando la pagina trae
        varias: nos quedamos con el «creation_time» que este pegado a este id.
        """
        u = url or ""
        for patron in (
            r"/reels?/(\d+)",
            r"/videos/(?:[^/]+/)?(\d+)",
            r"/posts/([A-Za-z0-9]+)",
            r"[?&]v=(\d+)",
            r"[?&]fbid=(\d+)",
            r"story_fbid=(\d+)",
            r"/watch/?\?v=(\d+)",
        ):
            m = re.search(patron, u)
            if m:
                return m.group(1)
        return ""

    @staticmethod
    def _identificador_reel(url: str) -> str:
        """Saca el numero del reel de una URL, o cadena vacia si no es un reel.

        Sirve para detectar que el reproductor ha saltado a otra tarjeta: la
        direccion de la pagina cambia sola al avanzar el carrusel.
        """
        m = re.search(r"/reels?/(\d+)", url or "")
        return m.group(1) if m else ""

    @staticmethod
    def _tiene_identificador(url: str) -> bool:
        """True si la URL lleva el identificador de una publicacion concreta.

        Basta con que el identificador EXISTA; no le exigimos una longitud
        minima, porque solo queremos descartar las direcciones genericas
        (facebook.com/reel, /mipagina/videos…), no publicaciones reales.
        """
        if re.search(r"/(reel|reels|videos|posts|watch)/[A-Za-z0-9._-]+", url):
            return True
        if re.search(r"/share/[pvr]/[A-Za-z0-9._-]+", url):
            return True
        if re.search(r"(?:story_fbid|fbid|[?&]v)=[A-Za-z0-9._-]+", url):
            return True
        return False

    @staticmethod
    def _tipo_publicacion(url: str) -> str:
        u = url.lower()
        if "/reel/" in u or "/share/r/" in u:
            return "reel"
        if "/videos/" in u or "/watch" in u or "/share/v/" in u:
            return "video"
        if "/photo" in u or "fbid=" in u:
            return "foto"
        return "publicacion"

    @staticmethod
    def _fecha_desde_enlace(item: dict) -> datetime | None:
        """Intenta sacar la fecha del texto, del aria-label o del title del enlace."""
        for campo in ("aria", "titulo", "texto"):
            valor = (item.get(campo) or "").strip()
            if not valor or len(valor) > 80 or not any(c.isdigit() for c in valor):
                continue
            fecha = interpretar_fecha(valor)
            if fecha:
                return fecha
        return None

    # Lineas de interfaz que no aportan nada al identificar la publicacion
    _RUIDO_LINEA = re.compile(
        r"^(me gusta|comentar|compartir|like|comment|share|responder|reply|"
        r"todas las reacciones|all reactions|\d[\d.,]* comentarios?|"
        r"\d[\d.,]* comments?|ver m[aá]s|see more|seguir|follow|"
        r"editado|edited|autor|author|top fan|fan destacado|"
        r"ver traducci[oó]n|see translation)$",
        re.IGNORECASE,
    )
    # Lineas que son solo una hora relativa ("15 h", "2 dias", "hace 3 h").
    # Casi siempre vienen del comentario destacado, no de la publicacion.
    _SOLO_TIEMPO = re.compile(
        r"^(hace\s+)?\d+\s*"
        r"(s|seg|segundos?|min|mins?|minutos?|m|h|hr|hrs|horas?|d|d[ií]as?|"
        r"sem|semanas?|w|mes|meses|mo|a|años?|anos?|y)\.?$",
        re.IGNORECASE,
    )

    @classmethod
    def _texto_del_bloque(cls, cuerpo: str) -> str:
        """Saca unas lineas representativas del post para reconocerlo en la tabla.

        Es solo una etiqueta provisional: al comprobar las fechas se sustituye
        por el texto real de la publicacion.
        """
        if not cuerpo:
            return ""
        lineas = [l.strip() for l in cuerpo.split("\n") if l.strip()]
        utiles = [
            l for l in lineas
            if len(l) > 3
            and not cls._RUIDO_LINEA.match(l)
            and not cls._SOLO_TIEMPO.match(l)
        ]
        return " ".join(utiles[:3])[:300]

    @staticmethod
    def _en_rango(pub: Publicacion, desde: datetime, hasta: datetime) -> bool:
        return pub.fecha is not None and desde <= pub.fecha <= hasta

    # ------------------------------------------------------------ diagnostico

    def guardar_diagnostico(self, pagina: Page, etiqueta: str = "facebook") -> Path:
        """Guarda el HTML y una captura de la pagina actual.

        Si algo deja de funcionar, estos dos archivos permiten ver que cambio
        Facebook sin tener que adivinar.
        """
        marca = datetime.now().strftime("%Y%m%d_%H%M%S")
        destino_html = CARPETA_DIAGNOSTICO / f"{etiqueta}_{marca}.html"
        destino_png = CARPETA_DIAGNOSTICO / f"{etiqueta}_{marca}.png"
        try:
            destino_html.write_text(pagina.content(), encoding="utf-8", errors="ignore")
            pagina.screenshot(path=str(destino_png), full_page=False)
        except Exception:
            pass
        return destino_html
