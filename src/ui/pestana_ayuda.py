"""Pestaña 4 - Guia rapida dentro de la propia aplicacion."""

from __future__ import annotations

import webbrowser

from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..core.rutas import CARPETA_CONFIG, CARPETA_DATOS, CARPETA_DIAGNOSTICO

GUIA = """
<style>
  body {{ font-family: "Segoe UI", Arial, sans-serif; color: #e6ebf5; line-height: 1.55; }}
  h2 {{ color: #4c8dff; margin-top: 22px; }}
  h3 {{ color: #e6ebf5; margin-bottom: 4px; }}
  code {{ background: #0b0f18; padding: 2px 6px; border-radius: 4px; color: #9ec5ff; }}
  .aviso {{ background:#1e2637; border-left: 3px solid #f0b429; padding: 10px 14px;
            border-radius: 6px; margin: 12px 0; }}
  .ok {{ background:#1e2637; border-left: 3px solid #39c07f; padding: 10px 14px;
         border-radius: 6px; margin: 12px 0; }}
  ul {{ margin-top: 4px; }}
  li {{ margin-bottom: 5px; }}
</style>

<h1>Guia rapida</h1>
<p>Esta aplicacion descarga los <b>comentarios de texto</b> de las publicaciones de un
perfil de redes sociales, dentro del rango de fechas que tu elijas.</p>

<h2>Primeros pasos (la primera vez)</h2>
<ol>
  <li>Ve a la pestaña <b>1 · Extraer</b>.</li>
  <li>Pulsa <b>«Abrir navegador e iniciar sesion»</b>. Se abrira una ventana de
      Chromium con Facebook.</li>
  <li>Inicia sesion <b>en esa ventana</b> como lo harias normalmente.
      <span class="ok">La aplicacion no ve ni guarda tu contraseña. Solo queda
      guardada la sesion (las cookies) en tu propio equipo.</span></li>
  <li>Vuelve a la aplicacion y pulsa <b>«Ya inicie sesion — comprobar»</b>.
      El indicador debe ponerse en verde 🟢.</li>
  <li>No cierres la ventana del navegador mientras trabajas.</li>
</ol>

<h2>Extraer comentarios</h2>
<ol>
  <li><b>Paso 2</b>: pega la URL del perfil o la pagina.
      <br><code>https://www.facebook.com/nombredelapagina</code></li>
  <li><b>Paso 3</b>: elige el rango de fechas (o usa un atajo como
      «Ultimos 30 dias»).</li>
  <li><b>Paso 4</b>: elige como quieres seleccionar las publicaciones:
    <ul>
      <li><b>Automatico</b> — la app busca y extrae todo lo del rango, de una.</li>
      <li><b>Revisar y elegir a mano</b> <i>(recomendado)</i> — primero te muestra
          la lista en la pestaña <b>2 · Publicaciones</b> y tu marcas cuales.</li>
      <li><b>Pegar URLs</b> — si ya sabes exactamente que publicaciones quieres,
          pega una URL por linea. <b>Este modo es el mas fiable de todos.</b></li>
    </ul>
  </li>
  <li>Pulsa <b>▶ Buscar publicaciones</b> y sigue el registro de abajo.</li>
  <li>En la pestaña <b>2 · Publicaciones</b> marca las que quieras y pulsa
      <b>⬇ Extraer comentarios de las marcadas</b>.</li>
  <li>Los resultados apareceran en la pestaña <b>3 · Resultados</b>.</li>
</ol>

<h2>Ver, filtrar y descargar</h2>
<ul>
  <li>El desplegable <b>Publicacion (URL)</b> te deja ver solo los comentarios de
      una publicacion concreta. Los contadores de arriba se recalculan solos.</li>
  <li>Puedes buscar una palabra dentro de los comentarios o filtrar por autor.</li>
  <li><b>Descargar CSV / Excel (lo que veo)</b> exporta exactamente lo filtrado.
      <b>(todo)</b> exporta la base completa.</li>
  <li>El Excel trae tres hojas: <i>Comentarios</i>, <i>Resumen por publicacion</i>
      y <i>Top autores</i>.</li>
</ul>

<h2>Que se guarda y que no</h2>
<ul>
  <li>De cada comentario se guarda <b>solo el texto y los emojis</b>, el autor,
      la fecha y la URL de la publicacion.</li>
  <li>Los comentarios que son solo un <b>GIF, sticker, imagen o video</b> se
      descartan automaticamente (quedan vacios de texto).</li>
  <li>Todo se guarda en tu equipo, en <code>{carpeta}</code>. Nada se envia
      a internet.</li>
</ul>

<h2>Si algo no funciona</h2>
<div class="aviso">
<b>«No encontro publicaciones»</b>
<ul>
  <li>Amplia el rango de fechas (usa el atajo <b>Todo</b>).</li>
  <li>Comprueba que la URL es de un perfil o pagina que tu cuenta pueda ver.</li>
  <li>Sube el valor de <b>«Veces que baja por el muro»</b> en opciones avanzadas.</li>
  <li>Usa el modo <b>Pegar URLs de publicaciones</b>: es el mas fiable.</li>
</ul>
</div>
<div class="aviso">
<b>«Encontro publicaciones pero 0 comentarios»</b>
<ul>
  <li>Puede que la publicacion realmente no tenga comentarios de texto.</li>
  <li>Facebook cambia su diseño cada cierto tiempo. Pulsa
      <b>🩺 Guardar diagnostico</b>, y luego revisa o comparte el archivo que
      queda en <code>{diagnostico}</code>.</li>
  <li>Los textos de los botones se pueden corregir a mano en
      <code>{config}</code> (archivo <code>facebook.json</code>).</li>
</ul>
</div>
<div class="aviso">
<b>Facebook me pide un captcha o me avisa de «actividad inusual»</b><br>
Baja el ritmo: reduce el maximo de publicaciones, deja el navegador visible y
resuelve el captcha a mano en la ventana del navegador. Despues continua.
</div>

<h2>Uso responsable</h2>
<p>Extrae solo contenido publico o que te pertenezca, y usa los datos para fines
legitimos. Los comentarios contienen datos personales de terceros: guardalos el
tiempo necesario, no los publiques tal cual y respeta la normativa de proteccion
de datos que te aplique. Las redes sociales restringen el scraping automatizado
en sus condiciones de uso; el uso que hagas de esta herramienta es tu
responsabilidad.</p>
"""


class PestanaAyuda(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        caja = QVBoxLayout(self)
        caja.setContentsMargins(18, 18, 18, 18)

        navegador = QTextBrowser()
        navegador.setOpenExternalLinks(True)
        navegador.setHtml(
            GUIA.format(
                carpeta=CARPETA_DATOS,
                diagnostico=CARPETA_DIAGNOSTICO,
                config=CARPETA_CONFIG,
            )
        )
        caja.addWidget(navegador, 1)

        fila = QHBoxLayout()
        btn_datos = QPushButton("📂 Abrir carpeta de datos")
        btn_config = QPushButton("⚙ Abrir carpeta de configuracion")
        btn_diag = QPushButton("🩺 Abrir carpeta de diagnostico")
        btn_datos.clicked.connect(lambda: webbrowser.open(str(CARPETA_DATOS)))
        btn_config.clicked.connect(lambda: webbrowser.open(str(CARPETA_CONFIG)))
        btn_diag.clicked.connect(lambda: webbrowser.open(str(CARPETA_DIAGNOSTICO)))
        fila.addWidget(btn_datos)
        fila.addWidget(btn_config)
        fila.addWidget(btn_diag)
        fila.addStretch(1)
        caja.addLayout(fila)
