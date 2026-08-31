"""JavaScript que se ejecuta dentro de las paginas de Instagram.

Instagram tiene una ventaja enorme sobre Facebook: publica la fecha exacta
en el propio HTML, en etiquetas <time datetime="2026-08-20T14:32:00.000Z">.
No hay que cazar "creation_time" ni interpretar «hace 3 h».

Pero se aplica la misma leccion que nos costo cara en Facebook: en la pagina
de una publicacion hay MUCHOS <time>, uno por cada comentario. Hay que saber
cual es el de la publicacion, o le asignaremos la hora de un comentario.
"""

# ---------------------------------------------------------------------------
# Fase 1: recolectar enlaces a publicaciones desde la cuadricula del perfil
# ---------------------------------------------------------------------------
JS_ENLACES_PUBLICACIONES = r"""
(patrones) => {
  const coincide = (h) => patrones.some(p => h.includes(p));
  const salida = [];
  const vistos = new Set();

  // Recorremos toda la pagina, no solo un contenedor concreto: la cuadricula
  // del perfil cambia de estructura a menudo y asi no dependemos de ella.
  document.querySelectorAll('a[href]').forEach(a => {
    const href = a.href || '';
    if (!href || !coincide(href)) return;
    if (vistos.has(href)) return;
    vistos.add(href);

    // Si hubiera una fecha a mano (no suele haberla en la cuadricula) la
    // aprovechamos; si no, ya la preguntaremos abriendo la publicacion.
    const t = a.querySelector('time[datetime]');
    const alt = a.querySelector('img[alt]');

    salida.push({
      href: href,
      fecha_iso: t ? t.getAttribute('datetime') : '',
      texto: alt ? (alt.getAttribute('alt') || '').slice(0, 200) : ''
    });
  });
  return salida;
}
"""

# ---------------------------------------------------------------------------
# Datos de UNA publicacion abierta: fecha exacta y texto del pie
# ---------------------------------------------------------------------------
JS_DATOS_PUBLICACION = r"""
(codigo) => {
  const html = document.documentElement.innerHTML;
  const tiempos = Array.from(document.querySelectorAll('time[datetime]'));
  let fecha = '', confianza = 'ninguna', epoch = null;

  // ---- Regla 0: "taken_at", el sello de tiempo que Instagram incrusta ----
  //
  // Es el equivalente al creation_time de Facebook, y trae la MISMA trampa:
  // en la pagina hay varios, uno por cada publicacion precargada. Medido
  // sobre una pagina real, el de la publicacion estaba a 2.848 caracteres de
  // su codigo y el ajeno a 32.204. Nos quedamos con el mas cercano.
  const tas = [];
  const reTa = /"taken_at"\s*:\s*(\d{9,11})/g;
  let m;
  while ((m = reTa.exec(html)) !== null) tas.push([m.index, parseInt(m[1], 10)]);

  if (tas.length === 1) {
    epoch = tas[0][1];
    confianza = 'taken_at_unico';
  } else if (tas.length > 1 && codigo) {
    const posiciones = [];
    let desde = 0, k;
    while ((k = html.indexOf(codigo, desde)) !== -1) {
      posiciones.push(k);
      desde = k + 1;
      if (posiciones.length > 500) break;
    }
    let mejor = null, mejorDist = Infinity;
    for (const par of tas) {
      for (const q of posiciones) {
        const d = Math.abs(par[0] - q);
        if (d < mejorDist) { mejorDist = d; mejor = par[1]; }
      }
    }
    if (mejor !== null && mejorDist <= 8000) {
      epoch = mejor;
      confianza = 'taken_at_por_codigo';
    }
  }

  // Regla 1 (la buena): el <time> de la publicacion cuelga de un enlace que
  // apunta a ESTA publicacion. Los <time> de los comentarios cuelgan del
  // permalink del comentario, que lleva /c/ en la ruta.
  if (codigo) {
    for (const t of tiempos) {
      const a = t.closest('a[href]');
      if (!a) continue;
      const h = a.getAttribute('href') || '';
      if (h.includes(codigo) && !h.includes('/c/')) {
        fecha = t.getAttribute('datetime') || '';
        confianza = 'por_enlace';
        break;
      }
    }
  }

  // Regla 2 (respaldo): una publicacion es SIEMPRE anterior a sus propios
  // comentarios, asi que la fecha mas antigua es la suya.
  // Nos ceñimos al <article> para no confundirnos con las "publicaciones
  // sugeridas" que Instagram enseña mas abajo.
  if (!fecha) {
    const art = document.querySelector('article');
    if (art) {
      const dentro = Array.from(art.querySelectorAll('time[datetime]'))
        .map(t => t.getAttribute('datetime'))
        .filter(Boolean)
        .sort();
      if (dentro.length) { fecha = dentro[0]; confianza = 'mas_antigua'; }
    }
  }

  // Regla 3 (ultimo recurso): en la pagina de una publicacion, la fecha de la
  // cabecera va antes que la de cualquier comentario, asi que el primer
  // <time> del documento suele ser el bueno. Menos fiable, se marca como tal.
  if (!fecha && tiempos.length) {
    fecha = tiempos[0].getAttribute('datetime') || '';
    if (fecha) confianza = 'primera_de_la_pagina';
  }

  // ---- og:description: la fuente mas honesta que tiene Instagram ----
  //
  // Las etiquetas og: describen SIEMPRE la publicacion de esta pagina, asi
  // que aqui no hay ambiguedad posible. Formato real:
  //   "305 likes, 5 comments - medellinnvivo el June 24, 2026: "texto""
  // De ahi salen la fecha, el numero de comentarios y el pie de foto.
  let og = '';
  const meta = document.querySelector('meta[property="og:description"]');
  if (meta) og = (meta.getAttribute('content') || '').trim();

  let fechaOg = '', anunciados = '';
  if (og) {
    const mf = og.match(/\b(?:el|on)\s+(.{4,40}?)\s*:/i);
    if (mf) fechaOg = mf[1].trim();
    const mc = og.match(/(\d[\d.,]*)\s*(?:comment|comentario)/i);
    if (mc) anunciados = mc[1];
  }

  // Texto del pie de foto: lo que va tras los dos puntos
  let texto = og;
  const mt = og.match(/:\s*"([^"]*)"/);
  if (mt) texto = mt[1];

  return {epoch: epoch, fecha: fecha, fecha_og: fechaOg, confianza: confianza,
          tiempos_en_pagina: tiempos.length, taken_at_en_pagina: tas.length,
          texto: (texto || '').slice(0, 400), anunciados: anunciados,
          url: location.href};
}
"""

