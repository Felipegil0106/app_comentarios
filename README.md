# Extractor de Comentarios de Redes Sociales

Aplicación de escritorio para Windows que descarga los **comentarios de texto** de las
publicaciones de un perfil de redes sociales, filtrando por **rango de fechas** o
eligiendo las publicaciones **a mano**.

- ✅ **Facebook** — funcionando (publicaciones, fotos, vídeos y reels)
- 🚧 Instagram, TikTok, X — la estructura está lista, la extracción todavía no

---

## 1. Instalación (solo una vez)

1. Instala **Python 3.10 o superior** desde <https://www.python.org/downloads/>.
   > ⚠️ Durante la instalación **marca la casilla «Add Python to PATH»**. Es el
   > error más común.
2. Haz **doble clic en `instalar.bat`**.
   Descargará las librerías y un navegador Chromium (~150 MB). Tarda de 3 a 8 minutos.
3. Cuando diga `INSTALACION TERMINADA`, cierra la ventana negra.

## 2. Abrir la aplicación

Doble clic en **`iniciar.bat`**.

> 💡 Puedes crear un acceso directo de `iniciar.bat` en el escritorio:
> clic derecho → *Enviar a* → *Escritorio (crear acceso directo)*.

---

## 3. Cómo se usa

### Paso A — Iniciar sesión (la primera vez)

En la pestaña **1 · Extraer**:

1. Pulsa **«Abrir navegador e iniciar sesión»**. Se abre una ventana de Chromium.
2. Inicia sesión en Facebook **en esa ventana**, como lo harías normalmente.
3. Vuelve a la app y pulsa **«Ya inicié sesión — comprobar»**. El indicador pasa a 🟢.

La aplicación **no te pide ni guarda tu contraseña**. Solo queda guardada la sesión
(cookies) en tu propio equipo, en `%APPDATA%\ExtractorComentarios\navegadores`.

### Paso B — Configurar la extracción

| Paso | Qué hacer |
|------|-----------|
| 2 | Pega la URL del perfil: `https://www.facebook.com/nombredelapagina` |
| 3 | Elige el rango de fechas (o usa un atajo: *Últimos 30 días*, *Este año*, *Todo*) |
| 4 | Elige **cómo** seleccionar las publicaciones (ver abajo) |

**Las tres formas de elegir publicaciones:**

1. **Automático** — busca y extrae todo lo del rango de una sola vez.
2. **Revisar y elegir a mano** *(recomendado)* — primero te muestra la lista en la
   pestaña **2 · Publicaciones** y tú marcas ☑ cuáles quieres.
3. **Pegar URLs de publicaciones** — pegas una URL por línea. **Es el modo más
   fiable**, porque no depende de que la app sepa leer el muro.

Pulsa **▶ Buscar publicaciones** y sigue el registro de la parte de abajo.

### Paso C — Ver resultados y descargar

En la pestaña **3 · Resultados**:

- Arriba hay cinco contadores: publicaciones con comentarios, comentarios mostrados,
  autores únicos, respuestas y promedio por publicación.
  **Se recalculan cada vez que cambias un filtro.**
- El desplegable **Publicación (URL)** muestra cada publicación con su número de
  comentarios entre corchetes. Al elegir una, la tabla y los contadores se limitan a esa.
- Puedes además buscar una palabra dentro de los comentarios o filtrar por autor.
- **Descargar CSV / Excel (lo que veo)** exporta exactamente lo filtrado.
  **(todo)** exporta la base completa.

El Excel trae tres hojas: *Comentarios*, *Resumen por publicación* y *Top autores*.

---

## 4. Qué se guarda

De cada comentario:

| Campo | Ejemplo |
|-------|---------|
| Red social | `facebook` |
| URL de la publicación | `https://www.facebook.com/pagina/posts/123` |
| Fecha de la publicación | `2025-08-03 14:32` |
| Tipo de publicación | `publicacion` / `foto` / `video` / `reel` |
| Autor del comentario | `Juan Pérez` |
| Fecha del comentario | `2025-08-03 16:10` |
| Es respuesta | `Sí` / `No` |
| **Comentario** | `Me encantó este producto 😍🔥` |

