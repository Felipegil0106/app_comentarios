"""Fragmentos de JavaScript que se ejecutan DENTRO de la pagina de Facebook.

Leer el HTML de Facebook desde Python seria lentisimo (miles de elementos).
En cambio, le pedimos al propio navegador que recorra la pagina y nos
devuelva una lista limpia de datos. Es mucho mas rapido y estable.
"""

# ---------------------------------------------------------------------------
# Fase 1: recolectar enlaces a publicaciones desde el muro del perfil
# ---------------------------------------------------------------------------
JS_ENLACES_PUBLICACIONES = r"""
(patrones) => {
  const regex = patrones.map(p => new RegExp(p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'));
  const coincide = (href) => regex.some(r => r.test(href));

  // Recorremos TODA la pagina, no solo los div[role="article"].
  // Facebook no siempre envuelve las publicaciones en un "article": los reels
  // en particular suelen ir en rejillas o carruseles fuera de esa etiqueta.
  // Si solo mirasemos dentro de los articles nos dejariamos posts sin ver.
  const salida = [];
  const vistos = new Set();

  document.querySelectorAll('a[href]').forEach(a => {
    const href = a.href || '';
    if (!href || !coincide(href)) return;

    const texto = (a.innerText || '').trim().slice(0, 80);
    const clave = href + '|' + texto;
    if (vistos.has(clave)) return;
    vistos.add(clave);

    // El contenedor del post, si existe, nos da el texto de alrededor
    const art = a.closest('div[role="article"]');

    salida.push({
      href: href,
      texto: texto,
      aria: (a.getAttribute('aria-label') || '').slice(0, 160),
      titulo: (a.getAttribute('title') || '').slice(0, 160),
      cuerpo: art ? (art.innerText || '').slice(0, 600) : ''
    });
  });
  return salida;
}
"""