# ---------------------------------------------------------------------------
# Leer los comentarios cargados
# ---------------------------------------------------------------------------
JS_LEER_COMENTARIOS = r"""
([codigo, pieDeFoto]) => {
  // IMPORTANTE: no se puede exigir un <time> en cada comentario. Instagram
  // dejo de pintarlos (medido: cero en toda la pagina), asi que un lector que
  // dependiera de ellos no encontraria nada aunque el panel estuviera abierto.
  //
  // Un comentario se reconoce por: enlace al perfil de quien comenta + texto
  // que no sea solo el nombre. El pie de foto tiene esa misma forma, y se
  // descarta comparandolo con el que anuncia og:description.
  const anclado = document.querySelector('[data-xc-panel]');
  const raiz = anclado || document.querySelector('article') || document.body;

  const limpio = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const pie = limpio(pieDeFoto);

  const esPerfil = (a) => {
    const h = a.getAttribute('href') || '';
    if (!/^\/[^/?#]+\/?$/.test(h)) return false;
    return !/^\/(p|reel|reels|tv|explore|accounts|direct|stories)\/?$/i.test(h);
  };

  // Trozos que NO son el comentario: marcas de tiempo («1 d», «hace 2 h»),
  // botones y contadores. Sin esto se guardaba la hora como si fuera el texto.
  const esRuido = (t) => {
    if (!t) return true;
    if (/^(hace\s+)?\d+\s*(s|seg|segundos?|min|mins?|minutos?|m|h|hr|horas?|d|d[ií]as?|sem|semanas?|w|mes|meses|a|años?|anos?|y)\.?$/i.test(t)) return true;
    if (/^(me gusta|responder|reply|like|likes?|compartir|share|editado|edited|verificado|verified|autor|traducci[oó]n|ver traducci[oó]n|see translation|original|mostrar m[aá]s|ver m[aá]s|more)$/i.test(t)) return true;
    if (/^\d[\d.,]*\s*(me gusta|likes?|respuestas?|replies|comentarios?|comments?)$/i.test(t)) return true;
    return false;
  };

  const salida = [];
  const vistos = new Set();

  Array.from(raiz.querySelectorAll('a[href]')).forEach(a => {
    if (!esPerfil(a)) return;
    const autor = limpio(a.innerText).split(' ')[0];
    if (!autor || autor.length > 40) return;

    // Subimos hasta el bloque del comentario y, DENTRO de el, buscamos el
    // trozo de texto de verdad.
    //
    // No vale quedarse con el primer ancestro que tenga algo mas que el
    // nombre: ese suele ser <a>ana</a><span>1 d</span>, y acabariamos
    // guardando «1 d» como si fuera el comentario. Hay que descartar horas,
    // botones y contadores, y quedarse con el trozo mas largo que quede.
    // Buscamos, dentro del bloque del comentario, el trozo que es el texto.
    //
    // Hay que descartar tres cosas distintas:
    //   - lo que va dentro de un enlace (el nombre, los hashtags del perfil)
    //   - los envoltorios, que empiezan por el nombre de quien comenta
    //     («ana1 d…»); ojo, innerText NO separa elementos inline, asi que
    //     nombre y hora salen pegados
    //   - las filas de botones («12 me gustaResponder»), que se reconocen
    //     porque TODOS sus hijos son ruido
    const soloRuidoDentro = (e) => {
      const hijos = Array.from(e.children);
      if (!hijos.length) return false;
      const textos = hijos.map(h => limpio(h.innerText)).filter(Boolean);
      return textos.length > 0 && textos.every(esRuido);
    };

    let cont = a.parentElement, texto = '', saltos = 0;
    while (cont && cont !== raiz && saltos < 6) {
      const trozos = Array.from(cont.querySelectorAll('span, div, p'))
        .filter(e => !e.closest('a') && !soloRuidoDentro(e))
        .map(e => limpio(e.innerText))
        .filter(t => t && t !== autor && !esRuido(t) && !t.startsWith(autor));
      if (trozos.length) {
        texto = trozos.reduce((x, y) => (y.length > x.length ? y : x), '');
        if (texto) break;
      }
      cont = cont.parentElement; saltos++;
    }
    if (!texto || esRuido(texto)) return;

    // El pie de foto NO es un comentario
    if (pie && (texto === pie || texto.startsWith(pie.slice(0, 40)))) return;

    const clave = autor + '|' + texto;
    if (vistos.has(clave)) return;
    vistos.add(clave);

    const t = cont ? cont.querySelector('time[datetime]') : null;

    salida.push({
      autor: autor,
      texto: texto,
      fecha: t ? (t.getAttribute('datetime') || '') : '',
      es_respuesta: false,
      reacciones: 0
    });
  });

  return {modo: 'instagram', comentarios: salida, anclado: !!anclado};
}
"""

