"""Pestaña 2 - Lista de publicaciones encontradas.

Aqui ves lo que la aplicacion encontro en el perfil y marcas con la casilla
de la izquierda cuales quieres que se procesen. Es la "segunda forma" de
elegir publicaciones, ademas del rango de fechas.
"""

from __future__ import annotations

import webbrowser
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.base_datos import BaseDatos
from ..core.modelos import Publicacion
from .hilo import HiloNavegador, Tarea
from .widgets import etiqueta_ayuda

COLUMNAS = ["", "Fecha", "Tipo", "Coment. extraidos", "Estado", "Contenido", "URL"]
COL_CHECK, COL_FECHA, COL_TIPO, COL_NCOM, COL_ESTADO, COL_TEXTO, COL_URL = range(7)


class PestanaPublicaciones(QWidget):
    def __init__(
        self,
        hilo: HiloNavegador,
        bd: BaseDatos,
        obtener_opciones: Callable,
        obtener_red: Callable[[], str],
        parent=None,
    ):
        super().__init__(parent)
        self.hilo = hilo
        self.bd = bd
        self.obtener_opciones = obtener_opciones
        self.obtener_red = obtener_red
        self.publicaciones: list[Publicacion] = []
        self._construir()

    # ------------------------------------------------------------- construccion

    def _construir(self) -> None:
        caja = QVBoxLayout(self)
        caja.setContentsMargins(18, 18, 18, 18)
        caja.setSpacing(12)

        caja.addWidget(
            etiqueta_ayuda(
                "Marca ☑ las publicaciones cuyos comentarios quieres descargar. "
                "Las que no tengan fecha detectada vienen desmarcadas: abrelas para "
                "comprobar antes de incluirlas.\n"
                "«Coment. extraidos» muestra «—» hasta que pulses Extraer: es el "
                "numero de comentarios ya descargados, no los que tiene la publicacion. "
                "Una fecha en amarillo con «aprox.» significa que no es exacta."
            )
        )

        # ---- barra de herramientas
        barra = QHBoxLayout()
        self.btn_todas = QPushButton("☑ Marcar todas")
        self.btn_ninguna = QPushButton("☐ Desmarcar todas")
        self.btn_invertir = QPushButton("⇄ Invertir")
        self.btn_con_fecha = QPushButton("Solo las que tienen fecha")
        self.btn_abrir = QPushButton("🌐 Abrir la seleccionada")
        self.btn_recargar = QPushButton("⟳ Recargar guardadas")

        self.buscador = QLineEdit()
        self.buscador.setPlaceholderText("Filtrar por texto o URL…")
        self.buscador.setClearButtonEnabled(True)
        self.buscador.textChanged.connect(self._filtrar)

        for b in (self.btn_todas, self.btn_ninguna, self.btn_invertir,
                  self.btn_con_fecha, self.btn_abrir, self.btn_recargar):
            barra.addWidget(b)
        barra.addStretch(1)
        barra.addWidget(QLabel("Buscar:"))
        barra.addWidget(self.buscador, 2)
        caja.addLayout(barra)

        self.btn_todas.clicked.connect(lambda: self._marcar_todas(True))
        self.btn_ninguna.clicked.connect(lambda: self._marcar_todas(False))
        self.btn_invertir.clicked.connect(self._invertir)
        self.btn_con_fecha.clicked.connect(self._marcar_con_fecha)
        self.btn_abrir.clicked.connect(self._abrir_seleccionada)
        self.btn_recargar.clicked.connect(self.recargar_desde_bd)

        # ---- tabla
        self.tabla = QTableWidget(0, len(COLUMNAS))
        self.tabla.setHorizontalHeaderLabels(COLUMNAS)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.setSortingEnabled(True)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.doubleClicked.connect(self._abrir_seleccionada)
        # Una sola conexion: si se conectara dentro de _pintar se acumularian
        # y el resumen se recalcularia decenas de veces por cada clic.
        self.tabla.itemChanged.connect(self._al_cambiar_casilla)

        cab = self.tabla.horizontalHeader()
        cab.setSectionResizeMode(COL_CHECK, QHeaderView.Fixed)
        self.tabla.setColumnWidth(COL_CHECK, 36)
        cab.setSectionResizeMode(COL_FECHA, QHeaderView.ResizeToContents)
        cab.setSectionResizeMode(COL_TIPO, QHeaderView.ResizeToContents)
        cab.setSectionResizeMode(COL_NCOM, QHeaderView.ResizeToContents)
        cab.setSectionResizeMode(COL_ESTADO, QHeaderView.ResizeToContents)
        cab.setSectionResizeMode(COL_TEXTO, QHeaderView.Stretch)
        cab.setSectionResizeMode(COL_URL, QHeaderView.Interactive)
        self.tabla.setColumnWidth(COL_URL, 320)
        caja.addWidget(self.tabla, 1)

        # ---- accion final
        grupo = QGroupBox("Extraer")
        fila = QHBoxLayout(grupo)
        self.lbl_resumen = QLabel("0 publicaciones · 0 marcadas")
        self.btn_extraer = QPushButton("⬇  Extraer comentarios de las marcadas")
        self.btn_extraer.setObjectName("principal")
        self.btn_extraer.clicked.connect(self._extraer)
        fila.addWidget(self.lbl_resumen)
        fila.addStretch(1)
        fila.addWidget(self.btn_extraer)
        caja.addWidget(grupo)

    # ------------------------------------------------------------------- datos

    def cargar(self, publicaciones: list[Publicacion]) -> None:
        """Vuelca en la tabla la lista de publicaciones encontradas."""
        self.publicaciones = list(publicaciones)
        self._pintar()

    def recargar_desde_bd(self) -> None:
        self.cargar(self.bd.publicaciones(self.obtener_red()))

    def _pintar(self) -> None:
        self.tabla.blockSignals(True)
        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(0)

        for pub in self.publicaciones:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)

            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            check.setCheckState(Qt.Checked if pub.seleccionada else Qt.Unchecked)
            self.tabla.setItem(fila, COL_CHECK, check)

            celdas = {
                COL_FECHA: pub.fecha_texto,
                COL_TIPO: pub.tipo,
                # Guion mientras no se haya extraido: un 0 hacia pensar que la
                # publicacion no tenia comentarios, cuando solo estaba pendiente.
                COL_NCOM: "—" if pub.estado == "pendiente" else str(pub.n_comentarios),
                COL_ESTADO: pub.estado + (f" · {pub.nota}" if pub.nota else ""),
                COL_TEXTO: pub.resumen or "(sin texto)",
                COL_URL: pub.url,
            }
            for col, valor in celdas.items():
                item = QTableWidgetItem(valor)
                item.setToolTip(valor)
                if col == COL_FECHA and (pub.fecha is None or pub.fecha_aproximada):
                    item.setForeground(QColor("#f0b429"))
                if col == COL_ESTADO and pub.estado == "error":
                    item.setForeground(QColor("#ef5f6b"))
                if col == COL_ESTADO and pub.estado == "extraida":
                    item.setForeground(QColor("#39c07f"))
                self.tabla.setItem(fila, col, item)

        self.tabla.setSortingEnabled(True)
        self.tabla.blockSignals(False)
        self._actualizar_resumen()

    def _al_cambiar_casilla(self, item: QTableWidgetItem) -> None:
        """Se dispara cuando el usuario marca/desmarca una casilla."""
        if item.column() != COL_CHECK:
            return
        pub = self._publicacion_de_fila(item.row())
        if pub:
            pub.seleccionada = item.checkState() == Qt.Checked
        self._actualizar_resumen()

    def _publicacion_de_fila(self, fila: int) -> Publicacion | None:
        item = self.tabla.item(fila, COL_URL)
        if not item:
            return None
        url = item.text()
        return next((p for p in self.publicaciones if p.url == url), None)

    def _sincronizar_marcas(self) -> None:
        """Copia el estado de las casillas de la tabla a los objetos Publicacion."""
        for fila in range(self.tabla.rowCount()):
            pub = self._publicacion_de_fila(fila)
            check = self.tabla.item(fila, COL_CHECK)
            if pub and check:
                pub.seleccionada = check.checkState() == Qt.Checked

    # ---------------------------------------------------------------- acciones

    def _marcar_todas(self, valor: bool) -> None:
        estado = Qt.Checked if valor else Qt.Unchecked
        self.tabla.blockSignals(True)
        for fila in range(self.tabla.rowCount()):
            if self.tabla.isRowHidden(fila):
                continue
            item = self.tabla.item(fila, COL_CHECK)
            if item:
                item.setCheckState(estado)
        self.tabla.blockSignals(False)
        self._sincronizar_marcas()
        self._actualizar_resumen()

    def _invertir(self) -> None:
        self.tabla.blockSignals(True)
        for fila in range(self.tabla.rowCount()):
            if self.tabla.isRowHidden(fila):
                continue
            item = self.tabla.item(fila, COL_CHECK)
            if item:
                item.setCheckState(
                    Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
                )
        self.tabla.blockSignals(False)
        self._sincronizar_marcas()
        self._actualizar_resumen()

    def _marcar_con_fecha(self) -> None:
        self.tabla.blockSignals(True)
        for fila in range(self.tabla.rowCount()):
            pub = self._publicacion_de_fila(fila)
            item = self.tabla.item(fila, COL_CHECK)
            if pub and item:
                item.setCheckState(Qt.Checked if pub.fecha else Qt.Unchecked)
        self.tabla.blockSignals(False)
        self._sincronizar_marcas()
        self._actualizar_resumen()

    def _abrir_seleccionada(self) -> None:
        fila = self.tabla.currentRow()
        if fila < 0:
            return
        item = self.tabla.item(fila, COL_URL)
        if item:
            webbrowser.open(item.text())

    def _filtrar(self, texto: str) -> None:
        t = texto.strip().lower()
        for fila in range(self.tabla.rowCount()):
            if not t:
                self.tabla.setRowHidden(fila, False)
                continue
            contenido = " ".join(
                (self.tabla.item(fila, c).text() if self.tabla.item(fila, c) else "")
                for c in (COL_TEXTO, COL_URL, COL_TIPO, COL_FECHA)
            ).lower()
            self.tabla.setRowHidden(fila, t not in contenido)
        self._actualizar_resumen()

    def _actualizar_resumen(self, *_) -> None:
        marcadas = 0
        visibles = 0
        for fila in range(self.tabla.rowCount()):
            if self.tabla.isRowHidden(fila):
                continue
            visibles += 1
            item = self.tabla.item(fila, COL_CHECK)
            if item and item.checkState() == Qt.Checked:
                marcadas += 1
        self.lbl_resumen.setText(
            f"{self.tabla.rowCount()} publicaciones encontradas · "
            f"{visibles} visibles · {marcadas} marcadas para extraer"
        )
        self.btn_extraer.setEnabled(marcadas > 0)

    def _extraer(self) -> None:
        self._sincronizar_marcas()
        elegidas = [p for p in self.publicaciones if p.seleccionada]
        if not elegidas:
            return
        self.hilo.encolar(
            Tarea(
                tipo="extraer",
                red=self.obtener_red(),
                opciones=self.obtener_opciones(),
                publicaciones=elegidas,
            )
        )

    # ------------------------------------------------- actualizacion en directo

    def actualizar_publicacion(self, pub: Publicacion) -> None:
        """Refresca una fila cuando el hilo termina de procesarla."""
        for fila in range(self.tabla.rowCount()):
            item = self.tabla.item(fila, COL_URL)
            if item and item.text() == pub.url:
                self.tabla.item(fila, COL_NCOM).setText(str(pub.n_comentarios))
                estado = self.tabla.item(fila, COL_ESTADO)
                estado.setText(pub.estado + (f" · {pub.nota}" if pub.nota else ""))
                estado.setForeground(
                    QColor("#ef5f6b" if pub.estado == "error" else "#39c07f")
                )
                if self.tabla.item(fila, COL_FECHA):
                    self.tabla.item(fila, COL_FECHA).setText(pub.fecha_texto)
                break

    def marcar_ocupado(self, ocupado: bool) -> None:
        self.btn_extraer.setEnabled(not ocupado and self.tabla.rowCount() > 0)
