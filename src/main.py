"""Punto de entrada de la aplicacion.

Para arrancar:  doble clic en iniciar.bat
O desde consola: python -m src.main
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

# Permite ejecutar tanto `python -m src.main` como `python src/main.py`
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt                       # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from src.core.rutas import asegurar_carpetas       # noqa: E402


def _comprobar_dependencias() -> str:
    """Avisa con un mensaje claro si falta algo por instalar."""
    faltan = []
    try:
        import playwright  # noqa: F401
    except ImportError:
        faltan.append("playwright")
    try:
        import pandas  # noqa: F401
    except ImportError:
        faltan.append("pandas")
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        faltan.append("openpyxl")
    if faltan:
        return (
            "Faltan librerias por instalar: " + ", ".join(faltan) + "\n\n"
            "Cierra esta ventana y ejecuta 'instalar.bat' (doble clic)."
        )
    return ""


def main() -> int:
    asegurar_carpetas()

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Extractor de Comentarios")

    problema = _comprobar_dependencias()
    if problema:
        QMessageBox.critical(None, "Faltan dependencias", problema)
        return 1

    from src.ui.ventana import VentanaPrincipal

    try:
        ventana = VentanaPrincipal()
    except Exception:
        QMessageBox.critical(
            None,
            "Error al arrancar",
            "La aplicacion no pudo iniciarse:\n\n" + traceback.format_exc(),
        )
        return 1

    ventana.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