**Solo texto y emojis.** Los comentarios que son únicamente un GIF, sticker, imagen
o vídeo se descartan automáticamente porque no tienen texto.

Todo se guarda en tu equipo, en `%APPDATA%\ExtractorComentarios\datos.sqlite3`.
Nada se envía a internet. Si vuelves a extraer la misma publicación, los comentarios
repetidos **no se duplican**.

---

## 5. Si algo falla

| Síntoma | Qué hacer |
|---------|-----------|
| «No encontró publicaciones» | Amplía el rango de fechas (atajo **Todo**), sube *«Veces que baja por el muro»* en opciones avanzadas, o usa el modo **Pegar URLs**. |
| «0 comentarios» en publicaciones que sí tienen | Pulsa **🩺 Guardar diagnóstico** y revisa el HTML guardado. Luego ajusta los textos en `src/config/facebook.json`. |
| Facebook pide captcha | Deja el navegador visible, resuélvelo a mano en esa ventana y continúa. Baja el máximo de publicaciones. |
| «Faltan dependencias» | Vuelve a ejecutar `instalar.bat`. |

**Facebook cambia su diseño cada cierto tiempo.** Cuando eso pasa, lo que se rompe
son los textos de los botones («Ver más comentarios», «Todos los comentarios»…).
Están todos en **`src/config/facebook.json`**, que se puede editar con el Bloc de
notas sin tocar el código.

---

## 6. Cómo está organizado el código

```
extraer_comentarios/
├── instalar.bat            Instalador (doble clic, una vez)
├── iniciar.bat             Arranca la aplicación
├── requirements.txt        Librerías necesarias
└── src/
    ├── main.py             Punto de entrada
    ├── config/
    │   └── facebook.json   Textos y selectores de Facebook (editable)
    ├── core/               Lógica que no depende de ninguna red
    │   ├── modelos.py      Qué es una Publicación y un Comentario
    │   ├── base_datos.py   Guardado en SQLite, sin duplicados
    │   ├── limpieza.py     Deja solo texto + emojis
    │   ├── fechas.py       Entiende «hace 3 h», «3 de agosto de 2024»…
    │   ├── exportar.py     CSV y Excel
    │   └── rutas.py        Dónde se guarda cada cosa
    ├── navegador/
    │   └── sesion.py       Abre Chromium con sesión persistente
    ├── redes/
    │   ├── base.py         Contrato común a todas las redes
    │   ├── facebook.py     ← el extractor de Facebook
    │   ├── js_facebook.py  JavaScript que lee la página
    │   ├── otras_redes.py  Esqueletos de Instagram / TikTok / X
    │   └── registro.py     Catálogo de redes
    └── ui/
        ├── ventana.py      Ventana principal
        ├── hilo.py         Trabajo en segundo plano (no congela la app)
        ├── pestana_*.py    Cada pestaña
        └── estilos.py      Colores y apariencia
```

### Añadir una red social nueva

1. Crea una clase que herede de `ExtractorRed` (mira `src/redes/facebook.py`).
2. Implementa tres métodos: `sesion_iniciada`, `descubrir_publicaciones` y
   `extraer_comentarios`.
3. Añádela a la lista `_CLASES` de `src/redes/registro.py`.

Todo lo demás (interfaz, base de datos, filtros, exportación) funciona solo.

---

## 7. Uso responsable

- Extrae solo contenido **público** o que te pertenezca.
- Los comentarios contienen **datos personales de terceros**: guárdalos el tiempo
  necesario, no los republiques tal cual y respeta la normativa de protección de
  datos que te aplique.
- Facebook, Instagram, TikTok y X **restringen el scraping automatizado** en sus
  condiciones de uso. Para uso a gran escala o comercial, la vía correcta son sus
  APIs oficiales (por ejemplo la Graph API de Meta para páginas que administras).
- La aplicación incluye pausas entre publicaciones para no saturar los servidores.
  No las quites.

El uso que hagas de esta herramienta es tu responsabilidad.
