"""JavaScript que se ejecuta dentro de las paginas de TikTok.

TikTok marca sus elementos con atributos `data-e2e` (comment-level-1,
comment-username-1, comment-text...). Son mucho mas estables que las clases
revueltas de Facebook o Instagram, asi que aqui hay menos adivinanza.

Lo que NO cambia respecto a las otras redes:
  - la pagina de un video es un carrusel: trae los siguientes cargados
  - los comentarios viven en un panel con scroll propio
  - hay que acotar la lectura o se mezclan comentarios de otros videos
"""

# ---------------------------------------------------------------------------
# Fase 1: recolectar enlaces a publicaciones desde la cuadricula del perfil
# ---------------------------------------------------------------------------
JS_ENLACES_PUBLICACIONES = r"""
(patrones) => {
  const coincide = (h) => patrones.some(p => h.includes(p));
  const salida = [];
  const vistos = new Set();

  document.querySelectorAll('a[href]').forEach(a => {
    const href = a.href || '';
    if (!href || !coincide(href)) return;
    if (vistos.has(href)) return;
    vistos.add(href);
    const img = a.querySelector('img[alt]');
    salida.push({
      href: href,
      texto: img ? (img.getAttribute('alt') || '').slice(0, 200) : ''
    });
  });
  return salida;
}
"""

# ---------------------------------------------------------------------------
# Datos de UN video abierto
# ---------------------------------------------------------------------------
JS_DATOS_PUBLICACION = r"""
(idObjetivo) => {
  const html = document.documentElement.innerHTML;

  // TikTok incrusta "createTime" en su JSON. Misma cautela que en Facebook e
  // Instagram: la pagina trae varios videos, asi que nos quedamos con el mas
  // cercano al id del que nos interesa. Si no hay forma de decidir, nada.
  const marcas = [];
  const re = /"createTime"\s*:\s*"?(\d{9,11})"?/g;
  let m;
  while ((m = re.exec(html)) !== null) marcas.push([m.index, parseInt(m[1], 10)]);

  let epoch = null, confianza = 'ninguna';
  if (marcas.length === 1) {
    epoch = marcas[0][1];
    confianza = 'createTime_unico';
  } else if (marcas.length > 1 && idObjetivo) {
    const posiciones = [];
    let desde = 0, k;
    while ((k = html.indexOf(idObjetivo, desde)) !== -1) {
      posiciones.push(k);
      desde = k + 1;
      if (posiciones.length > 500) break;
    }
    let mejor = null, mejorDist = Infinity;
    for (const par of marcas) {
      for (const q of posiciones) {
        const d = Math.abs(par[0] - q);
        if (d < mejorDist) { mejorDist = d; mejor = par[1]; }
      }
    }
    if (mejor !== null && mejorDist <= 8000) {
      epoch = mejor;
      confianza = 'createTime_por_id';
    }
  }

  // Descripcion del video y numero de comentarios anunciado
  let texto = '';
  const desc = document.querySelector('[data-e2e="browse-video-desc"], [data-e2e="video-desc"]');
  if (desc) texto = (desc.innerText || '').trim();
  if (!texto) {
    const og = document.querySelector('meta[property="og:description"]');
    if (og) texto = (og.getAttribute('content') || '').trim();
  }

  let anunciados = '';
  const cnt = document.querySelector('[data-e2e="comment-count"], [data-e2e="browse-comment-count"]');
  if (cnt) anunciados = (cnt.innerText || '').trim();

  return {epoch: epoch, confianza: confianza, marcas_en_pagina: marcas.length,
          texto: texto.slice(0, 400), anunciados: anunciados, url: location.href};
}
"""

