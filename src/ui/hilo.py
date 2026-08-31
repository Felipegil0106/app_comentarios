"""Hilo de trabajo: aqui vive el navegador.

Todo lo lento (abrir Facebook, bajar por el muro, leer comentarios) ocurre
en este hilo aparte. Asi la ventana nunca se congela y siempre puedes
pulsar "Detener".

Funciona con una cola de tareas: la interfaz encola ("descubre publicaciones")
y este hilo las va ejecutando una por una.
"""

from __future__ import annotations

import queue
import random
import traceback
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QThread, Signal

from ..core.base_datos import BaseDatos
from ..core.modelos import Publicacion
from ..navegador.sesion import SesionNavegador, cerrar_playwright
from ..redes import registro
from ..redes.base import OpcionesExtraccion, Progreso


@dataclass
class Tarea:
    tipo: str
    red: str = "facebook"
    opciones: OpcionesExtraccion | None = None
    publicaciones: list[Publicacion] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


class HiloNavegador(QThread):
    """Ejecuta las tareas del navegador y avisa a la interfaz por señales."""

    # --- señales (avisos que la ventana escucha) ---
    log = Signal(str)
    progreso = Signal(int, int, str)
    estado_sesion = Signal(bool, str)             # hay_sesion, mensaje
    publicaciones_listas = Signal(list)           # list[Publicacion]
    publicacion_procesada = Signal(object, int)   # Publicacion, nuevos
    tarea_inicia = Signal(str)                    # nombre legible
    tarea_termina = Signal(str, bool, str)        # nombre, ok, mensaje
    ocupado = Signal(bool)

    def __init__(self, bd: BaseDatos, parent=None):
        super().__init__(parent)
        self.bd = bd
        self._cola: "queue.Queue[Tarea | None]" = queue.Queue()
        self._sesiones: dict[str, SesionNavegador] = {}
        self._cancelar = False
        self._navegador_visible = True
        self._pausa_entre_publicaciones = (3, 7)  # segundos, para no saturar
        self._ocupado = False

    @property
    def esta_ocupado(self) -> bool:
        """True si ahora mismo hay una tarea corriendo o esperando en la cola."""
        return self._ocupado or not self._cola.empty()

    # ------------------------------------------------------------- API publica

    def encolar(self, tarea: Tarea) -> None:
        self._cancelar = False
        self._cola.put(tarea)

    def cancelar(self) -> None:
        """Pide detener la tarea en curso (no cierra el navegador)."""
        self._cancelar = True
        self.log.emit("⏹ Deteniendo… (termina el paso actual y para)")

    def detener_todo(self) -> None:
        self._cancelar = True
        self._cola.put(None)

    def configurar_navegador(self, visible: bool) -> None:
        self._navegador_visible = visible

    # ------------------------------------------------------------ bucle del hilo

    def run(self) -> None:  # noqa: C901  (bucle principal, largo a proposito)
        while True:
            tarea = self._cola.get()
            if tarea is None:
                break
            self._cancelar = False
            self._ocupado = True
            self.ocupado.emit(True)
            nombre = self._nombre_legible(tarea.tipo)
            self.tarea_inicia.emit(nombre)
            try:
                self._ejecutar(tarea)
                self.tarea_termina.emit(nombre, True, "Completado")
            except Exception as e:
                detalle = "".join(traceback.format_exception_only(type(e), e)).strip()
                self.log.emit(f"❌ Error: {detalle}")
                self.tarea_termina.emit(nombre, False, detalle)
            finally:
                self._ocupado = False
                self.ocupado.emit(False)

        for sesion in self._sesiones.values():
            sesion.cerrar()
        self._sesiones.clear()
        # Playwright se comparte entre redes, asi que solo se apaga aqui,
        # cuando el hilo termina de verdad.
        cerrar_playwright()

    # ------------------------------------------------------------- ejecucion

    def _ejecutar(self, tarea: Tarea) -> None:
        if tarea.tipo == "iniciar_sesion":
            self._tarea_iniciar_sesion(tarea)
        elif tarea.tipo == "verificar_sesion":
            self._tarea_verificar_sesion(tarea)
        elif tarea.tipo == "descubrir":
            self._tarea_descubrir(tarea)
        elif tarea.tipo == "extraer":
            self._tarea_extraer(tarea)
        elif tarea.tipo == "recargar":
            self._tarea_recargar(tarea)
        elif tarea.tipo == "diagnostico":
            self._tarea_diagnostico(tarea)
        elif tarea.tipo == "cerrar_navegador":
            self._tarea_cerrar(tarea)
        else:
            raise ValueError(f"Tarea desconocida: {tarea.tipo}")

    def _sesion(self, red: str) -> SesionNavegador:
        sesion = self._sesiones.get(red)
        if sesion is None or not sesion.abierta:
            sesion = SesionNavegador(red, visible=self._navegador_visible)
            self._sesiones[red] = sesion
            self.log.emit("🌐 Abriendo el navegador…")
            sesion.abrir()
        return sesion

    def _progreso(self) -> Progreso:
        return Progreso(
            log=lambda m: self.log.emit(m),
            paso=lambda h, t, m: self.progreso.emit(h, t, m),
            cancelado=lambda: self._cancelar,
        )

    # ------------------------------------------------------------------ tareas

    def _tarea_iniciar_sesion(self, tarea: Tarea) -> None:
        extractor = registro.obtener(tarea.red)
        sesion = self._sesion(tarea.red)
        try:
            extractor.abrir_login(sesion.pagina)
            sesion.pagina.wait_for_timeout(2000)
        except Exception as e:
            self.log.emit(f"⚠ No se pudo abrir la pagina: {str(e)[:120]}")

        # Decimos donde acabamos de verdad: si se queda en about:blank es que
        # la pagina no cargo, y conviene verlo en el registro.
        try:
            destino = sesion.pagina.url
        except Exception:
            destino = "?"
        if destino.startswith("about:") or not destino:
            self.log.emit(
                f"⚠ El navegador se quedo en «{destino}»: {extractor.etiqueta} "
                "no llego a cargar. Prueba a recargar con el boton 🔄."
            )
        else:
            self.log.emit(
                f"Se abrio {extractor.etiqueta} en el navegador ({destino[:60]}). "
                "Inicia sesion ahi con tu usuario y contraseña; "
                "cuando termines vuelve aqui y pulsa «Ya inicie sesion»."
            )

    def _tarea_verificar_sesion(self, tarea: Tarea) -> None:
        extractor = registro.obtener(tarea.red)
        sesion = self._sesion(tarea.red)
        ok = extractor.sesion_iniciada(sesion.pagina)
        if ok:
            self.estado_sesion.emit(True, f"Sesion activa en {extractor.etiqueta}")
            self.log.emit(f"✅ Sesion activa en {extractor.etiqueta}.")
        else:
            self.estado_sesion.emit(False, f"Sin sesion en {extractor.etiqueta}")
            self.log.emit(
                f"⚠ Todavia no hay sesion en {extractor.etiqueta}. "
                "Pulsa «Abrir navegador e iniciar sesion»."
            )

    def _tarea_descubrir(self, tarea: Tarea) -> None:
        extractor = registro.obtener(tarea.red)
        if not extractor.implementado:
            raise NotImplementedError(
                f"{extractor.etiqueta} todavia no esta disponible. "
                "Por ahora usa Facebook."
            )
        sesion = self._sesion(tarea.red)
        opciones = tarea.opciones or OpcionesExtraccion()

        publicaciones = extractor.descubrir_publicaciones(
            sesion.pagina, opciones, self._progreso()
        )
        for pub in publicaciones:
            self.bd.guardar_publicacion(pub)
        self.bd.recalcular_conteos()
        self.publicaciones_listas.emit(publicaciones)

    def _tarea_extraer(self, tarea: Tarea) -> None:
        extractor = registro.obtener(tarea.red)
        if not extractor.implementado:
            raise NotImplementedError(
                f"{extractor.etiqueta} todavia no esta disponible."
            )
        sesion = self._sesion(tarea.red)
        opciones = tarea.opciones or OpcionesExtraccion()
        pendientes = tarea.publicaciones
        total = len(pendientes)
        if not total:
            self.log.emit("No hay publicaciones marcadas para extraer.")
            return

        self.log.emit(f"▶ Extrayendo comentarios de {total} publicacion(es)…")
        acumulado = 0
        con_comentarios = 0
        omitidas = 0

        for i, pub in enumerate(pendientes, start=1):
            if self._cancelar:
                self.log.emit("⏹ Extraccion detenida.")
                break
            self.progreso.emit(i - 1, total, f"Publicacion {i} de {total}")
            try:
                comentarios = extractor.extraer_comentarios(
                    sesion.pagina, pub, opciones, self._progreso()
                )
                nuevos = self.bd.guardar_comentarios(comentarios)
                pub.n_comentarios = len(comentarios)
                if pub.estado == "omitida":
                    # El extractor la descarto por fecha: respetamos su decision
                    omitidas += 1
                else:
                    pub.estado = "extraida"
                    pub.nota = "" if comentarios else "Sin comentarios de texto"
                    acumulado += len(comentarios)
                    if comentarios:
                        con_comentarios += 1
                self.publicacion_procesada.emit(pub, nuevos)
                self.log.emit(
                    f"   [{i}/{total}] {len(comentarios)} comentarios "
                    f"({nuevos} nuevos) · {pub.url}"
                )
            except Exception as e:
                pub.estado = "error"
                pub.nota = str(e)[:200]
                self.log.emit(f"   [{i}/{total}] ⚠ Fallo: {e}")
            finally:
                self.bd.guardar_publicacion(pub)

            # Pausa entre publicaciones: baja el riesgo de que la red te bloquee
            if i < total and not self._cancelar:
                espera = random.uniform(*self._pausa_entre_publicaciones)
                sesion.pagina.wait_for_timeout(int(espera * 1000))

        self.bd.recalcular_conteos()
        self.progreso.emit(total, total, "Extraccion terminada")
        resumen = (
            f"✅ Terminado. {con_comentarios} publicaciones con comentarios, "
            f"{acumulado} comentarios leidos en total."
        )
        if omitidas:
            resumen += f" ({omitidas} omitidas por quedar fuera del rango de fechas.)"
        self.log.emit(resumen)

    def _tarea_recargar(self, tarea: Tarea) -> None:
        sesion = self._sesion(tarea.red)
        url = sesion.recargar()
        self.log.emit(f"🔄 Pagina recargada: {url[:100]}")

    def _tarea_diagnostico(self, tarea: Tarea) -> None:
        extractor = registro.obtener(tarea.red)
        sesion = self._sesion(tarea.red)
        if hasattr(extractor, "guardar_diagnostico"):
            ruta = extractor.guardar_diagnostico(sesion.pagina, tarea.red)
            self.log.emit(f"🩺 Diagnostico guardado en: {ruta}")
        else:
            self.log.emit("Esta red no tiene diagnostico disponible.")

    def _tarea_cerrar(self, tarea: Tarea) -> None:
        sesion = self._sesiones.pop(tarea.red, None)
        if sesion:
            sesion.cerrar()
            self.log.emit("Navegador cerrado. La sesion queda guardada.")

    @staticmethod
    def _nombre_legible(tipo: str) -> str:
        return {
            "iniciar_sesion": "Abrir navegador",
            "verificar_sesion": "Comprobar sesion",
            "descubrir": "Buscar publicaciones",
            "extraer": "Extraer comentarios",
            "recargar": "Recargar pagina",
            "diagnostico": "Diagnostico",
            "cerrar_navegador": "Cerrar navegador",
        }.get(tipo, tipo)
