"""Pestaña 3 - Resultados, filtros y exportacion.

Lo importante de esta pantalla:
  * Los contadores de arriba se recalculan CADA VEZ que cambias un filtro.
    Si filtras por una URL, veras los comentarios de esa publicacion.
  * Lo que exportas es exactamente lo que estas viendo.
"""

from __future__ import annotations

import webbrowser
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.base_datos import BaseDatos
from ..core.exportar import exportar_csv, exportar_excel
from .widgets import Tarjeta, etiqueta_ayuda

COLUMNAS = ["Fecha coment.", "Autor", "Comentario", "Tipo", "Fecha public.", "URL publicacion"]
C_FECHA, C_AUTOR, C_TEXTO, C_TIPO, C_FPUB, C_URL = range(6)

TODAS = "__todas__"


class PestanaResultados(QWidget):
    def __init__(self, bd: BaseDatos, parent=None):
        super().__init__(parent)
        self.bd = bd
        self.filas: list[dict] = []
        self._construir()
        self.refrescar()

    # ------------------------------------------------------------- construccion

    def _construir(self) -> None:
        caja = QVBoxLayout(self)
        caja.setContentsMargins(18, 18, 18, 18)
        caja.setSpacing(12)

        caja.addLayout(self._panel_tarjetas())
        caja.addWidget(self._panel_filtros())

        divisor = QSplitter(Qt.Vertical)
        divisor.addWidget(self._tabla())
        divisor.addWidget(self._detalle())
        divisor.setStretchFactor(0, 4)
        divisor.setStretchFactor(1, 1)
        caja.addWidget(divisor, 1)

        caja.addWidget(self._panel_exportar())

    def _panel_tarjetas(self) -> QHBoxLayout:
        fila = QHBoxLayout()
        fila.setSpacing(10)
        self.t_publicaciones = Tarjeta("Publicaciones con comentarios")
        self.t_comentarios = Tarjeta("Comentarios mostrados")
        self.t_autores = Tarjeta("Autores unicos")
        self.t_respuestas = Tarjeta("Son respuestas")
        self.t_promedio = Tarjeta("Promedio por publicacion")
        for t in (self.t_publicaciones, self.t_comentarios, self.t_autores,
                  self.t_respuestas, self.t_promedio):
            fila.addWidget(t)
        return fila

    def _panel_filtros(self) -> QGroupBox:
        grupo = QGroupBox("Filtros — los contadores de arriba se actualizan solos")
        caja = QVBoxLayout(grupo)

        arriba = QHBoxLayout()
        self.cmb_red = QComboBox()
        self.cmb_red.addItem("Todas las redes", TODAS)
        for r in ("facebook", "instagram", "tiktok", "x"):
            self.cmb_red.addItem(r.capitalize(), r)

        self.cmb_url = QComboBox()
        self.cmb_url.setMinimumWidth(420)
        self.cmb_url.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)

        arriba.addWidget(QLabel("Red:"))
        arriba.addWidget(self.cmb_red)
        arriba.addSpacing(10)
        arriba.addWidget(QLabel("Publicacion (URL):"))
        arriba.addWidget(self.cmb_url, 1)
        self.btn_abrir_url = QPushButton("🌐 Abrir")
        arriba.addWidget(self.btn_abrir_url)
        caja.addLayout(arriba)

        abajo = QHBoxLayout()
        self.txt_buscar = QLineEdit()
        self.txt_buscar.setPlaceholderText("Buscar palabra dentro del comentario…")
        self.txt_buscar.setClearButtonEnabled(True)
        self.txt_autor = QLineEdit()
        self.txt_autor.setPlaceholderText("Filtrar por autor…")
        self.txt_autor.setClearButtonEnabled(True)
        self.chk_solo_respuestas = QCheckBox("Solo respuestas")
        self.chk_sin_respuestas = QCheckBox("Sin respuestas")
        self.btn_limpiar = QPushButton("Limpiar filtros")

        abajo.addWidget(QLabel("Texto:"))
        abajo.addWidget(self.txt_buscar, 2)
        abajo.addWidget(QLabel("Autor:"))
        abajo.addWidget(self.txt_autor, 1)
        abajo.addWidget(self.chk_solo_respuestas)
        abajo.addWidget(self.chk_sin_respuestas)
        abajo.addWidget(self.btn_limpiar)
        caja.addLayout(abajo)

        # conexiones
        self.cmb_red.currentIndexChanged.connect(self._recargar_urls)
        self.cmb_url.currentIndexChanged.connect(self.aplicar_filtros)
        self.txt_buscar.textChanged.connect(self.aplicar_filtros)
        self.txt_autor.textChanged.connect(self.aplicar_filtros)
        self.chk_solo_respuestas.toggled.connect(self._exclusivo_respuestas)
        self.chk_sin_respuestas.toggled.connect(self._exclusivo_sin_respuestas)
        self.btn_limpiar.clicked.connect(self._limpiar_filtros)
        self.btn_abrir_url.clicked.connect(self._abrir_url_filtrada)
        return grupo

    def _tabla(self) -> QTableWidget:
        self.tabla = QTableWidget(0, len(COLUMNAS))
        self.tabla.setHorizontalHeaderLabels(COLUMNAS)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.setSortingEnabled(True)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.itemSelectionChanged.connect(self._mostrar_detalle)
        self.tabla.doubleClicked.connect(self._abrir_publicacion_de_fila)

        cab = self.tabla.horizontalHeader()
        cab.setSectionResizeMode(C_FECHA, QHeaderView.ResizeToContents)
        cab.setSectionResizeMode(C_AUTOR, QHeaderView.Interactive)
        cab.setSectionResizeMode(C_TEXTO, QHeaderView.Stretch)
        cab.setSectionResizeMode(C_TIPO, QHeaderView.ResizeToContents)
        cab.setSectionResizeMode(C_FPUB, QHeaderView.ResizeToContents)
        cab.setSectionResizeMode(C_URL, QHeaderView.Interactive)
        self.tabla.setColumnWidth(C_AUTOR, 180)
        self.tabla.setColumnWidth(C_URL, 300)
        return self.tabla

    def _detalle(self) -> QWidget:
        contenedor = QWidget()
        caja = QVBoxLayout(contenedor)
        caja.setContentsMargins(0, 6, 0, 0)

        fila = QHBoxLayout()
        fila.addWidget(QLabel("Comentario completo:"))
        fila.addStretch(1)
        self.btn_copiar = QPushButton("📋 Copiar")
        self.btn_copiar.clicked.connect(self._copiar_detalle)
        fila.addWidget(self.btn_copiar)
        caja.addLayout(fila)

        self.detalle = QPlainTextEdit()
        self.detalle.setReadOnly(True)
        self.detalle.setMinimumHeight(90)
        self.detalle.setPlaceholderText(
            "Selecciona una fila para ver el comentario completo."
        )
        caja.addWidget(self.detalle)
        return contenedor

    def _panel_exportar(self) -> QGroupBox:
        grupo = QGroupBox("Descargar")
        fila = QHBoxLayout(grupo)

        self.btn_csv = QPushButton("⬇ Descargar CSV (lo que veo)")
        self.btn_excel = QPushButton("⬇ Descargar Excel (lo que veo)")
        self.btn_excel_todo = QPushButton("⬇ Descargar Excel (todo)")
        self.btn_borrar = QPushButton("🗑 Borrar datos guardados")
        self.btn_borrar.setObjectName("peligro")

        self.btn_csv.clicked.connect(lambda: self._exportar("csv", False))
        self.btn_excel.clicked.connect(lambda: self._exportar("excel", False))
        self.btn_excel_todo.clicked.connect(lambda: self._exportar("excel", True))
        self.btn_borrar.clicked.connect(self._borrar)

        fila.addWidget(self.btn_csv)
        fila.addWidget(self.btn_excel)
        fila.addWidget(self.btn_excel_todo)
        fila.addStretch(1)
        fila.addWidget(
            etiqueta_ayuda(
                "El Excel trae 3 hojas: comentarios, resumen por publicacion y top autores."
            )
        )
        fila.addWidget(self.btn_borrar)
        return grupo

    # ---------------------------------------------------------------- filtrado

    @property
    def red_filtro(self) -> str | None:
        valor = self.cmb_red.currentData()
        return None if valor == TODAS else valor

    @property
    def url_filtro(self) -> str | None:
        valor = self.cmb_url.currentData()
        return None if valor in (TODAS, None) else valor

    def refrescar(self) -> None:
        """Vuelve a leer todo de la base de datos (tras una extraccion)."""
        self._recargar_urls()

    def _recargar_urls(self) -> None:
        """Rellena el desplegable de URLs con las publicaciones que SI tienen
        comentarios, indicando cuantos tiene cada una."""
        actual = self.cmb_url.currentData()
        self.cmb_url.blockSignals(True)
        self.cmb_url.clear()

        pares = self.bd.urls_con_comentarios()
        if self.red_filtro:
            urls_red = {p.url for p in self.bd.publicaciones(self.red_filtro)}
            pares = [(u, n) for u, n in pares if u in urls_red]

        total = sum(n for _, n in pares)
        self.cmb_url.addItem(
            f"Todas las publicaciones  ({len(pares)} publicaciones · {total} comentarios)",
            TODAS,
        )
        for url, n in pares:
            corta = url.replace("https://www.facebook.com", "fb")
            if len(corta) > 90:
                corta = corta[:87] + "…"
            self.cmb_url.addItem(f"[{n:>4}]  {corta}", url)

        # Intentamos conservar la seleccion anterior
        if actual and actual != TODAS:
            idx = self.cmb_url.findData(actual)
            if idx >= 0:
                self.cmb_url.setCurrentIndex(idx)
        self.cmb_url.blockSignals(False)
        self.aplicar_filtros()

    def _exclusivo_respuestas(self, marcado: bool) -> None:
        if marcado:
            self.chk_sin_respuestas.setChecked(False)
        self.aplicar_filtros()

    def _exclusivo_sin_respuestas(self, marcado: bool) -> None:
        if marcado:
            self.chk_solo_respuestas.setChecked(False)
        self.aplicar_filtros()

    def _limpiar_filtros(self) -> None:
        self.txt_buscar.clear()
        self.txt_autor.clear()
        self.chk_solo_respuestas.setChecked(False)
        self.chk_sin_respuestas.setChecked(False)
        self.cmb_url.setCurrentIndex(0)
        self.cmb_red.setCurrentIndex(0)

    def aplicar_filtros(self) -> None:
        solo_respuestas: bool | None = None
        if self.chk_solo_respuestas.isChecked():
            solo_respuestas = True
        elif self.chk_sin_respuestas.isChecked():
            solo_respuestas = False

        self.filas = self.bd.comentarios(
            url=self.url_filtro,
            red=self.red_filtro,
            busqueda=self.txt_buscar.text().strip(),
            autor=self.txt_autor.text().strip(),
            solo_respuestas=solo_respuestas,
        )
        self._pintar_tabla()
        self._actualizar_tarjetas()

    def _pintar_tabla(self) -> None:
        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(0)
        for f in self.filas:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            texto = f.get("texto", "")
            valores = {
                C_FECHA: self._fecha_corta(f.get("fecha")),
                C_AUTOR: f.get("autor", ""),
                C_TEXTO: " ".join(texto.split())[:300],
                C_TIPO: "respuesta" if f.get("es_respuesta") else "comentario",
                C_FPUB: self._fecha_corta(f.get("fecha_publicacion")),
                C_URL: f.get("publicacion_url", ""),
            }
            for col, valor in valores.items():
                item = QTableWidgetItem(valor)
                if col == C_TEXTO:
                    item.setToolTip(texto[:1500])
                    item.setData(Qt.UserRole, texto)
                self.tabla.setItem(fila, col, item)
        self.tabla.setSortingEnabled(True)

    def _actualizar_tarjetas(self) -> None:
        urls = {f.get("publicacion_url") for f in self.filas if f.get("publicacion_url")}
        autores = {f.get("autor") for f in self.filas}
        respuestas = sum(1 for f in self.filas if f.get("es_respuesta"))
        total = len(self.filas)
        promedio = (total / len(urls)) if urls else 0

        self.t_publicaciones.actualizar(len(urls))
        self.t_comentarios.actualizar(total)
        self.t_autores.actualizar(len(autores))
        self.t_respuestas.actualizar(respuestas)
        self.t_promedio.actualizar(f"{promedio:.1f}")

    @staticmethod
    def _fecha_corta(valor) -> str:
        if not valor:
            return ""
        try:
            return datetime.fromisoformat(str(valor)).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return str(valor)

    # ---------------------------------------------------------------- acciones

    def _mostrar_detalle(self) -> None:
        fila = self.tabla.currentRow()
        if fila < 0:
            return
        item = self.tabla.item(fila, C_TEXTO)
        autor = self.tabla.item(fila, C_AUTOR)
        url = self.tabla.item(fila, C_URL)
        if not item:
            return
        completo = item.data(Qt.UserRole) or item.text()
        cabecera = f"{autor.text() if autor else ''}\n{url.text() if url else ''}\n\n"
        self.detalle.setPlainText(cabecera + completo)

    def _copiar_detalle(self) -> None:
        QGuiApplication.clipboard().setText(self.detalle.toPlainText())

    def _abrir_publicacion_de_fila(self) -> None:
        fila = self.tabla.currentRow()
        if fila < 0:
            return
        item = self.tabla.item(fila, C_URL)
        if item and item.text():
            webbrowser.open(item.text())

    def _abrir_url_filtrada(self) -> None:
        if self.url_filtro:
            webbrowser.open(self.url_filtro)
        else:
            QMessageBox.information(
                self, "Abrir publicacion",
                "Primero elige una publicacion concreta en el desplegable.",
            )

    def _exportar(self, formato: str, todo: bool) -> None:
        filas = self.bd.comentarios() if todo else self.filas
        if not filas:
            QMessageBox.warning(
                self, "Nada que descargar",
                "No hay comentarios que coincidan con los filtros actuales.",
            )
            return

        marca = datetime.now().strftime("%Y%m%d_%H%M")
        sufijo = "todo" if todo else "filtrado"
        if formato == "csv":
            nombre, _ = QFileDialog.getSaveFileName(
                self, "Guardar CSV",
                str(Path.home() / "Downloads" / f"comentarios_{sufijo}_{marca}.csv"),
                "Archivo CSV (*.csv)",
            )
            if not nombre:
                return
            destino = exportar_csv(filas, nombre)
        else:
            nombre, _ = QFileDialog.getSaveFileName(
                self, "Guardar Excel",
                str(Path.home() / "Downloads" / f"comentarios_{sufijo}_{marca}.xlsx"),
                "Libro de Excel (*.xlsx)",
            )
            if not nombre:
                return
            destino = exportar_excel(filas, nombre)

        respuesta = QMessageBox.question(
            self, "Descarga lista",
            f"Se guardaron {len(filas)} comentarios en:\n{destino}\n\n"
            "¿Quieres abrir la carpeta?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if respuesta == QMessageBox.Yes:
            webbrowser.open(str(Path(destino).parent))

    def _borrar(self) -> None:
        respuesta = QMessageBox.question(
            self, "Borrar datos",
            "Se borraran TODAS las publicaciones y comentarios guardados.\n"
            "Esta accion no se puede deshacer.\n\n¿Seguro?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if respuesta == QMessageBox.Yes:
            self.bd.borrar_todo()
            self.refrescar()