JS_LEER_COMENTARIOS_ANTIGUO = r"""
([codigo, fechaPublicacion]) => {
  // Si hay panel anclado, solo leemos dentro de el (misma leccion que en
  // Facebook: evita mezclar con publicaciones sugeridas de mas abajo).
  const anclado = document.querySelector('[data-xc-panel]');
  const raiz = anclado || document.querySelector('article') || document;

  const salida = [];
  const vistos = new Set();

  // Un comentario es un bloque que tiene: enlace al perfil de quien comenta,
  // un texto, y su propia marca de tiempo.
  const bloques = Array.from(raiz.querySelectorAll('li, div[role="button"] ~ div, div'));

  const esEnlacePerfil = (a) => {
    const h = a.getAttribute('href') || '';
    if (!h.startsWith('/')) return false;
    if (/\/(p|reel|tv|explore|accounts|direct)\//.test(h)) return false;
    return /^\/[^/]+\/?$/.test(h);
  };

  bloques.forEach(b => {
    const t = b.querySelector('time[datetime]');
    if (!t) return;
    const fecha = t.getAttribute('datetime') || '';

    // El pie de foto tiene la misma pinta que un comentario pero NO lo es:
    // se reconoce porque lleva la misma marca de tiempo que la publicacion.
    if (fechaPublicacion && fecha === fechaPublicacion) return;

    const enlace = Array.from(b.querySelectorAll('a[href]')).find(esEnlacePerfil);
    if (!enlace) return;
    const autor = (enlace.innerText || '').trim().split('\n')[0];
    if (!autor) return;

    // El texto es lo que queda al quitar el nombre y los adornos
    let texto = '';
    const spans = Array.from(b.querySelectorAll('span'))
      .filter(s => !s.querySelector('a') && !s.querySelector('time'));
    for (const s of spans) {
      const v = (s.innerText || '').trim();
      if (!v || v === autor) continue;
      if (/^(responder|reply|me gusta|like|\d+\s*(me gusta|likes?))$/i.test(v)) continue;
      if (v.length > texto.length) texto = v;
    }
    if (!texto) return;

    // Nos quedamos con el bloque MAS PEQUEÑO de cada comentario: al recorrer
    // todos los div, el mismo comentario aparece dentro de varios ancestros.
    const clave = autor + '|' + texto;
    if (vistos.has(clave)) return;
    vistos.add(clave);

    // ¿Es una respuesta? Las respuestas van anidadas mas adentro.
    let profundidad = 0, p = b.parentElement;
    while (p && p !== raiz) {
      if (p.tagName === 'UL' || p.tagName === 'LI') profundidad++;
      p = p.parentElement;
    }

    salida.push({
      autor: autor,
      texto: texto,
      fecha: fecha,
      es_respuesta: profundidad >= 3,
      reacciones: 0
    });
  });

  return {modo: 'instagram', comentarios: salida, anclado: !!anclado};
}
"""

