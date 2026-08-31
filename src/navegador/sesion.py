"""Control del navegador automatizado (Playwright).

Abrimos un Chromium con un "perfil persistente": una carpeta donde quedan
guardadas las cookies. Asi inicias sesion UNA vez a mano y la app recuerda
la sesion las siguientes veces.

Importante: la app NUNCA te pide ni guarda tu contraseña. Tu escribes tus
datos directamente en la ventana de Facebook/Instagram/etc.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Page, sync_playwright

from ..core.rutas import carpeta_perfil_navegador

# Argumentos del navegador.
#
# OJO: aqui NO debe ir "--disable-features=IsolateOrigins,site-per-process".
# Es un truco antiguo para pasar desapercibido, pero rompe las paginas
# modernas de Facebook: la verificacion en dos pasos y algunos dialogos se
# quedan en blanco porque su codigo necesita el aislamiento de origenes.
# Tampoco va "--disable-blink-features=AutomationControlled": Chrome muestra
# por el una barra amarilla de advertencia, de modo que un parametro puesto
# para disimular acababa anunciando lo contrario. Lo que hacia ya lo cubre el
# retoque de navigator.webdriver de mas abajo.
_ARGS = [
    "--no-default-browser-check",
    "--no-first-run",
    "--disable-notifications",
    "--start-maximized",
]

# Retoques que se aplican a cada pagina ANTES de que corra el codigo del sitio.
_GUION_INICIAL = r"""
// 1. navigator.webdriver delata al navegador automatizado
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

