"""JavaScript que se ejecuta dentro de las paginas de X (antes Twitter).

X marca sus elementos con `data-testid`, igual de comodo que el `data-e2e`
de TikTok: article[data-testid="tweet"], [data-testid="tweetText"],
[data-testid="User-Name"]. Menos adivinanza que en Facebook o Instagram.

Lo que NO cambia respecto a las demas redes:
  - la pagina de un tuit trae debajo «publicaciones sugeridas» que NO son
    respuestas: hay que acotar la lectura a la conversacion
  - el tuit original tiene la misma forma que una respuesta; se distingue
    porque su identificador es el de la URL
  - la cronologia descarta del DOM lo que sale de pantalla
"""

# ---------------------------------------------------------------------------
# Fase 1: enlaces a publicaciones desde la cronologia del perfil
# ---------------------------------------------------------------------------
JS_ENLACES_PUBLICACIONES = r"""
() => {
  const salida = [];
  const vistos = new Set();
  document.querySelectorAll('a[href*="/status/"]').forEach(a => {
    // Miramos la direccion absoluta y, si no la hay, la del atributo: en X
    // los enlaces son relativos («/usuario/status/123»).
    const texto = (a.href || '') || (a.getAttribute('href') || '');
    // No exigimos que la direccion TERMINE en el identificador: hay enlaces
    // a /status/ID/photo/1 o /analytics que apuntan al mismo tuit y son la
    // unica forma de verlo en algunas tarjetas. Ya se normaliza despues.
    const m = texto.match(/\/([A-Za-z0-9_]{1,15})\/status\/(\d{15,20})/);
    if (!m) return;
    if (vistos.has(m[2])) return;
    vistos.add(m[2]);
    salida.push({href: 'https://x.com/' + m[1] + '/status/' + m[2],
                 autor: m[1], id: m[2]});
  });
  return salida;
}
"""

# Identificadores que viajan en el HTML aunque la cronologia no se pinte
JS_IDS_INCRUSTADOS = r"""
() => {
  const html = document.documentElement.innerHTML;
  const ids = new Set();
  let m;
  const re = /\/status\/(\d{15,20})/g;
  while ((m = re.exec(html)) !== null) ids.add(m[1]);
  return Array.from(ids).slice(0, 3000);
}
"""

# ---------------------------------------------------------------------------
# Radiografia: para saber QUE estamos viendo cuando no aparece nada
# ---------------------------------------------------------------------------
JS_ESTADO_PAGINA = r"""
() => {
  const t = document.body ? (document.body.innerText || '') : '';
  return {
    url: location.href,
    titulo: document.title || '',
    enlaces_total: document.querySelectorAll('a[href]').length,
    enlaces_status: document.querySelectorAll('a[href*="/status/"]').length,
    tuits: document.querySelectorAll('article[data-testid="tweet"]').length,
    hay_login: /\/i\/flow\/login|\/login/.test(location.pathname)
      || !!document.querySelector('input[name="text"][autocomplete="username"]'),
    hay_sesion: !!document.querySelector(
      '[data-testid="SideNav_AccountSwitcher_Button"], [data-testid="AppTabBar_Profile_Link"]'),
    parece_vacio: t.trim().length < 80,
    sin_ventana: /Headless/i.test(navigator.userAgent),
    texto: t.slice(0, 300)
  };
}
"""

