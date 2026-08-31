"""Control del navegador automatizado (Playwright).

Abrimos un Chromium con un "perfil persistente": una carpeta donde quedan
guardadas las cookies. Asi inicias sesion UNA vez a mano y la app recuerda
la sesion las siguientes veces.

Importante: la app NUNCA te pide ni guarda tu contraseña. Tu escribes tus
datos directamente en la ventana de Facebook/Instagram/etc.
"""

from __future__ import annotations

from typing import Any

from playwright.sync_api import BrowserContext, Page, sync_playwright

from ..core.rutas import carpeta_perfil_navegador

# Argumentos del navegador.
#
# OJO: aqui NO debe ir "--disable-features=IsolateOrigins,site-per-process".
# Es un truco antiguo para pasar desapercibido, pero rompe las paginas
# modernas de Facebook: la verificacion en dos pasos y algunos dialogos se
# quedan en blanco porque su codigo necesita el aislamiento de origenes.
_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-default-browser-check",
    "--no-first-run",
    "--disable-notifications",
    "--start-maximized",
]


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

    def __init__(self, red: str, visible: bool = True, ralentizar_ms: int = 0):
        self.red = red
        self.visible = visible
        self.ralentizar_ms = ralentizar_ms
        self._playwright: Any = None
        self._contexto: BrowserContext | None = None
        self._pagina: Page | None = None

    # ------------------------------------------------------------ ciclo de vida

    def abrir(self) -> Page:
        """Arranca el navegador (si no estaba abierto) y devuelve la pestaña."""
        if self._pagina and not self._pagina.is_closed():
            return self._pagina

        self._playwright = obtener_playwright()
        perfil = carpeta_perfil_navegador(self.red)

        # Con el navegador visible dejamos que la ventana mande (no_viewport);
        # oculto le damos un tamaño fijo grande para que Facebook cargue la
        # version de escritorio y no la movil.
        extra = (
            {"no_viewport": True}
            if self.visible
            else {"viewport": {"width": 1500, "height": 950}}
        )

        def _lanzar(con_sandbox: bool) -> BrowserContext:
            return self._playwright.chromium.launch_persistent_context(
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

        try:
            self._contexto = _lanzar(True)
        except Exception:
            self._contexto = _lanzar(False)

        self._contexto.set_default_timeout(25_000)

        # Reutilizamos la pestaña que abre Chromium al arrancar
        self._pagina = (
            self._contexto.pages[0]
            if self._contexto.pages
            else self._contexto.new_page()
        )

        # Pequeño parche para que la pagina no detecte "navigator.webdriver"
        self._contexto.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        return self._pagina

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
