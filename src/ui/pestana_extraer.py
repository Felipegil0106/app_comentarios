"""Pestaña 1 - Configurar y lanzar la extraccion.

Aqui el usuario elige la red, inicia sesion, pega la URL del perfil,
escoge el rango de fechas y decide COMO quiere elegir las publicaciones.
"""

from __future__ import annotations

from datetime import datetime, time

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..redes import registro
from ..redes.base import OpcionesExtraccion
from .hilo import HiloNavegador, Tarea
from .widgets import etiqueta_ayuda, etiqueta_paso

MODO_AUTOMATICO = "automatico"
MODO_REVISAR = "revisar"
MODO_MANUAL = "manual"


class PestanaExtraer(QWidget):
    """Formulario principal de la aplicacion."""

    ir_a_publicaciones = Signal()

    def __init__(self, hilo: HiloNavegador, parent=None):
        super().__init__(parent)
        self.hilo = hilo
        self._construir()
        self._conectar()

    # ------------------------------------------------------------- construccion

    def _construir(self) -> None:
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        contenido = QWidget()
        scroll.setWidget(contenido)
        raiz.addWidget(scroll)

        caja = QVBoxLayout(contenido)
        caja.setContentsMargins(18, 18, 18, 18)
        caja.setSpacing(14)

        caja.addWidget(self._grupo_red())
        caja.addWidget(self._grupo_perfil())
        caja.addWidget(self._grupo_fechas())
        caja.addWidget(self._grupo_modo())
        caja.addWidget(self._grupo_avanzado())
        caja.addWidget(self._grupo_accion())
        caja.addStretch(1)

    # -------- Paso 1: red social + sesion
    def _grupo_red(self) -> QGroupBox:
        grupo = QGroupBox("Paso 1 · Red social y sesion")
        caja = QVBoxLayout(grupo)

        fila = QHBoxLayout()
        self.cmb_red = QComboBox()
        for extractor in registro.listar():
            etiqueta = extractor.etiqueta
            if not extractor.implementado:
                etiqueta += "  (en construccion)"
            self.cmb_red.addItem(etiqueta, extractor.nombre)
        self.cmb_red.setMinimumWidth(240)

        self.lbl_sesion = QLabel("🔴  Sesion no comprobada")
        self.lbl_sesion.setMinimumWidth(220)

        self.btn_login = QPushButton("Abrir navegador e iniciar sesion")
        self.btn_verificar = QPushButton("Ya inicie sesion — comprobar")

        fila.addWidget(QLabel("Red:"))
        fila.addWidget(self.cmb_red)
        fila.addSpacing(16)
        fila.addWidget(self.lbl_sesion)
        fila.addStretch(1)
        fila.addWidget(self.btn_login)
        fila.addWidget(self.btn_verificar)
        caja.addLayout(fila)

        # Botones de rescate: cuando una pantalla del navegador se queda colgada
        rescate = QHBoxLayout()
        self.btn_recargar = QPushButton("🔄 Recargar la pagina del navegador")
        self.btn_recargar.setToolTip(
            "Si una pantalla de Facebook se queda en blanco, pulsa esto.\n"
            "Casi siempre se arregla recargando, sin perder lo que llevabas."
        )
        self.btn_cerrar_navegador = QPushButton("✖ Cerrar navegador")
        self.btn_cerrar_navegador.setToolTip(
            "Cierra la ventana del navegador. La sesion queda guardada:\n"
            "la proxima vez no tendras que volver a iniciar sesion."
        )
        rescate.addStretch(1)
        rescate.addWidget(self.btn_recargar)
        rescate.addWidget(self.btn_cerrar_navegador)
        caja.addLayout(rescate)

        self.lbl_ayuda_red = etiqueta_ayuda("")
        caja.addWidget(self.lbl_ayuda_red)
        caja.addWidget(
            etiqueta_ayuda(
                "🔒 La aplicacion nunca te pide ni guarda tu contraseña: la escribes "
                "directamente en la ventana del navegador que se abre. La sesion queda "
                "guardada en tu equipo para no repetirlo cada vez."
            )
        )
        return grupo

    # -------- Paso 2: URL del perfil
    def _grupo_perfil(self) -> QGroupBox:
        grupo = QGroupBox("Paso 2 · Perfil del que quieres extraer")
        caja = QVBoxLayout(grupo)

        self.txt_perfil = QLineEdit()
        self.txt_perfil.setPlaceholderText(
            "https://www.facebook.com/nombredelapagina"
        )
        self.txt_perfil.setClearButtonEnabled(True)
        caja.addWidget(self.txt_perfil)
        caja.addWidget(
            etiqueta_ayuda(
                "Pega aqui la direccion del perfil o pagina. Sirve tambien "
                "https://www.facebook.com/profile.php?id=100001234567890"
            )
        )
        return grupo

    # -------- Paso 3: rango de fechas
    def _grupo_fechas(self) -> QGroupBox:
        grupo = QGroupBox("Paso 3 · Rango de fechas de las publicaciones")
        caja = QVBoxLayout(grupo)

        fila = QHBoxLayout()
        hoy = QDate.currentDate()

        self.fecha_desde = QDateEdit(hoy.addDays(-30))
        self.fecha_hasta = QDateEdit(hoy)
        for campo in (self.fecha_desde, self.fecha_hasta):
            campo.setCalendarPopup(True)
            campo.setDisplayFormat("dd/MM/yyyy")
            campo.setMinimumWidth(140)

        fila.addWidget(QLabel("Desde:"))
        fila.addWidget(self.fecha_desde)
        fila.addSpacing(12)
        fila.addWidget(QLabel("Hasta:"))
        fila.addWidget(self.fecha_hasta)
        fila.addStretch(1)
        caja.addLayout(fila)

        # Atajos para no tener que abrir el calendario
        atajos = QHBoxLayout()
        atajos.addWidget(QLabel("Atajos:"))
        for texto, dias in (
            ("Ultimos 7 dias", 7),
            ("Ultimos 30 dias", 30),
            ("Ultimos 90 dias", 90),
            ("Este año", -1),
            ("Todo", -2),
        ):
            btn = QPushButton(texto)
            btn.clicked.connect(lambda _=False, d=dias: self._atajo_fecha(d))
            atajos.addWidget(btn)
        atajos.addStretch(1)
        caja.addLayout(atajos)

        caja.addWidget(
            etiqueta_ayuda(
                "Solo se analizaran las publicaciones creadas dentro de este rango "
                "(ambos dias incluidos)."
            )
        )
        return grupo

    # -------- Paso 4: como elegir las publicaciones
    def _grupo_modo(self) -> QGroupBox:
        grupo = QGroupBox("Paso 4 · Que publicaciones entran")
        caja = QVBoxLayout(grupo)

        self.grupo_modo = QButtonGroup(self)

        self.rb_auto = QRadioButton(
            "Automatico — busca y extrae todas las publicaciones del rango"
        )
        self.rb_revisar = QRadioButton(
            "Revisar y elegir a mano — primero te muestro la lista y tu marcas cuales"
        )
        self.rb_manual = QRadioButton(
            "Pegar URLs de publicaciones — tu ya sabes cuales quieres"
        )
        self.rb_revisar.setChecked(True)

        for i, rb in enumerate((self.rb_auto, self.rb_revisar, self.rb_manual)):
            self.grupo_modo.addButton(rb, i)
            caja.addWidget(rb)

        caja.addWidget(
            etiqueta_ayuda(
                "Recomendado para empezar: «Revisar y elegir a mano». Asi ves que "
                "encontro la aplicacion antes de gastar tiempo extrayendo."
            )
        )

        self.txt_urls = QPlainTextEdit()
        self.txt_urls.setPlaceholderText(
            "Pega aqui una URL de publicacion por linea, por ejemplo:\n"
            "https://www.facebook.com/pagina/posts/123456789\n"
            "https://www.facebook.com/reel/987654321"
        )
        self.txt_urls.setFixedHeight(110)
        self.txt_urls.setVisible(False)
        caja.addWidget(self.txt_urls)
        return grupo

    # -------- Opciones avanzadas
    def _grupo_avanzado(self) -> QGroupBox:
        grupo = QGroupBox("Opciones avanzadas (puedes dejarlas como estan)")
        rejilla = QGridLayout(grupo)

        self.spin_max_pub = QSpinBox()
        self.spin_max_pub.setRange(1, 5000)
        self.spin_max_pub.setValue(200)
        self.spin_max_pub.setSingleStep(25)
        self.spin_max_pub.setToolTip(
            "Tope de publicaciones a procesar. Si el registro avisa de que se\n"
            "alcanzo el limite, subelo: se quedarian fuera las mas antiguas."
        )

        self.spin_max_com = QSpinBox()
        self.spin_max_com.setRange(10, 20000)
        self.spin_max_com.setValue(500)
        self.spin_max_com.setSingleStep(50)

        self.spin_scroll = QSpinBox()
        self.spin_scroll.setRange(10, 3000)
        self.spin_scroll.setValue(250)
        self.spin_scroll.setSingleStep(25)
        self.spin_scroll.setToolTip(
            "Cuantas veces baja por el muro buscando publicaciones.\n"
            "Cada vuelta baja unos dos tercios de pantalla (poco a proposito,\n"
            "para no saltarse nada). Si el perfil publica mucho, subelo."
        )

        self.chk_respuestas = QCheckBox("Incluir respuestas a comentarios")
        self.chk_respuestas.setChecked(True)

        self.chk_visible = QCheckBox("Mostrar el navegador mientras trabaja")
        self.chk_visible.setChecked(True)

        self.spin_minutos = QSpinBox()
        self.spin_minutos.setRange(1, 60)
        self.spin_minutos.setValue(8)
        self.spin_minutos.setSuffix(" min")
        self.spin_minutos.setToolTip(
            "Tiempo maximo recorriendo cada seccion del perfil.\n"
            "Solo se aplica cuando ya no aparecen publicaciones del rango:\n"
            "mientras siga encontrando, no corta por reloj."
        )

        self.chk_exhaustivo = QCheckBox("Busqueda exhaustiva (mas lenta, no se salta nada)")
        self.chk_exhaustivo.setToolTip(
            "Quita el tope de tiempo, recorre cada seccion hasta el final y\n"
            "comprueba la fecha de TODAS las publicaciones encontradas.\n"
            "Usalo cuando lo importante sea que no falte ninguna."
        )

        self.chk_pestanas = QCheckBox("Buscar tambien en Reels / Videos / Fotos")
        self.chk_pestanas.setChecked(True)
        self.chk_pestanas.setToolTip(
            "Recorre tambien las pestañas del perfil, no solo la linea de tiempo.\n"
            "Facebook NO lista todos los reels en el muro: los agrupa en su propia\n"
            "pestaña. Sin esto siempre faltaran publicaciones."
        )

        self.chk_verificar_fechas = QCheckBox("Comprobar la fecha exacta de cada publicacion")
        self.chk_verificar_fechas.setChecked(True)
        self.chk_verificar_fechas.setToolTip(
            "Abre cada publicacion para leer su fecha real.\n"
            "Tarda mas, pero es la unica forma de que las fechas sean exactas:\n"
            "la fecha que se ve en el muro puede ser la de un comentario."
        )

        rejilla.addWidget(QLabel("Maximo de publicaciones:"), 0, 0)
        rejilla.addWidget(self.spin_max_pub, 0, 1)
        rejilla.addWidget(QLabel("Maximo de comentarios por publicacion:"), 0, 2)
        rejilla.addWidget(self.spin_max_com, 0, 3)
        rejilla.addWidget(QLabel("Vueltas bajando por el muro:"), 1, 0)
        rejilla.addWidget(self.spin_scroll, 1, 1)
        rejilla.addWidget(self.chk_respuestas, 1, 2)
        rejilla.addWidget(self.chk_visible, 1, 3)
        rejilla.addWidget(QLabel("Tiempo maximo por seccion:"), 2, 0)
        rejilla.addWidget(self.spin_minutos, 2, 1)
        rejilla.addWidget(self.chk_pestanas, 2, 2, 1, 2)
        rejilla.addWidget(self.chk_verificar_fechas, 3, 0, 1, 2)
        rejilla.addWidget(self.chk_exhaustivo, 3, 2, 1, 2)
        rejilla.addWidget(
            etiqueta_ayuda(
                "Deja marcado «Mostrar el navegador» al principio: asi ves lo que "
                "ocurre y puedes resolver a mano un captcha o un aviso de Facebook.\n"
                "«Comprobar la fecha exacta» es lento pero necesario: sin el, las "
                "fechas salen corridas porque el muro muestra la hora del ultimo "
                "comentario, no la de la publicacion."
            ),
            4, 0, 1, 4,
        )
        rejilla.setColumnStretch(4, 1)
        return grupo

    # -------- Boton de accion + registro en vivo
    def _grupo_accion(self) -> QGroupBox:
        grupo = QGroupBox("Ejecutar")
        caja = QVBoxLayout(grupo)

        fila = QHBoxLayout()
        self.btn_iniciar = QPushButton("▶  Buscar publicaciones")
        self.btn_iniciar.setObjectName("principal")
        self.btn_detener = QPushButton("⏹  Detener")
        self.btn_detener.setEnabled(False)
        self.btn_diagnostico = QPushButton("🩺 Guardar diagnostico")
        self.btn_diagnostico.setToolTip(
            "Guarda el HTML y una captura de la pagina actual del navegador.\n"
            "Sirve para reparar la app si Facebook cambia su diseño."
        )
        fila.addWidget(self.btn_iniciar)
        fila.addWidget(self.btn_detener)
        fila.addStretch(1)
        fila.addWidget(self.btn_diagnostico)
        caja.addLayout(fila)

        self.barra = QProgressBar()
        self.barra.setRange(0, 100)
        self.barra.setValue(0)
        self.barra.setFormat("Listo para empezar")
        caja.addWidget(self.barra)

        self.registro = QPlainTextEdit()
        self.registro.setObjectName("registro")
        self.registro.setReadOnly(True)
        self.registro.setMinimumHeight(180)
        self.registro.setPlaceholderText("Aqui iras viendo lo que hace la aplicacion…")
        caja.addWidget(self.registro)
        return grupo

    # ---------------------------------------------------------------- conexiones

    def _conectar(self) -> None:
        self.cmb_red.currentIndexChanged.connect(self._cambio_red)
        self.btn_login.clicked.connect(self._abrir_login)
        self.btn_verificar.clicked.connect(self._verificar_sesion)
        self.btn_recargar.clicked.connect(self._recargar_pagina)
        self.btn_cerrar_navegador.clicked.connect(self._cerrar_navegador)
        self.btn_iniciar.clicked.connect(self._iniciar)
        self.btn_detener.clicked.connect(self.hilo.cancelar)
        self.btn_diagnostico.clicked.connect(self._diagnostico)
        self.grupo_modo.idToggled.connect(self._cambio_modo)
        self.chk_visible.toggled.connect(self.hilo.configurar_navegador)
        self._cambio_red()

    # ------------------------------------------------------------------ acciones

    def _atajo_fecha(self, dias: int) -> None:
        hoy = QDate.currentDate()
        if dias == -1:      # este año
            self.fecha_desde.setDate(QDate(hoy.year(), 1, 1))
        elif dias == -2:    # todo
            self.fecha_desde.setDate(QDate(2004, 1, 1))
        else:
            self.fecha_desde.setDate(hoy.addDays(-dias))
        self.fecha_hasta.setDate(hoy)

    def _cambio_red(self) -> None:
        extractor = registro.obtener(self.red_actual)
        self.lbl_ayuda_red.setText(extractor.ayuda)
        self.txt_perfil.setPlaceholderText(
            {
                "facebook": "https://www.facebook.com/nombredelapagina",
                "instagram": "https://www.instagram.com/nombredeusuario/",
                "tiktok": "https://www.tiktok.com/@nombredeusuario",
                "x": "https://x.com/nombredeusuario",
            }.get(extractor.nombre, "")
        )
        disponible = extractor.implementado
        self.btn_iniciar.setEnabled(disponible)
        self.lbl_sesion.setText(
            "🔴  Sesion no comprobada" if disponible else "⛔  Red no disponible aun"
        )

    def _cambio_modo(self, _id: int, _marcado: bool) -> None:
        manual = self.rb_manual.isChecked()
        self.txt_urls.setVisible(manual)
        self.btn_iniciar.setText(
            "▶  Extraer comentarios de esas URLs" if manual
            else "▶  Buscar publicaciones"
        )

    def _abrir_login(self) -> None:
        self.hilo.configurar_navegador(self.chk_visible.isChecked())
        self.hilo.encolar(Tarea(tipo="iniciar_sesion", red=self.red_actual))

    def _verificar_sesion(self) -> None:
        self.hilo.encolar(Tarea(tipo="verificar_sesion", red=self.red_actual))

    def _recargar_pagina(self) -> None:
        self.hilo.encolar(Tarea(tipo="recargar", red=self.red_actual))

    def _cerrar_navegador(self) -> None:
        self.hilo.encolar(Tarea(tipo="cerrar_navegador", red=self.red_actual))

    def _diagnostico(self) -> None:
        self.hilo.encolar(Tarea(tipo="diagnostico", red=self.red_actual))

    def _iniciar(self) -> None:
        self.hilo.configurar_navegador(self.chk_visible.isChecked())
        opciones = self.opciones_actuales()

        if self.rb_manual.isChecked():
            urls = [u.strip() for u in self.txt_urls.toPlainText().splitlines() if u.strip()]
            if not urls:
                self.escribir("⚠ Pega al menos una URL de publicacion.")
                return
            extractor = registro.obtener(self.red_actual)
            publicaciones = [extractor.publicacion_desde_url(u) for u in urls]
            self.escribir(f"Modo manual: {len(publicaciones)} URLs a procesar.")
            self.hilo.encolar(
                Tarea(
                    tipo="extraer",
                    red=self.red_actual,
                    opciones=opciones,
                    publicaciones=publicaciones,
                )
            )
            return

        if not opciones.url_perfil:
            self.escribir("⚠ Falta la URL del perfil (Paso 2).")
            return
        self.hilo.encolar(
            Tarea(tipo="descubrir", red=self.red_actual, opciones=opciones)
        )

    # ------------------------------------------------------------------- estado

    @property
    def red_actual(self) -> str:
        return self.cmb_red.currentData()

    @property
    def modo(self) -> str:
        if self.rb_auto.isChecked():
            return MODO_AUTOMATICO
        if self.rb_manual.isChecked():
            return MODO_MANUAL
        return MODO_REVISAR

    def opciones_actuales(self) -> OpcionesExtraccion:
        d = self.fecha_desde.date().toPython()
        h = self.fecha_hasta.date().toPython()
        return OpcionesExtraccion(
            url_perfil=self.txt_perfil.text().strip(),
            desde=datetime.combine(d, time.min),
            hasta=datetime.combine(h, time.max),
            max_publicaciones=self.spin_max_pub.value(),
            max_comentarios_por_publicacion=self.spin_max_com.value(),
            incluir_respuestas=self.chk_respuestas.isChecked(),
            max_desplazamientos=self.spin_scroll.value(),
            verificar_fechas=self.chk_verificar_fechas.isChecked(),
            buscar_en_pestanas=self.chk_pestanas.isChecked(),
            minutos_por_seccion=self.spin_minutos.value(),
            exhaustivo=self.chk_exhaustivo.isChecked(),
        )

    # -------------------------------------------------------- ranuras (señales)

    def escribir(self, mensaje: str) -> None:
        marca = datetime.now().strftime("%H:%M:%S")
        self.registro.appendPlainText(f"[{marca}] {mensaje}")
        barra = self.registro.verticalScrollBar()
        barra.setValue(barra.maximum())

    def actualizar_progreso(self, hecho: int, total: int, mensaje: str) -> None:
        total = max(total, 1)
        self.barra.setRange(0, total)
        self.barra.setValue(min(hecho, total))
        self.barra.setFormat(f"{mensaje}  (%p%)")

    def marcar_ocupado(self, ocupado: bool) -> None:
        self.btn_iniciar.setEnabled(
            not ocupado and registro.obtener(self.red_actual).implementado
        )
        self.btn_detener.setEnabled(ocupado)
        self.btn_login.setEnabled(not ocupado)
        self.btn_verificar.setEnabled(not ocupado)
        self.btn_recargar.setEnabled(not ocupado)
        self.btn_cerrar_navegador.setEnabled(not ocupado)

    def actualizar_sesion(self, activa: bool, mensaje: str) -> None:
        self.lbl_sesion.setText(("🟢  " if activa else "🔴  ") + mensaje)