# ---------------------------------------------------------------------------
# Leer las respuestas de un tuit
# ---------------------------------------------------------------------------
JS_LEER_RESPUESTAS = r"""
([idOriginal, selBloques, selTexto, selAutor, selConversacion]) => {
  // De donde leemos. Como en las demas redes: NUNCA de document.body.
  // Debajo de la conversacion X pone «Descubre mas», con tuits de otros que
  // no son respuestas a este.
  let raiz = document.querySelector('[data-xc-panel]');
  let ambito = 'panel anclado';
  if (!raiz) {
    for (const s of selConversacion) {
      raiz = document.querySelector(s);
      if (raiz) { ambito = 'conversacion (' + s + ')'; break; }
    }
  }
  if (!raiz) {
    return {comentarios: [], ambito: 'no se encontro la conversacion', bloques: 0};
  }

  const limpio = (s) => (s || '').replace(/\s+/g, ' ').trim();

  let bloques = [];
  for (const s of selBloques) {
    bloques = Array.from(raiz.querySelectorAll(s));
    if (bloques.length) break;
  }

  const salida = [];
  const vistos = new Set();

  bloques.forEach(b => {
    // El identificador de este tuit: sale de su propio enlace con la hora
    let id = '';
    const enlaces = Array.from(b.querySelectorAll('a[href*="/status/"]'));
    for (const a of enlaces) {
      const m = (a.getAttribute('href') || '').match(/\/status\/(\d+)/);
      if (m) { id = m[1]; break; }
    }

    // El tuit original NO es una respuesta a si mismo
    if (idOriginal && id === idOriginal) return;

    const et = b.querySelector(selTexto);
    const texto = limpio(et ? et.innerText : '');
    if (!texto) return;

    // Autor: preferimos el @usuario, que es inequivoco
    let autor = '';
    const bloqueAutor = b.querySelector(selAutor);
    if (bloqueAutor) {
      const m = (bloqueAutor.innerText || '').match(/@([A-Za-z0-9_]{1,15})/);
      if (m) autor = '@' + m[1];
      else autor = limpio(bloqueAutor.innerText).split(' ')[0];
    }
    if (!autor) {
      const ap = b.querySelector('a[href^="/"][role="link"]');
      if (ap) {
        const h = (ap.getAttribute('href') || '').replace(/^\//, '');
        if (/^[A-Za-z0-9_]{1,15}$/.test(h)) autor = '@' + h;
      }
    }
    if (!autor) return;

    const clave = autor + '|' + texto;
    if (vistos.has(clave)) return;
    vistos.add(clave);

    const t = b.querySelector('time[datetime]');
    salida.push({
      autor: autor,
      texto: texto,
      fecha: t ? (t.getAttribute('datetime') || '') : '',
      id: id,
      es_respuesta: true,
      reacciones: 0
    });
  });

  return {comentarios: salida, ambito: ambito, bloques: bloques.length};
}
"""

JS_ANCLAR_PANEL = r"""
(selConversacion) => {
  document.querySelectorAll('[data-xc-panel]').forEach(
    e => e.removeAttribute('data-xc-panel'));
  for (const s of selConversacion) {
    const c = document.querySelector(s);
    if (c) { c.setAttribute('data-xc-panel', '1'); return {ok: true, usado: s}; }
  }
  return {ok: false, motivo: 'no se encontro la conversacion'};
}
"""

# --------------------------------------------------------------- utilidades
JS_PULSAR_BOTONES = r"""
([patron, limite]) => {
  const re = new RegExp(patron, 'i');
  const candidatos = Array.from(document.querySelectorAll(
    'button, div[role="button"], span[role="button"], a[role="link"]'));
  let pulsados = 0;
  for (const b of candidatos) {
    if (pulsados >= limite) break;
    const t = ((b.innerText || '') + ' ' + (b.getAttribute('aria-label') || '')).trim();
    if (!t || t.length > 70) continue;
    if (!re.test(t)) continue;
    if (/ocultar|hide/i.test(t)) continue;
    const caja = b.getBoundingClientRect();
    if (caja.width === 0 && caja.height === 0) continue;
    try { b.click(); pulsados++; } catch (e) {}
  }
  return pulsados;
}
"""

JS_DESPLAZAR = r"""
(paso) => {
  const alturaAntes = document.body.scrollHeight;
  const yAntes = window.scrollY;
  window.scrollBy(0, paso);
  return {
    y: window.scrollY,
    se_movio: window.scrollY > yAntes,
    altura: alturaAntes,
    al_final: (window.innerHeight + window.scrollY) >= (alturaAntes - 300)
  };
}
"""

JS_ALTURA_PAGINA = r"""() => document.body.scrollHeight"""
JS_POSICION = r"""() => window.scrollY"""
JS_IR_A = r"""(y) => { window.scrollTo(0, y); return window.scrollY; }"""
JS_IR_AL_FONDO = r"""
() => { window.scrollTo(0, document.body.scrollHeight); return document.body.scrollHeight; }
"""

JS_SESION_INICIADA = r"""
() => !!document.querySelector(
  '[data-testid="SideNav_AccountSwitcher_Button"], [data-testid="AppTabBar_Profile_Link"]')
"""