# ---------------------------------------------------------------------------
# Leer los comentarios cargados
# ---------------------------------------------------------------------------
JS_LEER_COMENTARIOS = r"""
([selBloque, selAutor, selTexto]) => {
  // De donde leemos. Igual que en las otras redes: NUNCA de document.body.
  // La pagina de un video trae los videos siguientes cargados, con sus
  // comentarios, y acabariamos atribuyendolos a esta URL.
  const anclado = document.querySelector('[data-xc-panel]');
  const raiz = anclado
            || document.querySelector('[data-e2e="comment-list"]')
            || document.querySelector('[class*="CommentListContainer"]')
            || null;
  if (!raiz) {
    return {comentarios: [], ambito: 'no se encontro la lista de comentarios',
            anclado: false, bloques: 0};
  }
  const ambito = anclado ? 'panel anclado' : 'lista de comentarios';

  const limpio = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const esRuido = (t) => {
    if (!t) return true;
    if (/^(hace\s+)?\d+\s*(s|seg|min|m|h|d|sem|w|mes|meses|a|años?|dias?|días?|semanas?|horas?|minutos?)\.?$/i.test(t)) return true;
    if (/^\d{1,2}-\d{1,2}(-\d{2,4})?$/.test(t)) return true;   // «08-28»
    if (/^(responder|reply|ver traducci[oó]n|see translation|creador|creator|autor|fijado|pinned)$/i.test(t)) return true;
    if (/^\d[\d.,]*\s*(me gusta|likes?|respuestas?|replies)?$/i.test(t)) return true;
    return false;
  };

  const primero = (el, selectores) => {
    for (const s of selectores) {
      const e = el.querySelector(s);
      if (e && limpio(e.innerText)) return limpio(e.innerText);
    }
    return '';
  };

  let bloques = [];
  for (const s of selBloque) {
    bloques = Array.from(raiz.querySelectorAll(s));
    if (bloques.length) break;
  }

  const salida = [];
  const vistos = new Set();

  bloques.forEach(b => {
    const autor = primero(b, selAutor);
    if (!autor) return;

    let texto = primero(b, selTexto);
    if (!texto || texto === autor) {
      // Plan B: el trozo mas largo que no sea el nombre ni ruido
      const trozos = Array.from(b.querySelectorAll('span, p, div'))
        .filter(e => !e.closest('a'))
        .map(e => limpio(e.innerText))
        .filter(t => t && t !== autor && !esRuido(t) && !t.startsWith(autor));
      texto = trozos.reduce((x, y) => (y.length > x.length ? y : x), '');
    }
    if (!texto || esRuido(texto)) return;

    const clave = autor + '|' + texto;
    if (vistos.has(clave)) return;
    vistos.add(clave);

    const e2e = b.getAttribute('data-e2e') || '';
    salida.push({
      autor: autor,
      texto: texto,
      fecha: '',
      // comment-level-1 son comentarios; del 2 en adelante, respuestas
      es_respuesta: /comment-level-([2-9])/.test(e2e),
      reacciones: 0
    });
  });

  return {comentarios: salida, ambito: ambito, anclado: !!anclado,
          bloques: bloques.length};
}
"""

JS_ANCLAR_PANEL = r"""
() => {
  document.querySelectorAll('[data-xc-panel]').forEach(
    e => e.removeAttribute('data-xc-panel'));

  const lista = document.querySelector('[data-e2e="comment-list"]')
             || document.querySelector('[class*="CommentListContainer"]');
  if (!lista) return {ok: false, motivo: 'aun no hay lista de comentarios'};

  // Subimos desde la lista hasta el contenedor que tiene el scroll propio
  let e = lista, saltos = 0;
  while (e && saltos < 12) {
    const ov = getComputedStyle(e).overflowY;
    if ((ov === 'auto' || ov === 'scroll') && e.scrollHeight > e.clientHeight + 40) {
      e.setAttribute('data-xc-panel', '1');
      return {ok: true};
    }
    e = e.parentElement; saltos++;
  }
  // Sin scroll propio todavia (pocos comentarios): anclamos la lista misma
  lista.setAttribute('data-xc-panel', '1');
  return {ok: true, motivo: 'lista sin scroll propio'};
}
"""

JS_DESPLAZAR_PANEL = r"""
() => {
  const anclado = document.querySelector('[data-xc-panel]');
  let destino = null;
  if (anclado) {
    destino = anclado;
    // Si el anclado no tiene scroll propio, buscamos el ancestro que si
    if (destino.scrollHeight <= destino.clientHeight + 10) {
      let e = destino.parentElement, saltos = 0;
      while (e && saltos < 10) {
        if (e.scrollHeight > e.clientHeight + 40) { destino = e; break; }
        e = e.parentElement; saltos++;
      }
    }
  }
  if (!destino) return {encontrado: false, al_final: true};
  const antes = destino.scrollTop;
  destino.scrollTop = antes + Math.max(300, destino.clientHeight * 0.7);
  return {
    encontrado: true,
    se_movio: destino.scrollTop > antes,
    al_final: (destino.scrollTop + destino.clientHeight) >= (destino.scrollHeight - 100)
  };
}
"""

JS_PULSAR_BOTONES = r"""
([patron, limite]) => {
  const re = new RegExp(patron, 'i');
  const candidatos = Array.from(document.querySelectorAll(
    'button, div[role="button"], span[role="button"], p, span, div[tabindex]'
  ));
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
() => {
  if (document.querySelector('input[name="username"]')) return false;
  if (/\/login/.test(location.pathname)) return false;
  return !!document.querySelector(
    '[data-e2e="profile-icon"], [data-e2e="nav-profile"], a[href*="/upload"]');
}
"""