// Aqui hubo un envoltorio sobre Function para desactivar las trampas de
// «debugger». Se quito: se comprobo que mientras nadie active el depurador
// esas sentencias no hacen nada, asi que no aportaba, y envolver Function
// rompe las comprobaciones de identidad que hace el codigo de algunas
// paginas. Menos retoques, menos formas de estropear el sitio.
"""


# Playwright, en su version sincrona, solo admite UNA instancia por hilo.
#
# Como cada red social tiene su propia sesion de navegador (para que no se
# mezclen las cookies), al pasar de Facebook a Instagram se creaba una segunda
# instancia con la primera aun viva y Playwright lo rechazaba con el error
# "It looks like you are using Playwright Sync API inside the asyncio loop".
#
# La solucion es compartir una unica instancia entre todas las redes: de ella
# cuelgan tantos navegadores como haga falta.
_playwright_compartido = None


def obtener_playwright():
    """Devuelve la instancia de Playwright del hilo, creandola si hace falta."""
    global _playwright_compartido
    if _playwright_compartido is None:
        _playwright_compartido = sync_playwright().start()
    return _playwright_compartido


def cerrar_playwright() -> None:
    """Apaga Playwright del todo. Solo al cerrar la aplicacion."""
    global _playwright_compartido
    if _playwright_compartido is not None:
        try:
            _playwright_compartido.stop()
        except Exception:
            pass
        _playwright_compartido = None


class SesionNavegador:
    """Abre y mantiene vivo un navegador para una red social."""

    def __init__(self, red: str, visible: bool = True, ralentizar_ms: int = 0,
                 usar_chrome: bool = True, carpeta_perfil: str = ""):
        self.red = red
        # Carpeta de perfil propia, si el usuario eligio una.
        #
        # Sirve para el caso en que una red limita los intentos de acceso
        # desde el navegador de la aplicacion (X lo hace). En vez de pelear
        # con eso, se inicia sesion UNA vez en un Chrome normal que use esa
        # carpeta, y despues la aplicacion abre esa misma carpeta: la sesion
        # ya esta dentro y no hay ningun intento de acceso que limitar.
        self.carpeta_perfil = (carpeta_perfil or "").strip()
        self.visible = visible
        self.ralentizar_ms = ralentizar_ms
        # Usar el Chrome instalado en el equipo en vez del Chromium que trae
        # Playwright. Importa mas de lo que parece: el Chromium incluido NO
        # lleva los codecs de video propietarios (H.264), y sin ellos TikTok
        # carga la pagina pero deja la cuadricula de videos en blanco.
        self.usar_chrome = usar_chrome
        self.navegador_usado = ""
        self._playwright: Any = None
        self._contexto: BrowserContext | None = None
        self._pagina: Page | None = None

    # ------------------------------------------------------------ ciclo de vida

    def abrir(self) -> Page:
        """Arranca el navegador (si no estaba abierto) y devuelve la pestaña."""
        if self._pagina and not self._pagina.is_closed():
            return self._pagina

        self._playwright = obtener_playwright()
        if self.carpeta_perfil:
            perfil = Path(self.carpeta_perfil)
            perfil.mkdir(parents=True, exist_ok=True)
        else:
            perfil = carpeta_perfil_navegador(self.red)

        # Con el navegador visible dejamos que la ventana mande (no_viewport);
        # oculto le damos un tamaño fijo grande para que Facebook cargue la
        # version de escritorio y no la movil.
        extra = (
            {"no_viewport": True}
            if self.visible
            else {"viewport": {"width": 1500, "height": 950}}
        )

        def _lanzar(con_sandbox: bool, canal: str | None) -> BrowserContext:
            opciones = dict(
                user_data_dir=str(perfil),
                headless=not self.visible,
                slow_mo=self.ralentizar_ms,
                args=_ARGS,
                locale="es-ES",
                timezone_id="America/Bogota",
                ignore_default_args=["--enable-automation"],
                # Playwright desactiva el sandbox de Chromium por defecto, y eso
                # hace que salga la barra amarilla de aviso y que algunas paginas
                # vayan peor. Lo activamos; si el equipo no lo admite, reintentamos
                # sin el para no dejar al usuario sin navegador.
                chromium_sandbox=con_sandbox,
                **extra,
            )
            if canal:
                opciones["channel"] = canal
            return self._playwright.chromium.launch_persistent_context(**opciones)

        # Orden de preferencia. El Chrome del equipo va primero porque lleva
        # los codecs que el Chromium incluido no trae; si no esta instalado,
        # se prueba Edge y por ultimo el Chromium de siempre.
        candidatos = (
            [("chrome", "tu Google Chrome"), ("msedge", "Microsoft Edge"),
             (None, "el Chromium incluido")]
            if self.usar_chrome else [(None, "el Chromium incluido")]
        )

        ultimo_error: Exception | None = None
        for canal, nombre in candidatos:
            for con_sandbox in (True, False):
                try:
                    self._contexto = _lanzar(con_sandbox, canal)
                    self.navegador_usado = nombre
                    break
                except Exception as e:
                    ultimo_error = e
            if self._contexto is not None:
                break

        if self._contexto is None:
            raise RuntimeError(
                "No se pudo abrir ningun navegador. "
                f"Ultimo error: {ultimo_error}"
            )

        self._contexto.set_default_timeout(25_000)

        # Reutilizamos la pestaña que abre Chromium al arrancar
        self._pagina = (
            self._contexto.pages[0]
            if self._contexto.pages
            else self._contexto.new_page()
        )

        # Se aplica a TODAS las pestañas del contexto, incluidas las auxiliares
        # que se abren despues, y en cada navegacion.
        self._contexto.add_init_script(_GUION_INICIAL)

        # Cada pestaña nueva se prepara sola (las auxiliares de las sondas
        # tambien). Y preparamos la que ya existe.
        self._contexto.on("page", self._preparar_pagina)
        self._preparar_pagina(self._pagina)
        return self._pagina

    def _preparar_pagina(self, pagina: Page) -> None:
        """Pide al navegador que no se detenga en las sentencias `debugger`.

        TikTok lleva sentencias `debugger` literales en bucle para congelar la
        pestaña. El sintoma es el aviso «El depurador se ha pausado en otra
        pestaña»: con la pagina detenida ni siquiera termina de cargar, se
        queda en about:blank y no se puede ni iniciar sesion.

        MUY IMPORTANTE no llamar aqui a `Debugger.enable`. Medido:

            sin tocar CDP ............... carga en 1,6 s
            Debugger.enable ............. se congela
            enable + setSkipAllPauses ... se congela igual
            solo setSkipAllPauses ....... carga en 1,6 s

        Es decir: mientras nadie active el depurador, un `debugger` literal no
        hace absolutamente nada, y activarlo es justo lo que dispara la
        trampa. Enviamos solo setSkipAllPauses, que es inofensivo y ademas
        cubre el caso de que el depurador lo haya activado otro (por ejemplo,
        si quedaron las herramientas de desarrollo abiertas en el perfil).
        """
        try:
            cdp = self._contexto.new_cdp_session(pagina)
            cdp.send("Debugger.setSkipAllPauses", {"skip": True})
        except Exception:
            pass

    @property
    def pagina(self) -> Page:
        return self.abrir()

    @property
    def abierta(self) -> bool:
        return self._pagina is not None and not self._pagina.is_closed()

    def cerrar(self) -> None:
        """Cierra este navegador. Las cookies quedan guardadas en el perfil.

        No se apaga Playwright: esta compartido con las demas redes y otra
        podria estar usandolo. Se apaga al cerrar la aplicacion, con
        `cerrar_playwright()`.
        """
        try:
            if self._contexto:
                self._contexto.close()
        except Exception:
            pass
        self._contexto = None
        self._pagina = None
        self._playwright = None

    # --------------------------------------------------------------- utilidades

    def ir_a(self, url: str, espera: int = 30_000) -> None:
        """Navega a una URL sin esperar a que TODO cargue (las redes nunca paran)."""
        pagina = self.pagina
        pagina.goto(url, wait_until="domcontentloaded", timeout=espera)
        pagina.wait_for_timeout(1500)

    def recargar(self) -> str:
        """Vuelve a cargar la pagina actual y devuelve su URL.

        Util cuando una pantalla de Facebook se queda en blanco: casi siempre
        se arregla recargando, sin perder lo que llevabas.
        """
        pagina = self.pagina
        pagina.reload(wait_until="domcontentloaded", timeout=45_000)
        pagina.wait_for_timeout(2000)
        return pagina.url


def texto_seguro(elemento: Any, por_defecto: str = "") -> str:
    """Lee el texto de un elemento sin reventar si ya no existe."""
    try:
        return (elemento.inner_text() or por_defecto).strip()
    except Exception:
        return por_defecto
