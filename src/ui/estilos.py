"""Apariencia de la aplicacion (colores, bordes, tipografia).

Esta escrito en QSS, que es como el CSS de las paginas web pero para Qt.
Si quieres cambiar los colores, toca solo la tabla COLORES de aqui abajo.
"""

COLORES = {
    "fondo": "#0f1420",
    "panel": "#171d2b",
    "panel_claro": "#1e2637",
    "borde": "#2a3448",
    "texto": "#e6ebf5",
    "texto_suave": "#98a4bb",
    "acento": "#4c8dff",
    "acento_oscuro": "#356fd6",
    "exito": "#39c07f",
    "aviso": "#f0b429",
    "error": "#ef5f6b",
}

QSS = """
* {{
    font-family: "Segoe UI", "Inter", Arial, sans-serif;
    font-size: 13px;
}}

QWidget {{
    background: {fondo};
    color: {texto};
}}

QLabel#titulo {{
    font-size: 22px;
    font-weight: 700;
    color: {texto};
}}
QLabel#subtitulo {{
    color: {texto_suave};
    font-size: 13px;
}}
QLabel#paso {{
    font-size: 14px;
    font-weight: 600;
    color: {acento};
    padding-top: 4px;
}}
QLabel#ayuda {{
    color: {texto_suave};
    font-size: 12px;
}}

/* ---------------------------------------------------------------- pestañas */
QTabWidget::pane {{
    border: 1px solid {borde};
    border-radius: 10px;
    background: {panel};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {texto_suave};
    padding: 10px 20px;
    margin-right: 4px;
    border: 1px solid transparent;
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    background: {panel};
    color: {texto};
    border-color: {borde};
    border-bottom-color: {panel};
}}
QTabBar::tab:hover:!selected {{
    color: {texto};
}}

/* ----------------------------------------------------------------- grupos */
QGroupBox {{
    background: {panel_claro};
    border: 1px solid {borde};
    border-radius: 10px;
    margin-top: 14px;
    padding: 14px 12px 12px 12px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {acento};
}}

/* ---------------------------------------------------------------- botones */
QPushButton {{
    background: {panel_claro};
    color: {texto};
    border: 1px solid {borde};
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
}}
QPushButton:hover {{ border-color: {acento}; }}
QPushButton:pressed {{ background: {borde}; }}
QPushButton:disabled {{ color: {texto_suave}; border-color: {borde}; }}

QPushButton#principal {{
    background: {acento};
    border-color: {acento};
    color: #ffffff;
    padding: 11px 22px;
    font-size: 14px;
}}
QPushButton#principal:hover {{ background: {acento_oscuro}; }}
QPushButton#principal:disabled {{ background: {borde}; border-color: {borde}; }}

QPushButton#peligro {{ border-color: {error}; color: {error}; }}
QPushButton#peligro:hover {{ background: {error}; color: #ffffff; }}

/* ---------------------------------------------------- campos de formulario */
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDateEdit {{
    background: {fondo};
    border: 1px solid {borde};
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: {acento};
}}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDateEdit:focus {{
    border-color: {acento};
}}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {panel_claro};
    border: 1px solid {borde};
    selection-background-color: {acento};
    outline: none;
}}

QRadioButton, QCheckBox {{ padding: 4px 2px; spacing: 8px; }}
QRadioButton::indicator, QCheckBox::indicator {{ width: 16px; height: 16px; }}

/* ---------------------------------------------------------------- tablas */
QTableView {{
    background: {fondo};
    alternate-background-color: {panel};
    border: 1px solid {borde};
    border-radius: 8px;
    gridline-color: {borde};
    selection-background-color: {acento_oscuro};
    selection-color: #ffffff;
}}
QHeaderView::section {{
    background: {panel_claro};
    color: {texto_suave};
    border: none;
    border-right: 1px solid {borde};
    border-bottom: 1px solid {borde};
    padding: 8px;
    font-weight: 600;
}}
QTableView::item {{ padding: 4px 6px; }}

/* ------------------------------------------------------------- indicadores */
QProgressBar {{
    background: {fondo};
    border: 1px solid {borde};
    border-radius: 8px;
    height: 20px;
    text-align: center;
    color: {texto};
}}
QProgressBar::chunk {{ background: {acento}; border-radius: 7px; }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {borde}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {acento}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {borde}; border-radius: 5px; min-width: 30px; }}

QStatusBar {{ background: {panel}; color: {texto_suave}; border-top: 1px solid {borde}; }}

/* --------------------------------------------------- tarjetas de estadistica */
QFrame#tarjeta {{
    background: {panel_claro};
    border: 1px solid {borde};
    border-radius: 12px;
}}
QLabel#tarjeta_valor {{ font-size: 26px; font-weight: 700; color: {acento}; }}
QLabel#tarjeta_titulo {{ font-size: 11px; color: {texto_suave}; font-weight: 600; }}

QPlainTextEdit#registro {{
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
    background: #0b0f18;
    color: #cbd5e6;
}}
""".format(**COLORES)
