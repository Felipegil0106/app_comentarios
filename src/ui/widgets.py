"""Piezas visuales reutilizables."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class Tarjeta(QFrame):
    """Recuadro con un numero grande y un titulo pequeño.

    Se usa en el panel de resumen: "Comentarios totales: 1.245".
    """

    def __init__(self, titulo: str, valor: str = "0", parent=None):
        super().__init__(parent)
        self.setObjectName("tarjeta")
        self.setMinimumWidth(150)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(14, 12, 14, 12)
        caja.setSpacing(2)

        self.lbl_valor = QLabel(valor)
        self.lbl_valor.setObjectName("tarjeta_valor")
        self.lbl_valor.setAlignment(Qt.AlignLeft)

        self.lbl_titulo = QLabel(titulo.upper())
        self.lbl_titulo.setObjectName("tarjeta_titulo")
        self.lbl_titulo.setWordWrap(True)

        caja.addWidget(self.lbl_valor)
        caja.addWidget(self.lbl_titulo)

    def actualizar(self, valor: int | str) -> None:
        if isinstance(valor, int):
            valor = f"{valor:,}".replace(",", ".")
        self.lbl_valor.setText(str(valor))


def etiqueta_paso(texto: str) -> QLabel:
    """Titulo azul de un paso del formulario ('Paso 1 · Elige la red')."""
    lbl = QLabel(texto)
    lbl.setObjectName("paso")
    return lbl


def etiqueta_ayuda(texto: str) -> QLabel:
    """Texto gris pequeño de explicacion."""
    lbl = QLabel(texto)
    lbl.setObjectName("ayuda")
    lbl.setWordWrap(True)
    return lbl