# Baja por la pagina de forma fiable.
#
# No usamos la rueda del raton: el puntero de Playwright empieza en la esquina
# (0,0), que en Facebook cae sobre la barra lateral fija, y los eventos de rueda
# pueden acabar desplazando ese panel en vez del muro. Con scrollBy actuamos
# siempre sobre el documento.
JS_DESPLAZAR = r"""
(paso) => {
  const alturaAntes = document.body.scrollHeight;
  const yAntes = window.scrollY;
  window.scrollBy(0, paso);
  return {
    y: window.scrollY,
    se_movio: window.scrollY > yAntes,
    altura: alturaAntes,
    ventana: window.innerHeight,
    // ¿Estamos ya al final de lo que hay cargado?
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

# Busca marcas de tiempo incrustadas en el HTML (la fuente mas fiable de fecha)
JS_TIEMPOS_INCRUSTADOS = r"""
() => {
  const html = document.documentElement.innerHTML;
  const encontrados = [];
  const re = /"creation_time"\s*:\s*(\d{10})/g;
  let m;
  while ((m = re.exec(html)) !== null) encontrados.push(parseInt(m[1], 10));
  return encontrados;
}
"""

# ---------------------------------------------------------------------------
# Fase 2: pulsar botones (ver mas comentarios, ver mas respuestas, ver mas texto)
# ---------------------------------------------------------------------------
JS_PULSAR_BOTONES = r"""
([patron, limite]) => {
  const re = new RegExp(patron, 'i');
  const candidatos = Array.from(document.querySelectorAll(
    'div[role="button"], span[role="button"], a[role="button"], button'
  ));
  let pulsados = 0;
  for (const b of candidatos) {
    if (pulsados >= limite) break;
    const t = (b.innerText || '').trim();
    if (!t || t.length > 70) continue;
    if (!re.test(t)) continue;
    // Ignoramos lo que no se ve en pantalla (menus cerrados, etc.)
    const caja = b.getBoundingClientRect();
    if (caja.width === 0 && caja.height === 0) continue;
    try { b.click(); pulsados++; } catch (e) {}
  }
  return pulsados;
}
"""

# Abre el desplegable de orden y elige "Todos los comentarios"
JS_ABRIR_ORDEN = r"""
(patron) => {
  const re = new RegExp(patron, 'i');
  const candidatos = Array.from(document.querySelectorAll(
    'div[role="button"], span[role="button"], button'
  ));
  for (const b of candidatos) {
    const t = (b.innerText || '').trim();
    if (t && t.length < 40 && re.test(t)) {
      const caja = b.getBoundingClientRect();
      if (caja.width === 0 && caja.height === 0) continue;
      try { b.click(); return t; } catch (e) {}
    }
  }
  return "";
}
"""

JS_ELEGIR_OPCION_MENU = r"""
(patron) => {
  const re = new RegExp(patron, 'i');
  const items = Array.from(document.querySelectorAll(
    '[role="menuitem"], [role="menuitemradio"], [role="option"]'
  ));
  for (const it of items) {
    const t = (it.innerText || '').trim().split('\n')[0];
    if (t && re.test(t)) {
      try { it.click(); return t; } catch (e) {}
    }
  }
  return "";
}
"""

# ---------------------------------------------------------------------------
# Fase 2: leer los comentarios ya cargados en la pagina
# ---------------------------------------------------------------------------
JS_LEER_COMENTARIOS = r"""
([prefijoAria, selectoresTexto]) => {
  const RE_COM = new RegExp(prefijoAria, 'i');

  // Si hay un panel anclado, ese es nuestro unico terreno de juego: todo lo
  // que haya dentro pertenece con seguridad a la publicacion que procesamos.
  const anclado = document.querySelector('[data-xc-panel]');
  const raiz = anclado || document;

  const arts = Array.from(raiz.querySelectorAll('div[role="article"]'));
  const salida = [];

  // ¿Estamos en el reproductor inmersivo de Reels?
  //
  // Ojo, esto es CRITICO: ese reproductor es un carrusel vertical y mantiene
  // en la pagina las tarjetas de los reels siguientes y anteriores, con SUS
  // comentarios. Si leyeramos todo el documento mezclariamos comentarios de
  // otras publicaciones. Por eso, ahi solo aceptamos lo que esta en pantalla.
  const enReels = /^\/reels?\//.test(location.pathname);
  // Nada de margenes de cortesia: la tarjeta siguiente arranca justo en el
  // borde inferior de la pantalla, asi que con unos pocos pixeles de holgura
  // se colaba su primer comentario. Exigimos que se vea de verdad.
  const enPantalla = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    const alto = Math.min(r.bottom, window.innerHeight) - Math.max(r.top, 0);
    return alto >= Math.min(r.height, 8);
  };
  // Con el panel anclado no hace falta mirar si esta en pantalla: el ancla ya
  // garantiza que el comentario es de esta publicacion. Sin ancla, en el
  // reproductor de reels, nos quedamos solo con lo visible.
  const aceptar = (el) => anclado ? true : (!enReels || enPantalla(el));

  // ---------------------------------------------------------------------
  // Estrategia B (se usa solo si la A no encuentra nada): buscar los bloques
  // de mensaje directamente. Hace falta para los REELS, que Facebook abre en
  // un visor con panel lateral donde los comentarios NO son role="article".
  // ---------------------------------------------------------------------
  const porMensajes = () => {
    const res = [];
    const vistos = new Set();
    const esEnlacePerfil = (a) => {
      const h = a.getAttribute('href') || '';
      if (!h || h.startsWith('#')) return false;
      if (/\/(reel|reels|posts|videos|photo|watch|share)\//.test(h)) return false;
      if (/comment_id=/.test(h)) return false;
      return /^(https?:\/\/[^/]*facebook\.com)?\/(profile\.php|people\/|groups\/[^/]+\/user\/|[^/?#]+\/?($|\?))/.test(h);
    };

    selectoresTexto.forEach(sel => {
      raiz.querySelectorAll(sel).forEach(msg => {
        if (!aceptar(msg)) return;   // descarta comentarios de otras tarjetas
        const texto = (msg.innerText || '').trim();
        if (!texto) return;

        // Subimos por el arbol hasta encontrar el bloque que ademas tiene
        // el enlace al perfil de quien comenta.
        let cont = msg.parentElement, autor = '', saltos = 0;
        while (cont && saltos < 7) {
          const perfil = Array.from(cont.querySelectorAll('a[href]'))
            .find(a => esEnlacePerfil(a) && (a.innerText || '').trim().length > 1);
          if (perfil) { autor = (perfil.innerText || '').trim().split('\n')[0]; break; }
          cont = cont.parentElement; saltos++;
        }

        const clave = autor + '|' + texto;
        if (vistos.has(clave)) return;
        vistos.add(clave);

        // Fecha: el ultimo trocito corto con pinta de hora relativa
        let fecha = '';
        if (cont) {
          const trozos = Array.from(cont.querySelectorAll('a[href], span, abbr'));
          for (let i = trozos.length - 1; i >= 0; i--) {
            const t = (trozos[i].innerText || '').trim();
            if (t && t.length <= 28 && /\d/.test(t) &&
                /(seg|min|\bh\b|hora|\bd\b|d[ií]a|sem|semana|mes|año|ano|\bw\b|ago)/i.test(t)) {
              fecha = t; break;
            }
          }
        }
        res.push({autor: autor, texto: texto, fecha: fecha,
                  es_respuesta: false, reacciones: 0});
      });
    });
    return res;
  };

  const esComentario = (el) => {
    const a = (el.getAttribute('aria-label') || '').trim();
    return a && RE_COM.test(a);
  };

  // Devuelve true si el elemento pertenece directamente a este comentario
  // (y no a una respuesta anidada dentro de el).
  const esPropio = (el, art) => el.closest('div[role="article"]') === art;

  arts.forEach(art => {
    if (!esComentario(art)) return;
    if (!aceptar(art)) return;   // descarta comentarios de otras tarjetas
    const aria = (art.getAttribute('aria-label') || '').trim();

    // Profundidad: si esta dentro de otro comentario, es una respuesta
    let profundidad = 0;
    let p = art.parentElement;
    while (p) {
      if (p.matches && p.matches('div[role="article"]') && esComentario(p)) profundidad++;
      p = p.parentElement;
    }

    // Autor: sale limpio del aria-label ("Comentario de Juan Perez")
    let autor = aria.replace(RE_COM, '').trim().replace(/^[:\-\s]+/, '');
    if (!autor) {
      const link = art.querySelector('a[role="link"] span, a[role="link"]');
      autor = link ? (link.innerText || '').trim().split('\n')[0] : '';
    }

    // Texto: probamos los selectores conocidos y, si fallan, un plan B
    let texto = '';
    for (const sel of selectoresTexto) {
      const els = Array.from(art.querySelectorAll(sel)).filter(e => esPropio(e, art));
      if (els.length) {
        const t = els.map(e => (e.innerText || '').trim()).filter(Boolean).join('\n');
        if (t) { texto = t; break; }
      }
    }
    if (!texto) {
      const divs = Array.from(art.querySelectorAll('div[dir="auto"]'))
        .filter(d => esPropio(d, art));
      let mejor = '';
      divs.forEach(d => {
        const t = (d.innerText || '').trim();
        if (!t || t === autor) return;
        // Descartamos la barra de acciones del comentario
        if (/^(me gusta|responder|like|reply|compartir|share)$/i.test(t)) return;
        if (t.length > mejor.length) mejor = t;
      });
      texto = mejor;
    }

    // Fecha: el ultimo enlace corto con pinta de fecha dentro del comentario
    let fecha = '';
    const enlaces = Array.from(art.querySelectorAll('a[href]')).filter(a => esPropio(a, art));
    for (let i = enlaces.length - 1; i >= 0; i--) {
      const a = enlaces[i];
      const al = (a.getAttribute('aria-label') || '').trim();
      const t = (a.innerText || '').trim();
      if (al && /\d/.test(al) && al.length < 70) { fecha = al; break; }
      if (t && t.length <= 28 && /\d/.test(t)) { fecha = t; break; }
    }

    // Reacciones (aproximado, no siempre esta visible)
    let reacciones = 0;
    const rea = Array.from(art.querySelectorAll('[aria-label]'))
      .filter(e => esPropio(e, art))
      .find(e => /reaccion|reaction|me gusta:|likes?:/i.test(e.getAttribute('aria-label') || ''));
    if (rea) {
      const m = ((rea.innerText || '') + ' ' + (rea.getAttribute('aria-label') || ''))
        .match(/\d[\d.,]*/);
      if (m) reacciones = parseInt(m[0].replace(/[.,]/g, ''), 10) || 0;
    }

    salida.push({
      autor: autor,
      texto: texto,
      fecha: fecha,
      es_respuesta: profundidad > 0,
      reacciones: reacciones
    });
  });

  // Si la estrategia A no vio nada, probamos la B (caso tipico de los reels)
  if (salida.length === 0) {
    return {modo: 'mensajes', comentarios: porMensajes(), en_reels: enReels};
  }
  return {modo: 'articulos', comentarios: salida, en_reels: enReels};
}
"""

# Abre el panel de comentarios.
#
# CLAVE para los reels: se abren en el reproductor inmersivo con el panel de
# comentarios cerrado (el boton lleva aria-expanded="false"). Hasta que no se
# pulsa, los comentarios NO existen en la pagina: no hay nada que leer.
JS_ABRIR_COMENTARIOS = r"""
(patron) => {
  const re = new RegExp(patron, 'i');
  for (const el of Array.from(document.querySelectorAll('[aria-label]'))) {
    const etiqueta = (el.getAttribute('aria-label') || '').trim();
    if (!re.test(etiqueta)) continue;

    const caja = el.getBoundingClientRect();
    if (caja.width === 0 && caja.height === 0) continue;

    // Si Facebook ya lo marca como desplegado, no lo volvemos a pulsar
    // (lo cerrariamos).
    if (el.getAttribute('aria-expanded') === 'true') return 'ya_abierto';

    const objetivo = el.closest('[role="button"], button, a') || el;
    try { objetivo.click(); return etiqueta; } catch (e) {}
  }
  return '';
}
"""

# Cuantos comentarios anuncia Facebook (el numero junto al icono del bocadillo).
# Sirve para poder comparar: "anuncia 27, extraje 25".
JS_COMENTARIOS_ANUNCIADOS = r"""
(patron) => {
  const re = new RegExp(patron, 'i');
  for (const el of Array.from(document.querySelectorAll('[aria-label]'))) {
    if (!re.test((el.getAttribute('aria-label') || '').trim())) continue;
    let cont = el.parentElement, saltos = 0;
    while (cont && saltos < 5) {
      const t = (cont.innerText || '').trim();
      const m = t.match(/^\s*(\d[\d.,]*\s*(mil|k|m)?)\s*$/im);
      if (m) return m[1].trim();
      cont = cont.parentElement; saltos++;
    }
  }
  return '';
}
"""

# Ancla el panel de comentarios del reel que estamos procesando.
#
# Por que hace falta: el reproductor de Reels es un carrusel. Cuando el panel
# llega a su final, el scroll se propaga a la pagina y salta al reel siguiente.
# A partir de ahi los comentarios del vecino TAMBIEN estan en pantalla, asi que
# filtrar "por lo visible" ya no basta. Marcamos el panel una vez y despues solo
# leemos y desplazamos DENTRO de el: si el carrusel se mueve, nos da igual.
JS_ANCLAR_PANEL = r"""
([selectoresTexto, prefijoAria]) => {
  document.querySelectorAll('[data-xc-panel]').forEach(
    e => e.removeAttribute('data-xc-panel'));

  const RE = new RegExp(prefijoAria, 'i');
  let nodos = [];
  selectoresTexto.forEach(s => {
    nodos = nodos.concat(Array.from(document.querySelectorAll(s)));
  });
  Array.from(document.querySelectorAll('div[role="article"]')).forEach(a => {
    const al = (a.getAttribute('aria-label') || '').trim();
    if (al && RE.test(al)) nodos.push(a);
  });

  const visibles = nodos.filter(n => {
    const r = n.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    const alto = Math.min(r.bottom, window.innerHeight) - Math.max(r.top, 0);
    return alto >= Math.min(r.height, 8);
  });
  if (!visibles.length) return {ok: false, motivo: 'no hay comentarios visibles'};

  // Subimos desde el primer comentario visible hasta su contenedor con scroll
  let el = visibles[0], panel = null, saltos = 0;
  while (el && saltos < 15) {
    const ov = getComputedStyle(el).overflowY;
    if ((ov === 'auto' || ov === 'scroll') && el.scrollHeight > el.clientHeight + 40) {
      panel = el; break;
    }
    el = el.parentElement; saltos++;
  }
  if (!panel) return {ok: false, motivo: 'sin panel con scroll propio'};

  panel.setAttribute('data-xc-panel', '1');
  return {ok: true, visibles: visibles.length};
}
"""

# Desplaza el panel lateral de comentarios (los reels y el visor de fotos usan
# un contenedor con scroll propio: mover la pagina entera no sirve de nada).
JS_DESPLAZAR_PANEL = r"""
() => {
  // Si hay panel anclado desplazamos ESE, no "el que mas scroll tenga":
  // ese otro podria ser el panel de una tarjeta vecina del carrusel.
  const anclado = document.querySelector('[data-xc-panel]');
  if (anclado) {
    const antes = anclado.scrollTop;
    anclado.scrollTop = antes + Math.max(300, anclado.clientHeight * 0.7);
    return {
      encontrado: true,
      anclado: true,
      se_movio: anclado.scrollTop > antes,
      al_final: (anclado.scrollTop + anclado.clientHeight) >= (anclado.scrollHeight - 100)
    };
  }

  let mejor = null, mejorAlto = 0;
  document.querySelectorAll('div').forEach(d => {
    if (d.clientHeight < 200) return;
    if (d.scrollHeight - d.clientHeight < 150) return;
    const ov = getComputedStyle(d).overflowY;
    if (ov !== 'auto' && ov !== 'scroll') return;
    if (d.scrollHeight > mejorAlto) { mejorAlto = d.scrollHeight; mejor = d; }
  });
  if (!mejor) return {encontrado: false, al_final: true};
  const antes = mejor.scrollTop;
  mejor.scrollTop = antes + Math.max(300, mejor.clientHeight * 0.7);
  return {
    encontrado: true,
    se_movio: mejor.scrollTop > antes,
    al_final: (mejor.scrollTop + mejor.clientHeight) >= (mejor.scrollHeight - 100)
  };
}
"""

# Datos de la propia publicacion abierta (fecha exacta y texto)
JS_DATOS_PUBLICACION = r"""
(idObjetivo) => {
  const html = document.documentElement.innerHTML;

  // Eleccion de la fecha: NO vale coger el primer "creation_time" del HTML.
  //
  // La pagina de un reel trae SIEMPRE dos: el del reel y el de la tarjeta que
  // el carrusel precarga detras. Comprobado sobre paginas reales, pueden
  // diferir en semanas o meses, y cual aparece primero es indiferente. Coger
  // el primero equivale a echarlo a suertes.
  //
  // El que vale es el que esta pegado al identificador de ESTA publicacion:
  // en las paginas medidas, 390 caracteres frente a 12.494 del ajeno.
  const cts = [];
  const reCT = /"creation_time"\s*:\s*(\d{10})/g;
  let m;
  while ((m = reCT.exec(html)) !== null) cts.push([m.index, parseInt(m[1], 10)]);

  let creacion = null;
  let confianza = 'ninguna';

  if (cts.length === 1) {
    // Publicacion normal: no hay ambiguedad posible
    creacion = cts[0][1];
    confianza = 'unica';
  } else if (cts.length > 1 && idObjetivo) {
    const posiciones = [];
    let desde = 0, k;
    while ((k = html.indexOf(idObjetivo, desde)) !== -1) {
      posiciones.push(k);
      desde = k + 1;
      if (posiciones.length > 500) break;
    }
    let mejor = null, mejorDist = Infinity;
    for (const par of cts) {
      for (const q of posiciones) {
        const d = Math.abs(par[0] - q);
        if (d < mejorDist) { mejorDist = d; mejor = par[1]; }
      }
    }
    // Si ninguna fecha esta cerca del id, preferimos NO dar fecha antes que
    // dar una equivocada: una fecha mala ensucia todo el rango.
    if (mejor !== null && mejorDist <= 5000) {
      creacion = mejor;
      confianza = 'por_id';
    }
  }

  // Texto del post. Importante: hay que saltarse los bloques que estan dentro
  // de un comentario, o acabariamos guardando el comentario en vez del post.
  const RE_COM = /^(coment(a|á)rio de|comentario de|comment by|respuesta de|reply by)/i;
  const dentroDeComentario = (el) => {
    let p = el.parentElement;
    while (p) {
      if (p.matches && p.matches('div[role="article"]')) {
        const a = (p.getAttribute('aria-label') || '').trim();
        if (a && RE_COM.test(a)) return true;
      }
      p = p.parentElement;
    }
    return false;
  };

  let texto = '';
  const sel = [
    '[data-ad-rendering-role="story_message"]',
    '[data-ad-comet-preview="message"]',
    '[data-ad-preview="message"]'
  ];
  for (const s of sel) {
    const el = Array.from(document.querySelectorAll(s))
      .find(e => (e.innerText || '').trim() && !dentroDeComentario(e));
    if (el) { texto = el.innerText.trim(); break; }
  }
  // Ultimo recurso (habitual en reels, que no tienen bloque de mensaje):
  // la descripcion que Facebook publica en las etiquetas <meta>.
  if (!texto) {
    const meta = document.querySelector('meta[property="og:description"]')
              || document.querySelector('meta[name="description"]');
    if (meta) texto = (meta.getAttribute('content') || '').trim();
  }

  // Numero de comentarios que Facebook anuncia (solo informativo)
  let anunciados = '';
  const cand = Array.from(document.querySelectorAll('span, div[role="button"]'))
    .map(e => (e.innerText || '').trim())
    .find(t => t && t.length < 40 && /comentarios?|comments?/i.test(t) && /\d/.test(t));
  if (cand) anunciados = cand;

  return {creacion: creacion, confianza: confianza, fechas_en_pagina: cts.length,
          texto: texto.slice(0, 500), anunciados: anunciados,
          url: location.href};
}
"""
