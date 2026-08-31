"""Instagram, TikTok y X: esqueletos preparados, todavia sin implementar.

Aparecen en la aplicacion para que veas hacia donde va, pero avisan
claramente que aun no extraen. Cuando toque implementarlas, basta con
copiar la estructura de `facebook.py`:

    1. `sesion_iniciada`         -> como saber si ya hay sesion abierta
    2. `descubrir_publicaciones` -> recorrer el perfil y listar publicaciones
    3. `extraer_comentarios`     -> abrir cada publicacion y leer comentarios

Notas de cada red (para cuando llegue el momento):

  Instagram  Los posts estan en /<usuario>/. Los comentarios se cargan con
             el boton "Ver mas comentarios" (icono +). La fecha exacta esta
             en la etiqueta <time datetime="...">, que es muy fiable.

  TikTok     Los videos estan en /@<usuario>. Los comentarios salen en un
             panel lateral; hay que desplazarse DENTRO del panel, no en la
             pagina. TikTok es la mas agresiva detectando automatizacion.

  X          Requiere sesion si o si. Las "respuestas" son tweets hijos;
             hay que abrir cada tweet y desplazarse. El limite de peticiones
             es bajo: conviene ir despacio.
"""

from __future__ import annotations

from .base import ExtractorNoImplementado


class ExtractorX(ExtractorNoImplementado):
    nombre = "x"
    etiqueta = "X (Twitter)"
    url_inicio = "https://x.com/"
    ayuda = (
        "X todavia no esta implementado.\n"
        "Cuando lo este, pegaras la URL del perfil:\n"
        "  https://x.com/nombredeusuario"
    )
