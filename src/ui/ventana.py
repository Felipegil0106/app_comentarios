"""Ventana principal: junta las cuatro pestañas y conecta todo."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtWidgets import QApplication

from ..core.base_datos import BaseDatos
from ..core.modelos import Publicacion
from .estilos import QSS
from .hilo import HiloNavegador, Tarea
from .pestana_ayuda import PestanaAyuda
from .pestana_extraer import MODO_AUTOMATICO, PestanaExtraer
from .pestana_publicaciones import PestanaPublicaciones
from .pestana_resultados import PestanaResultados

TITULO = "Extractor de Comentarios de Redes Sociales"


class VentanaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(TITULO)
        self.resize(1320, 900)
        self.setStyleSheet(QSS)

        self.bd = BaseDatos()
        self.hilo = HiloNavegador(self.bd)
        self.hilo.start()
        self._cerrado = False

        # Red de seguridad: pase lo que pase al salir (cerrar ventana, Ctrl+C,
        # cierre de sesion de Windows), el hilo del navegador se detiene. Sin
        # esto el proceso se quedaria colgado en segundo plano.
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._apagar)

        self._construir()
        self._conectar()
        self.statusBar().showMessage("Listo. Empieza por la pestaña «1 · Extraer».")

    # ------------------------------------------------------------- construccion

    def _construir(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        caja = QVBoxLayout(central)
        caja.setContentsMargins(14, 12, 14, 10)
        caja.setSpacing(10)

        # Cabecera
        cabecera = QHBoxLayout()
        titulo = QLabel(TITULO)
        titulo.setObjectName("titulo")
        subtitulo = QLabel(
            "Descarga los comentarios de texto de las publicaciones de un perfil, "
            "por rango de fechas."
        )
        subtitulo.setObjectName("subtitulo")
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(titulo)
        col.addWidget(subtitulo)
        cabecera.addLayout(col)
        cabecera.addStretch(1)
        caja.addLayout(cabecera)

        # Pestañas
        self.pestanas = QTabWidget()
        self.p_extraer = PestanaExtraer(self.hilo)
        self.p_publicaciones = PestanaPublicaciones(
            self.hilo,
            self.bd,
            obtener_opciones=self.p_extraer.opciones_actuales,
            obtener_red=lambda: self.p_extraer.red_actual,
        )
        self.p_resultados = PestanaResultados(self.bd)
        self.p_ayuda = PestanaAyuda()

        self.pestanas.addTab(self.p_extraer, "1 · Extraer")
        self.pestanas.addTab(self.p_publicaciones, "2 · Publicaciones")
        self.pestanas.addTab(self.p_resultados, "3 · Resultados")
        self.pestanas.addTab(self.p_ayuda, "? · Ayuda")
        caja.addWidget(self.pestanas, 1)

        # Al abrir, mostramos lo que ya hubiera guardado de sesiones anteriores
        self.p_publicaciones.recargar_desde_bd()

    # ---------------------------------------------------------------- conexiones

    def _conectar(self) -> None:
        self.hilo.log.connect(self.p_extraer.escribir)
        self.hilo.log.connect(lambda m: self.statusBar().showMessage(m, 8000))
        self.hilo.progreso.connect(self.p_extraer.actualizar_progreso)
        self.hilo.estado_sesion.connect(self.p_extraer.actualizar_sesion)
        self.hilo.publicaciones_listas.connect(self._publicaciones_listas)
        self.hilo.publicacion_procesada.connect(self._publicacion_procesada)
        self.hilo.tarea_inicia.connect(
            lambda n: self.statusBar().showMessage(f"⏳ {n}…")
        )
        self.hilo.tarea_termina.connect(self._tarea_termina)
        self.hilo.ocupado.connect(self.p_extraer.marcar_ocupado)
        self.hilo.ocupado.connect(self.p_publicaciones.marcar_ocupado)

    # -------------------------------------------------------------- reacciones

    def _publicaciones_listas(self, publicaciones: list[Publicacion]) -> None:
        self.p_publicaciones.cargar(publicaciones)

        if self.p_extraer.modo == MODO_AUTOMATICO:
            elegidas = [p for p in publicaciones if p.seleccionada]
            if elegidas:
                self.p_extraer.escribir(
                    f"Modo automatico: extrayendo {len(elegidas)} publicaciones "
                    "sin pedir confirmacion."
                )
                opciones = self.p_extraer.opciones_actuales()
                # Nadie reviso la lista a mano, asi que al abrir cada publicacion
                # volvemos a comprobar su fecha real antes de leer comentarios.
                opciones.verificar_rango_al_extraer = True
                self.hilo.encolar(
                    Tarea(
                        tipo="extraer",
                        red=self.p_extraer.red_actual,
                        opciones=opciones,
                        publicaciones=elegidas,
                    )
                )
            else:
                self.p_extraer.escribir(
                    "No hubo publicaciones dentro del rango. Revisa la pestaña 2."
                )
                self.pestanas.setCurrentWidget(self.p_publicaciones)
        else:
            self.pestanas.setCurrentWidget(self.p_publicaciones)

    def _publicacion_procesada(self, pub: Publicacion, nuevos: int) -> None:
        self.p_publicaciones.actualizar_publicacion(pub)

    def _tarea_termina(self, nombre: str, ok: bool, mensaje: str) -> None:
        if nombre == "Extraer comentarios":
            self.p_resultados.refrescar()
            if ok:
                self.pestanas.setCurrentWidget(self.p_resultados)
        if not ok:
            self.statusBar().showMessage(f"❌ {nombre}: {mensaje}", 15000)
        else:
            self.statusBar().showMessage(f"✅ {nombre}: {mensaje}", 8000)

    # -------------------------------------------------------------------- cierre

    def _apagar(self) -> None:
        """Cierra hilo y base de datos. Se puede llamar varias veces sin problema."""
        if self._cerrado:
            return
        self._cerrado = True
        if self.hilo.isRunning():
            self.hilo.detener_todo()
            if not self.hilo.wait(20000):
                self.hilo.terminate()
                self.hilo.wait(3000)
        try:
            self.bd.cerrar()
        except Exception:
            pass

    def closeEvent(self, evento) -> None:
        # Solo preguntamos si hay trabajo a medias. Si no hay nada corriendo,
        # cerrar debe ser inmediato (y no bloquear el apagado de Windows).
        if not self._cerrado and self.hilo.esta_ocupado:
            respuesta = QMessageBox.question(
                self,
                "Hay una extraccion en curso",
                "Todavia se estan extrayendo comentarios.\n"
                "Si sales ahora, se detendra a medias.\n"
                "Lo ya extraido queda guardado.\n\n¿Salir de todos modos?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if respuesta != QMessageBox.Yes:
                evento.ignore()
                return
        self._apagar()
        evento.accept()