# Abre el panel de comentarios cuando acabamos en el visor de Reels.
#
# Ese visor es un carrusel: carga catorce publicaciones a la vez, incluidas
# reels de OTRAS cuentas, y todas traen su boton «Comentario». Por eso solo se
# pulsa el que esta visible en pantalla, que es el de la publicacion activa.
JS_ABRIR_COMENTARIOS = r"""
(patron) => {
  const re = new RegExp(patron, 'i');
  const enPantalla = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    const alto = Math.min(r.bottom, window.innerHeight) - Math.max(r.top, 0);
    return alto >= Math.min(r.height, 8);
  };
  for (const el of Array.from(document.querySelectorAll('[aria-label]'))) {
    const etiqueta = (el.getAttribute('aria-label') || '').trim();
    if (!re.test(etiqueta)) continue;
    if (!enPantalla(el)) continue;
    const objetivo = el.closest('[role="button"], button, a, div[tabindex]') || el;
    try { objetivo.click(); return etiqueta; } catch (e) {}
  }
  return '';
}
"""

# Ancla el contenedor con scroll propio donde viven los comentarios
JS_ANCLAR_PANEL = r"""
() => {
  document.querySelectorAll('[data-xc-panel]').forEach(
    e => e.removeAttribute('data-xc-panel'));

  // Buscamos el contenedor con scroll propio que MAS comentarios contiene.
  //
  // No vale partir del ultimo <time> de la pagina y subir: ese suele estar en
  // las «mas publicaciones de este perfil» del final, fuera del area de
  // comentarios, y entonces no se encuentra ningun panel.
  // Contamos enlaces a perfil, no <time>: Instagram ya no pinta ninguno.
  const esPerfil = (a) => {
    const h = a.getAttribute('href') || '';
    return /^\/[^/?#]+\/?$/.test(h)
        && !/^\/(p|reel|reels|tv|explore|accounts|direct|stories)\/?$/i.test(h);
  };
  let mejor = null, mejorN = 0;
  document.querySelectorAll('div, ul, section').forEach(d => {
    const ov = getComputedStyle(d).overflowY;
    if (ov !== 'auto' && ov !== 'scroll') return;
    if (d.clientHeight < 120) return;
    if (d.scrollHeight <= d.clientHeight + 40) return;
    const n = Array.from(d.querySelectorAll('a[href]')).filter(esPerfil).length;
    if (n > mejorN) { mejorN = n; mejor = d; }
  });

  if (!mejor) return {ok: false, motivo: 'sin panel de comentarios con scroll'};
  mejor.setAttribute('data-xc-panel', '1');
  return {ok: true, comentarios_dentro: mejorN};
}
"""

JS_DESPLAZAR_PANEL = r"""
() => {
  const anclado = document.querySelector('[data-xc-panel]');
  const destino = anclado || (() => {
    let mejor = null, alto = 0;
    document.querySelectorAll('div').forEach(d => {
      if (d.clientHeight < 150) return;
      if (d.scrollHeight - d.clientHeight < 100) return;
      const ov = getComputedStyle(d).overflowY;
      if (ov !== 'auto' && ov !== 'scroll') return;
      if (d.scrollHeight > alto) { alto = d.scrollHeight; mejor = d; }
    });
    return mejor;
  })();
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

# --------------------------------------------------------------- utilidades
JS_PULSAR_BOTONES = r"""
([patron, limite]) => {
  const re = new RegExp(patron, 'i');
  const candidatos = Array.from(document.querySelectorAll(
    'button, div[role="button"], span[role="button"], a[role="link"]'
  ));
  let pulsados = 0;
  for (const b of candidatos) {
    if (pulsados >= limite) break;
    const t = ((b.innerText || '') + ' ' + (b.getAttribute('aria-label') || '')).trim();
    if (!t || t.length > 70) continue;
    if (!re.test(t)) continue;
    if (/ocultar|hide/i.test(t)) continue;   // no plegar lo ya desplegado
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
    ventana: window.innerHeight,
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
  // Si aparece el formulario de acceso, no hay sesion
  if (document.querySelector('input[name="username"]')) return false;
  if (/\/accounts\/login/.test(location.pathname)) return false;
  // Con sesion siempre hay barra de navegacion con enlaces propios
  return !!document.querySelector('a[href="/direct/inbox/"], svg[aria-label*="Inicio"], a[href*="/explore/"]');
}
"""
