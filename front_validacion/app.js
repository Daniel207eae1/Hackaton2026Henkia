/* =====================================================================
   app.js · Avance del guion, cambio de vistas y render desde datos.js
   ---------------------------------------------------------------------
   Lógica MÍNIMA: no hay reglas de negocio reales, ni parsers, ni agentes.
   El "motor" solo recorre los pasos predefinidos de cada escenario,
   se detiene donde el guion exige una decisión humana (consentimiento,
   aprobación N2, adjuntar captura) y acumula el estado para mostrarlo.
   Además comprueba, como autoverificación, que los DATOS del guion
   respetan las invariantes (p. ej., que ninguna `accion` llegue sin un
   consentimiento previo). Si alguna se rompe, la pinta en rojo.
   ===================================================================== */
(function () {
  'use strict';

  var FV = window.FV = {};

  /* ------------------------------------------------------------ util */
  FV.esc = function (t) {
    return String(t == null ? '' : t).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  };
  FV.param = function (n) { return new URLSearchParams(location.search).get(n); };
  FV.caso = function (id) { return window.CASOS.filter(function (c) { return String(c.id) === String(id); })[0] || null; };
  FV.cat = function (id) { return window.CATALOGO.filter(function (a) { return a.id === id; })[0] || null; };
  FV.clonar = function (o) { return JSON.parse(JSON.stringify(o)); };
  function pad(n, l) { n = String(n); while (n.length < (l || 2)) { n = '0' + n; } return n; }
  function aSeg(h) { var p = String(h || '').split(':').map(function (x) { return parseInt(x, 10); }); var t = p[0] * 3600 + p[1] * 60 + (p[2] || 0); return isNaN(t) ? -1 : t; }
  function aHora(s) { return pad(Math.floor(s / 3600)) + ':' + pad(Math.floor(s / 60) % 60) + ':' + pad(s % 60); }
  function hash(t) { var h = 5381; for (var i = 0; i < t.length; i++) { h = ((h << 5) + h + t.charCodeAt(i)) >>> 0; } return 'h-sim-' + h.toString(16); }
  function el(id) { return document.getElementById(id); }

  /* ---------------------------------------------------- almacenamiento
     sessionStorage con try/catch: si falla, todo sigue funcionando en
     memoria y aparece el botón manual "Simular aprobación N2". */
  FV.almacen = (function () {
    var ok = true;
    try { sessionStorage.setItem('fv_prueba', '1'); sessionStorage.removeItem('fv_prueba'); } catch (e) { ok = false; }
    return {
      ok: ok,
      get: function (k) { if (!ok) { return null; } try { var v = sessionStorage.getItem(k); return v == null ? null : JSON.parse(v); } catch (e) { return null; } },
      set: function (k, v) { if (!ok) { return false; } try { sessionStorage.setItem(k, JSON.stringify(v)); return true; } catch (e) { return false; } },
      del: function (k) { if (!ok) { return; } try { sessionStorage.removeItem(k); } catch (e) { /* nada */ } }
    };
  })();
  FV.clave = {
    log: function (id) { return 'fv_log_' + id; },
    aprob: function (id) { return 'fv_aprob_' + id; },
    masivo: function (id) { return 'fv_masivo_' + id; },
    evaluacion: function (id) { return 'fv_eval_' + id; },
    kb: function (pid) { return 'fv_kb_' + pid; },
    check: function (i) { return 'fv_check_' + i; }
  };

  /* --------------------------------------------- etiquetas y leyendas */
  FV.MARCAS = { ok: '✓', hallazgo: '✗', fallo: '⚠' };
  FV.MARCA_TXT = { ok: 'consulta correcta, nada anormal', hallazgo: 'consulta correcta, encontró una anomalía', fallo: 'la consulta falló' };
  FV.RESULTADO_TXT = { cerrado: 'Cerrado', escalado: 'Escalado a N2', vinculado_masivo: 'Vinculado a masivo', derivado: 'Derivado', pendiente_revision: 'Pendiente de revisión' };
  FV.MODULO_TXT = { nucleo: 'Núcleo', A: 'Módulo A', B: 'Módulo B' };
  FV.POLITICA_TXT = { automatica: 'automática', consentimiento: 'consentimiento', aprobacion_n2: 'aprobación N2', prohibida: 'prohibida' };

  FV.badgeRiesgo = function (r) { return '<span class="badge riesgo-' + r + '">riesgo ' + FV.esc(r) + '</span>'; };
  FV.badgePolitica = function (p) { return '<span class="badge politica-' + p + '">' + FV.esc(FV.POLITICA_TXT[p] || p) + '</span>'; };
  FV.badgeEstadoHip = function (e) { return '<span class="badge hip-' + e + '">' + FV.esc(e.replace('_', ' ')) + '</span>'; };
  FV.badgeResultado = function (r) { return '<span class="badge res-' + r + '">' + FV.esc(FV.RESULTADO_TXT[r] || r) + '</span>'; };

  /* ===================================================================
     MOTOR DEL GUION
     =================================================================== */
  var ESTADO_POR_TIPO = {
    consentimiento: 'Consentimiento', aprobacion_n2: 'AprobacionN2', accion: 'Ejecucion',
    verificacion: 'Verificacion', escalamiento: 'Escalar', cierre: 'Cierre', vinculo_masivo: 'InformarMasivo'
  };
  var PASOS_INDIVIDUALES = ['hipotesis', 'consentimiento', 'aprobacion_n2', 'accion', 'verificacion'];

  FV.crearMotor = function (caso, opts) {
    opts = opts || {};
    var s = {
      caso: caso, cola: FV.clonar(caso.pasos), items: [], pausa: null, terminado: false,
      grafo: null, visitados: [], hip: {}, revisiones: [], acciones: [], tokens: [], tokenVigente: null,
      aprobaciones: {}, banderas: [], rechazos: [], capturas: [], preguntas: [], senales: [],
      masivoVinculado: null, escalamiento: null, cierre: null, errores: [], decisiones: [],
      telemetriaConsultada: false, sintomaUsuario: null, inyecciones: 0, nTok: 0, horaUlt: -1,
      esperaEscalarPorHumano: false, pasosPrincipalesMostrados: 0, aprobManual: {}, masivoManual: null,
      masivo: { estado: 'no_evaluado', categoria: null, confianza: null, cluster: [], usuarios: null, ventana: null, similitud_media: null, umbral: null, k: null,
        regla: null, tablero: null, fuente: null, mensaje: null, hora_mensaje: null, incidente: null, suscripcion: false, vinculado: false, pendienteN2: false, propuesta: null, decisionN2: null, resuelto: null }
    };
    (caso.hipotesis || []).forEach(function (h) { s.hip[h.id] = { estado: 'pendiente', evidencia: null, hora: null }; });

    function error(regla, texto) { s.errores.push({ regla: regla, texto: texto }); s.items.push({ tipo: 'error', regla: regla, texto: texto, hora: aHora(Math.max(s.horaUlt, 0)) }); }
    function horaDe(p) {
      var t = p && p.hora ? aSeg(p.hora) : -1;
      if (t <= s.horaUlt) { t = s.horaUlt + 5; }
      s.horaUlt = t; return aHora(t);
    }
    function visitar(est) {
      [].concat(est || []).forEach(function (e) { s.grafo = e; if (s.visitados.indexOf(e) < 0) { s.visitados.push(e); } });
    }
    function slot(nombre) { return (caso.sintoma.slots || []).filter(function (x) { return x.nombre === nombre; })[0]; }

    function textoTarjeta(p, cat) {
      return 'Qué haré: ' + (p.detalle || cat.descripcion) + ' | Qué efecto tiene: ' + cat.aviso_obligatorio + ' | Cómo se revierte: ' + cat.reversion + ' | Riesgo: ' + cat.riesgo;
    }

    function sugerirSiguiente() {
      var conf = caso.hipotesis.filter(function (h) { return s.hip[h.id].estado === 'confirmada'; });
      var pend = caso.hipotesis.filter(function (h) { return s.hip[h.id].estado === 'pendiente'; });
      if (!s.telemetriaConsultada) { return 'Iniciar el diagnóstico: todavía no se consultó la telemetría del equipo (se puede hacer sin preguntarle al usuario).'; }
      if (conf.length) { return 'Retomar con la hipótesis confirmada ' + conf[0].id + ' (' + conf[0].descripcion + ', ' + conf[0].kb + ') y aplicar su solución con el usuario.'; }
      if (pend.length) { return 'Continuar el diagnóstico con las hipótesis sin probar: ' + pend.map(function (h) { return h.id + ' (' + h.kb + ')'; }).join(', ') + '.'; }
      return 'Revisar el caso desde el estado «' + (s.grafo || 'Recepcion') + '».';
    }

    function escalamientoGenerico(motivo, ansKey, texto) {
      return { tipo: 'escalamiento', generico: true, ans: ansKey, motivo: motivo, siguiente_paso: sugerirSiguiente(), hora: aHora(s.horaUlt + 5),
        texto: texto || 'Entendido. Te paso con una persona de soporte ahora mismo, con todo lo que llevamos revisado; no tendrás que repetir nada.' };
    }

    function procesar(p) {
      var hora = horaDe(p);
      var item = { tipo: p.tipo, paso: p, hora: hora };
      if (p.estado) { visitar(p.estado); } else if (ESTADO_POR_TIPO[p.tipo]) { visitar(ESTADO_POR_TIPO[p.tipo]); } else if (!s.grafo) { visitar('Recepcion'); }

      if (s.masivo.estado === 'masivo_confirmado' && PASOS_INDIVIDUALES.indexOf(p.tipo) >= 0) {
        error('masivo', 'Paso individual «' + p.tipo + '» en un incidente masivo confirmado.');
      }
      if (s.masivo.pendienteN2 && (PASOS_INDIVIDUALES.indexOf(p.tipo) >= 0 || (p.tipo === 'msg_sistema' && p.guia))) {
        error('posible_masivo', 'Paso «' + p.tipo + (p.guia ? ' (guía)' : '') + '» mientras el posible masivo espera a N2: solo se permiten pruebas de lectura.');
      }
      if (s.esperaEscalarPorHumano && p.tipo !== 'escalamiento') {
        error('humano', 'El usuario pidió una persona y el guion siguió con «' + p.tipo + '» en vez de escalar.');
      }

      switch (p.tipo) {
        case 'msg_usuario':
          if (!s.sintomaUsuario && !p.captura) { s.sintomaUsuario = p.texto; }
          if (p.senal) { s.senales.push({ senal: p.senal, hora: hora }); }
          if (p.pide_humano) { s.esperaEscalarPorHumano = true; }
          s.items.push(item); break;

        case 'msg_sistema':
          if (p.pregunta) {
            var sl = slot(p.pregunta);
            s.preguntas.push({ slot: p.pregunta, hora: hora, origen: sl ? sl.origen : 'desconocido' });
            if (sl && sl.origen === 'telemetria') { error('slots', 'Pregunta por «' + p.pregunta + '», que tiene origen telemetría.'); }
          }
          if (p.guia && (!p.kb || String(p.texto).indexOf(p.kb) < 0)) { error('kb', 'Paso guiado sin cita a un artículo KB-SIM.'); }
          if (p.cita_masivo) {
            if (!s.masivo.mensaje) { error('masivo', 'Se quiere citar el aviso oficial del masivo, pero no hay mensaje publicado.'); }
            item.cita = { fuente: s.masivo.fuente, mensaje: s.masivo.mensaje, hora: s.masivo.hora_mensaje };
          }
          s.items.push(item); break;

        case 'revisando':
          (p.lineas || []).forEach(function (l) {
            var r = FV.clonar(l); r.hora = hora; s.revisiones.push(r);
            if (l.fuente === 'telemetria') { s.telemetriaConsultada = true; }
            if (l.efecto_masivo) { Object.keys(l.efecto_masivo).forEach(function (k) { s.masivo[k] = FV.clonar(l.efecto_masivo[k]); }); }
            if (l.inyeccion) {
              // La bandera queda en el estado en el mismo instante en que el extractor la detecta,
              // aunque el aviso visible al usuario llegue en el paso `bandera` siguiente.
              s.inyecciones++;
              s.banderas.push({ categoria: 'inyeccion', texto: 'Instrucciones detectadas en texto no confiable (' + l.herramienta + ').', detalle: l.resultado, hora: hora, mostrada: false });
            }
          });
          if ([].concat(p.estado || []).indexOf('ChequeoMasivo') >= 0 && s.masivo.estado === 'no_evaluado') { s.masivo.estado = 'sin_masivo'; s.masivo.regla = 'Sin clúster de reportes similares ni incidente en el tablero'; }
          s.items.push(item); break;

        case 'propuesta_masivo':
          if (s.masivo.estado !== 'posible_masivo') { error('datos', 'propuesta_masivo sin un clúster «posible_masivo» previo.'); break; }
          s.masivo.pendienteN2 = true; s.masivo.propuesta = FV.clonar(p.propuesta);
          s.items.push(item); break;

        case 'espera_masivo':
          if (!s.masivo.pendienteN2) { error('datos', 'espera_masivo sin propuesta a N2.'); break; }
          item.resolucion = null;
          s.items.push(item); s.pausa = { tipo: 'masivo', item: item }; break;

        case 'resolucion_masivo':
          if (!s.masivo.vinculado) { error('masivo', 'Aviso de resolución en un caso no vinculado a un masivo.'); break; }
          s.masivo.resuelto = { hora: hora, mensaje: p.mensaje_tablero, hora_tablero: p.hora_tablero };
          s.items.push(item); break;

        case 'hipotesis':
          item.cambios = (p.cambios || []).map(function (c) {
            if (!s.hip[c.id]) { error('datos', 'Hipótesis desconocida: ' + c.id); return c; }
            s.hip[c.id] = { estado: c.estado, evidencia: c.evidencia, hora: hora }; return c;
          });
          if (p.guia && (!p.kb || String(p.mensaje).indexOf(p.kb) < 0)) { error('kb', 'Paso guiado sin cita a un artículo KB-SIM.'); }
          s.items.push(item); break;

        case 'consentimiento':
          var cat = FV.cat(p.accion);
          if (p.aviso || p.aviso_obligatorio) { error('catalogo', 'El paso define su propio aviso: el aviso debe salir del catálogo.'); }
          if (!cat) { error('consentimiento', 'Acción fuera del catálogo: ' + p.accion); break; }
          if (cat.politica === 'prohibida') { error('prohibida', 'Se intentó pedir consentimiento para una acción prohibida (' + p.accion + '). No se muestra la tarjeta.'); break; }
          if (cat.politica === 'aprobacion_n2' && !(s.aprobaciones[p.accion] && s.aprobaciones[p.accion].estado === 'aprobada')) {
            error('consentimiento', 'Tarjeta de «' + p.accion + '» sin aprobación N2 previa.'); break;
          }
          item.cat = cat; item.decision = null; s.tokenVigente = null;
          s.items.push(item); s.pausa = { tipo: 'consentimiento', item: item }; break;

        case 'aprobacion_n2':
          var catA = FV.cat(p.accion);
          if (!catA || catA.politica !== 'aprobacion_n2') { error('consentimiento', 'Solicitud de aprobación N2 para una acción que no la requiere: ' + p.accion); break; }
          item.cat = catA; item.resolucion = null;
          s.aprobaciones[p.accion] = { estado: 'pendiente', solicitada: hora };
          s.items.push(item); s.pausa = { tipo: 'aprobacion', item: item }; break;

        case 'accion':
          var catX = FV.cat(p.accion), tok = s.tokenVigente, motivo = null;
          if (!catX) { motivo = 'acción fuera del catálogo'; }
          else if (catX.politica === 'prohibida') { motivo = 'acción prohibida: nunca se ejecuta'; }
          else if (!tok || tok.accion !== p.accion || tok.consumido) { motivo = 'no hay un consentimiento aceptado justo antes para esta acción'; }
          else if (catX.politica === 'aprobacion_n2' && !(s.aprobaciones[p.accion] && s.aprobaciones[p.accion].estado === 'aprobada')) { motivo = 'falta la aprobación N2'; }
          if (motivo) { item.bloqueada = motivo; error(catX && catX.politica === 'prohibida' ? 'prohibida' : 'consentimiento', 'Acción «' + p.accion + '» bloqueada: ' + motivo + '.'); break; }
          tok.consumido = true; tok.consumidoHora = hora; s.tokenVigente = null;
          item.cat = catX; item.token = tok.token;
          s.acciones.push({ accion: p.accion, nombre: catX.nombre, riesgo: catX.riesgo, politica: catX.politica, token: tok.token, quien: tok.quien, cuando: tok.cuando,
            texto: tok.texto, hash: tok.hash, aprobacion: s.aprobaciones[p.accion] || null, resultado: p.resultado, exito: p.exito !== false, hora: hora, verificacion: null });
          s.items.push(item); break;

        case 'verificacion':
          if (s.acciones.length) { s.acciones[s.acciones.length - 1].verificacion = { prueba: p.prueba, resultado: p.resultado_tecnico, ok: p.ok, usuario: p.respuesta_usuario }; }
          s.items.push(item); break;

        case 'rechazo_politica':
          var catR = FV.cat(p.accion);
          if (!catR || catR.politica !== 'prohibida') { error('datos', 'rechazo_politica sobre una acción que no es prohibida.'); break; }
          if (p.texto) { error('catalogo', 'El rechazo define su propio texto: debe ser la plantilla fija del catálogo.'); }
          item.cat = catR; item.texto = catR.plantilla_rechazo;
          s.rechazos.push({ accion: p.accion, intento: p.intento, hora: hora, texto: catR.plantilla_rechazo });
          s.items.push(item); break;

        case 'bandera':
          var previa = s.banderas.filter(function (b) { return b.categoria === p.categoria && b.mostrada === false; })[0];
          if (previa) { previa.texto = p.texto; previa.detalle = p.detalle; previa.mostrada = true; }
          else { s.banderas.push({ categoria: p.categoria, texto: p.texto, detalle: p.detalle, hora: hora, mostrada: true }); }
          s.items.push(item); break;

        case 'vinculo_masivo':
          if (s.masivo.estado !== 'masivo_confirmado') { error('posible_masivo', 'Vínculo a un masivo que no está confirmado (ni por el tablero ni por N2).'); break; }
          s.masivoVinculado = { incidente: p.incidente, hora: hora, texto: p.texto };
          s.masivo.vinculado = true; s.masivo.suscripcion = !!p.suscripcion; s.masivo.incidente = p.incidente;
          s.items.push(item); break;

        case 'adjunto':
          item.pendientes = (caso.capturas || []).map(function (c) { return c.id; }).filter(function (id) { return s.capturas.map(function (x) { return x.id; }).indexOf(id) < 0; });
          s.items.push(item); s.pausa = { tipo: 'adjunto', item: item }; break;

        case 'escalamiento':
          s.esperaEscalarPorHumano = false;
          var ans = window.ANS[p.ans || 'escalamiento'] || window.ANS.escalamiento;
          s.escalamiento = { motivo: p.motivo, siguiente_paso: p.siguiente_paso || sugerirSiguiente(), ans: ans, hora: hora, generico: !!p.generico };
          item.ans = ans;
          s.items.push(item); s.terminado = true; s.cola = []; s.pausa = null; break;

        case 'cierre':
          s.cierre = { texto: p.texto, hora: hora };
          s.items.push(item); s.terminado = true; s.cola = []; break;

        default:
          error('datos', 'Tipo de paso desconocido: ' + p.tipo);
      }
    }

    var M = {
      s: s,
      siguiente: function () {
        if (s.terminado) { return false; }
        if (s.pausa) { return s.pausa.tipo === 'aprobacion' ? M.revisarAprobacion() : s.pausa.tipo === 'masivo' ? M.revisarMasivo() : false; }
        var p = s.cola.shift();
        if (!p) { s.terminado = true; return false; }
        procesar(p); return true;
      },
      decidir: function (valor) {
        if (!s.pausa || s.pausa.tipo !== 'consentimiento') { return false; }
        var item = s.pausa.item, p = item.paso, cat = item.cat;
        item.decision = valor; s.pausa = null;
        s.decisiones.push({ accion: p.accion, decision: valor, hora: item.hora });
        if (valor === 'si') {
          var texto = textoTarjeta(p, cat);
          var tok = { token: 'TOK-SIM-' + pad(caso.id) + '-' + (++s.nTok), accion: p.accion, parametros: p.parametros || {}, quien: caso.usuario.nombre + ' (clic en «Sí, hazlo»)',
            cuando: item.hora, texto: texto, hash: hash(texto), consumido: false };
          s.tokens.push(tok); s.tokenVigente = tok; item.token = tok.token;
        } else {
          s.cola = p.si_rechaza ? FV.clonar(p.si_rechaza) : [escalamientoGenerico('El usuario rechazó la acción «' + p.accion + '» y el guion no define otra opción.', 'escalamiento',
            'Entendido, no haré esa acción. Como no tengo otra opción segura, te paso con un técnico con todo lo que revisé.')];
        }
        return true;
      },
      adjuntar: function (cid) {
        if (!s.pausa || s.pausa.tipo !== 'adjunto') { return false; }
        var item = s.pausa.item, p = item.paso;
        if (item.pendientes.indexOf(cid) < 0) { return false; }
        s.pausa = null;
        var cap = (caso.capturas || []).filter(function (c) { return c.id === cid; })[0];
        s.capturas.push({ id: cid, titulo: cap ? cap.titulo : cid, hora: aHora(s.horaUlt + 5) });
        procesar({ tipo: 'msg_usuario', captura: cid, texto: 'Adjunto: ' + (cap ? cap.titulo : cid), hora: aHora(s.horaUlt + 5) });
        var resto = item.pendientes.filter(function (x) { return x !== cid; });
        var nueva = FV.clonar((p.ramas && p.ramas[cid]) || []);
        if (p.todas && resto.length) { var otra = FV.clonar(p); otra.hora = null; otra.texto = 'Falta adjuntar: ' + resto.map(function (r) { var c2 = (caso.capturas || []).filter(function (x) { return x.id === r; })[0]; return c2 ? c2.titulo : r; }).join(', '); nueva.push(otra); }
        s.cola = nueva.concat(s.cola);
        return true;
      },
      revisarAprobacion: function () {
        if (!s.pausa || s.pausa.tipo !== 'aprobacion') { return false; }
        var item = s.pausa.item, acc = item.paso.accion, reg = null;
        if (opts.autoAprobar) { reg = { accion: acc, estado: 'aprobada', quien: window.N2_FICTICIO.nombre + ' · ' + window.N2_FICTICIO.id, hora: aHora(s.horaUlt + 60), via: 'recorrido automático' }; }
        else if (s.aprobManual[acc]) { reg = s.aprobManual[acc]; }
        else if (!opts.sinAlmacen) { var g = FV.almacen.get(FV.clave.aprob(caso.id)); if (g && g.accion === acc) { reg = g; } }
        if (!reg || reg.estado === 'pendiente') { return false; }
        item.resolucion = reg; s.aprobaciones[acc] = reg; s.pausa = null; horaDe(null); // la hora real de N2 se muestra, pero no altera la hora simulada
        if (reg.estado !== 'aprobada') {
          s.cola = [escalamientoGenerico(reg.estado === 'tomada' ? 'N2 tomó el caso desde la consola.' : 'N2 rechazó la acción «' + acc + '».', 'escalamiento',
            reg.estado === 'tomada' ? 'Un técnico de N2 tomó tu caso y te contactará directamente.' : 'El técnico de N2 no aprobó esa acción. Tu caso queda con N2, que revisará otra solución contigo.')];
        }
        return true;
      },
      revisarMasivo: function () {
        if (!s.pausa || s.pausa.tipo !== 'masivo') { return false; }
        var item = s.pausa.item, p = item.paso, reg = null;
        if (opts.autoMasivo) { reg = { estado: opts.autoMasivo, mensaje: opts.autoMasivo === 'confirmado' ? p.mensaje_sugerido : '', quien: window.N2_FICTICIO.nombre + ' · ' + window.N2_FICTICIO.id, hora: aHora(s.horaUlt + 590), via: 'recorrido automático' }; }
        else if (s.masivoManual) { reg = s.masivoManual; }
        else if (!opts.sinAlmacen) { reg = FV.almacen.get(FV.clave.masivo(caso.id)); }
        if (!reg || (reg.estado !== 'confirmado' && reg.estado !== 'descartado')) { return false; }
        item.resolucion = reg; s.pausa = null; s.masivo.pendienteN2 = false; s.masivo.decisionN2 = reg; horaDe(null);
        if (reg.estado === 'confirmado') {
          s.masivo.estado = 'masivo_confirmado'; s.masivo.fuente = 'N2 (consola)'; s.masivo.mensaje = reg.mensaje; s.masivo.hora_mensaje = reg.hora; s.masivo.incidente = p.incidente_si_confirma;
        } else { s.masivo.estado = 'descartado'; s.masivo.fuente = 'N2 (consola): descartado'; }
        s.cola = FV.clonar((p.ramas && p.ramas[reg.estado]) || []);
        return true;
      },
      decidirMasivoManual: function (estado) {
        if (!s.pausa || s.pausa.tipo !== 'masivo') { return false; }
        var p = s.pausa.item.paso;
        s.masivoManual = { estado: estado, mensaje: estado === 'confirmado' ? p.mensaje_sugerido : '', quien: window.N2_FICTICIO.nombre + ' · ' + window.N2_FICTICIO.id, hora: aHora(s.horaUlt + 590), via: 'botón manual del prototipo' };
        return M.revisarMasivo();
      },
      aprobarManual: function () {
        if (!s.pausa || s.pausa.tipo !== 'aprobacion') { return false; }
        var acc = s.pausa.item.paso.accion;
        s.aprobManual[acc] = { accion: acc, estado: 'aprobada', quien: window.N2_FICTICIO.nombre + ' · ' + window.N2_FICTICIO.id, hora: aHora(s.horaUlt + 60), via: 'botón manual del prototipo' };
        return M.revisarAprobacion();
      },
      humano: function () {
        if (s.terminado) { return false; }
        s.pausa = null; s.cola = []; s.esperaEscalarPorHumano = false;
        procesar({ tipo: 'msg_usuario', texto: 'Quiero hablar con una persona.', pide_humano: true, boton: true });
        procesar(escalamientoGenerico('El usuario pidió hablar con una persona (botón «Hablar con una persona»).', 'humano'));
        return true;
      },
      aplicar: function (ev) {
        if (ev === 'sig') { return M.siguiente(); }
        if (ev === 'si' || ev === 'no') { return M.decidir(ev); }
        if (ev === 'humano') { return M.humano(); }
        if (ev === 'aprob') { return M.revisarAprobacion(); }
        if (ev === 'aprob-manual') { return M.aprobarManual(); }
        if (ev === 'masivo') { return M.revisarMasivo(); }
        if (ev === 'masivo-manual-confirmado') { return M.decidirMasivoManual('confirmado'); }
        if (ev === 'masivo-manual-descartado') { return M.decidirMasivoManual('descartado'); }
        if (ev.indexOf('cap:') === 0) { return M.adjuntar(ev.slice(4)); }
        return false;
      }
    };
    return M;
  };

  FV.reproducir = function (caso, log, opts) {
    var m = FV.crearMotor(caso, opts);
    (log || []).forEach(function (e) { m.aplicar(e); });
    return m;
  };

  /* Recorre el guion completo por el camino feliz (acepta, aprueba, adjunta).
     `plan` permite forzar decisiones: { noEnConsentimiento: k, humanoEnPaso: k } */
  FV.recorridoCompleto = function (caso, plan) {
    plan = plan || {};
    var m = FV.crearMotor(caso, { autoAprobar: true, sinAlmacen: true, autoMasivo: plan.masivo || 'confirmado' }), s = m.s, nCons = 0, nPasos = 0;
    for (var i = 0; i < 400 && !s.terminado; i++) {
      if (plan.humanoEnPaso != null && nPasos === plan.humanoEnPaso) { m.humano(); break; }
      if (s.pausa && s.pausa.tipo === 'consentimiento') { m.decidir(nCons === plan.noEnConsentimiento ? 'no' : 'si'); nCons++; continue; }
      if (s.pausa && s.pausa.tipo === 'adjunto') { m.adjuntar(s.pausa.item.pendientes[0]); continue; }
      if (s.pausa && s.pausa.tipo === 'aprobacion') { m.revisarAprobacion(); continue; }
      if (s.pausa && s.pausa.tipo === 'masivo') { m.revisarMasivo(); continue; }
      if (!m.siguiente() && !s.pausa) { break; }
      nPasos++;
    }
    m.nConsentimientos = nCons; m.nPasos = nPasos;
    return m;
  };

  /* --------------------------------------------- ficha de escalamiento */
  FV.ficha = function (s) {
    var c = s.caso;
    return {
      sintoma_usuario: s.sintomaUsuario,
      sintoma_normalizado: s.sintomaUsuario ? c.sintoma.normalizado + ' (app: ' + c.sintoma.app + ' · tipo: ' + c.sintoma.tipo + ')' : null,
      contexto: s.telemetriaConsultada ? c.telemetria : null,
      equipo: c.usuario.equipo, usuario: c.usuario,
      masivo: s.masivo,
      hipotesis: (c.hipotesis || []).map(function (h) { return { id: h.id, descripcion: h.descripcion, kb: h.kb, prior: h.prior, estado: s.hip[h.id].estado, evidencia: s.hip[h.id].evidencia }; }),
      fallos: s.revisiones.filter(function (r) { return r.marca === 'fallo'; }),
      acciones: s.acciones, decisiones: s.decisiones,
      banderas: s.banderas, rechazos: s.rechazos,
      preguntas: s.preguntas, senales: s.senales,
      motivo: s.escalamiento ? s.escalamiento.motivo : null,
      siguiente_paso: s.escalamiento ? s.escalamiento.siguiente_paso : null,
      ans: s.escalamiento ? s.escalamiento.ans : null
    };
  };

  FV.ESTADO_MASIVO_TXT = { no_evaluado: 'No evaluado', sin_masivo: 'Evaluado: no es masivo', posible_masivo: 'Posible masivo (clúster)', masivo_confirmado: 'Masivo confirmado', descartado: 'Posible masivo descartado por N2' };
  FV.textoMasivo = function (m) {
    var t = FV.ESTADO_MASIVO_TXT[m.estado] || m.estado;
    if (m.categoria) { t += ' · categoría ' + m.categoria + ' (confianza ' + m.confianza + ')'; }
    if (m.usuarios) { t += ' · ' + m.usuarios + ' usuarios similares en ' + m.ventana + ', similitud media ' + m.similitud_media; }
    if (m.pendienteN2) { t += ' · propuesta a N2 pendiente'; }
    if (m.fuente) { t += ' · fuente: ' + m.fuente; }
    if (m.incidente) { t += ' · incidente ' + m.incidente; }
    if (m.regla && m.estado === 'sin_masivo') { t += ' (' + m.regla + ')'; }
    return t;
  };

  FV.htmlFicha = function (s) {
    var f = FV.ficha(s), h = '';
    h += '<div class="ficha">';
    h += '<p class="ficha-motivo"><b>Motivo del escalamiento:</b> ' + FV.esc(f.motivo || '—') + '</p>';
    h += '<h4>1. Síntoma</h4><p><b>En palabras del usuario:</b> ' + (f.sintoma_usuario ? '«' + FV.esc(f.sintoma_usuario) + '»' : '<i class="vacio">Aún no lo describió.</i>') + '<br><b>Normalizado:</b> ' + (f.sintoma_normalizado ? FV.esc(f.sintoma_normalizado) : '<i class="vacio">Sin normalizar todavía.</i>') + '</p>';
    h += '<h4>2. Contexto del equipo</h4>';
    if (f.contexto) {
      h += '<table class="tabla compacta"><tbody><tr><th>Usuario / equipo</th><td>' + FV.esc(f.usuario.nombre + ' · ' + f.usuario.area + ' · nivel ' + f.usuario.nivel + ' · ' + f.equipo) + '</td></tr>';
      Object.keys(f.contexto).forEach(function (k) { h += '<tr><th>' + FV.esc(k) + '</th><td>' + FV.esc(f.contexto[k]) + '</td></tr>'; });
      h += '<tr><th>Masivo</th><td>' + FV.esc(FV.textoMasivo(f.masivo)) + '</td></tr></tbody></table>';
    } else { h += '<p class="vacio">Telemetría aún no consultada en el momento del escalamiento (equipo ' + FV.esc(f.equipo) + ').</p>'; }
    if (f.senales.length) { h += '<p><b>Señales del usuario:</b> ' + f.senales.map(function (x) { return FV.esc(x.senal); }).join(', ') + ' · <b>Preguntas hechas:</b> ' + f.preguntas.length + '</p>'; }
    h += '<h4>3. Hipótesis probadas y descartadas</h4>';
    if (f.hipotesis.length) {
      h += '<table class="tabla compacta"><thead><tr><th>Id</th><th>Hipótesis</th><th>KB</th><th>Estado</th><th>Evidencia</th></tr></thead><tbody>';
      f.hipotesis.forEach(function (x) { h += '<tr><td>' + x.id + '</td><td>' + FV.esc(x.descripcion) + '</td><td>' + FV.esc(x.kb) + '</td><td>' + FV.badgeEstadoHip(x.estado) + '</td><td>' + FV.esc(x.evidencia || 'Sin probar') + '</td></tr>'; });
      h += '</tbody></table>';
    } else { h += '<p class="vacio">Sin hipótesis en este escenario.</p>'; }
    if (f.fallos.length) { h += '<p><b>Consultas fallidas:</b> ' + f.fallos.map(function (x) { return '⚠ ' + FV.esc(x.herramienta + ': ' + x.resultado); }).join('; ') + '</p>'; }
    h += '<h4>4. Acciones hechas</h4>';
    if (f.acciones.length) {
      h += '<ul>' + f.acciones.map(function (a) { return '<li><b>' + FV.esc(a.nombre) + '</b> ' + FV.badgeRiesgo(a.riesgo) + ' · consentimiento ' + FV.esc(a.token) + ' (' + FV.esc(a.cuando) + ')' + (a.aprobacion ? ' · aprobación N2: ' + FV.esc(a.aprobacion.quien) : '') + ' → ' + FV.esc(a.resultado) + (a.verificacion ? ' · verificación: ' + (a.verificacion.ok ? '✓ ' : '✗ ') + FV.esc(a.verificacion.resultado) : '') + '</li>'; }).join('') + '</ul>';
    } else { h += '<p class="vacio">Ninguna acción ejecutada.</p>'; }
    var rech = f.decisiones.filter(function (d) { return d.decision === 'no'; });
    if (rech.length) { h += '<p><b>Acciones rechazadas por el usuario:</b> ' + rech.map(function (d) { return FV.esc(d.accion); }).join(', ') + '</p>'; }
    h += '<h4>5. Banderas de seguridad</h4>';
    if (f.banderas.length || f.rechazos.length) {
      h += '<ul>' + f.banderas.map(function (b) { return '<li>⚑ <b>' + FV.esc(b.categoria) + ':</b> ' + FV.esc(b.texto) + '</li>'; }).join('') +
        (f.rechazos.length ? '<li>Peticiones de acción prohibida: ' + f.rechazos.length + ' (' + FV.esc(f.rechazos[0].accion) + '), todas rechazadas con la misma plantilla.</li>' : '') + '</ul>';
    } else { h += '<p class="vacio">Sin banderas.</p>'; }
    h += '<h4>6. Siguiente paso sugerido y ANS</h4><p>' + FV.esc(f.siguiente_paso || '—') + '<br><b>ANS:</b> ' + (f.ans ? FV.esc(f.ans.prioridad + ' · ' + f.ans.plazo) : '—') + '</p>';
    h += '</div>';
    return h;
  };

  /* ---------------------------------------------- autoverificación */
  FV.REGLAS = [
    { id: 'consentimiento', txt: 'Ninguna acción sin consentimiento aceptado justo antes (y aprobación N2 cuando la política lo exige)' },
    { id: 'prohibida', txt: 'Ninguna acción prohibida se ejecuta ni aparece como tarjeta' },
    { id: 'masivo', txt: 'En un masivo no hay pasos individuales' },
    { id: 'posible_masivo', txt: 'Un posible masivo no confirmado no muestra pasos individuales ni acciones, solo pruebas de lectura (y no se vincula sin confirmación)' },
    { id: 'slots', txt: 'No se pregunta un slot de origen telemetría' },
    { id: 'kb', txt: 'Todo paso guiado cita un KB-SIM' },
    { id: 'humano', txt: '«Hablar con una persona» escala de inmediato (probado en cada paso)' },
    { id: 'ficha', txt: 'Toda escalación lleva la ficha completa (6 secciones)' },
    { id: 'inyeccion', txt: 'Texto con instrucciones en capturas/logs genera bandera' },
    { id: 'catalogo', txt: 'Aviso y rechazo salen del catálogo (fuente única)' },
    { id: 'resultado', txt: 'El resultado del guion coincide con el esperado' },
    { id: 'datos', txt: 'Datos del guion bien formados' }
  ];

  FV.validar = function (caso) {
    var errores = [], variantes = 0;
    function recoger(m, etiqueta) {
      variantes++;
      m.s.errores.forEach(function (e) { errores.push({ regla: e.regla, texto: (etiqueta ? '[' + etiqueta + '] ' : '') + e.texto }); });
      if (m.s.escalamiento) {
        var f = FV.ficha(m.s);
        if (!f.siguiente_paso || !f.ans || !f.motivo) { errores.push({ regla: 'ficha', texto: (etiqueta || '') + ' Escalamiento sin siguiente paso, ANS o motivo.' }); }
      }
      var banderasIny = m.s.banderas.filter(function (b) { return b.categoria === 'inyeccion'; });
      if (m.s.inyecciones > banderasIny.length) { errores.push({ regla: 'inyeccion', texto: (etiqueta || '') + ' Se detectaron instrucciones sin bandera en el estado.' }); }
      if (!etiqueta && banderasIny.some(function (b) { return !b.mostrada; })) { errores.push({ regla: 'inyeccion', texto: 'Bandera de inyección sin aviso visible al usuario.' }); }
    }
    var base = FV.recorridoCompleto(caso);
    recoger(base, '');
    var s = base.s;
    var obtenido = caso.modulo === 'A' ? 'pendiente_revision' : s.escalamiento ? 'escalado' : s.masivoVinculado ? 'vinculado_masivo' : s.cierre ? 'cerrado' : 'sin terminar';
    if (obtenido !== caso.resultado_esperado || (caso.resultado && caso.resultado.tipo !== caso.resultado_esperado)) {
      errores.push({ regla: 'resultado', texto: 'Esperado «' + caso.resultado_esperado + '», obtenido «' + obtenido + '».' });
    }
    var sHip = s;
    if (caso.resultado_si_descarta) {
      var mDesc = FV.recorridoCompleto(caso, { masivo: 'descartado' });
      recoger(mDesc, 'N2 descarta el masivo');
      var obtD = mDesc.s.escalamiento ? 'escalado' : mDesc.s.masivoVinculado ? 'vinculado_masivo' : mDesc.s.cierre ? 'cerrado' : 'sin terminar';
      if (obtD !== caso.resultado_si_descarta) { errores.push({ regla: 'resultado', texto: 'Si N2 descarta: esperado «' + caso.resultado_si_descarta + '», obtenido «' + obtD + '».' }); }
      if (caso.hipotesis_segun_rama === 'descartado') { sHip = mDesc.s; }
    }
    (caso.hipotesis || []).forEach(function (h) {
      var s = sHip;
      if (s.hip[h.id].estado !== h.estado) { errores.push({ regla: 'datos', texto: h.id + ': estado final «' + s.hip[h.id].estado + '» ≠ esperado «' + h.estado + '».' }); }
    });
    // Variantes: decir "No" en cada consentimiento.
    for (var k = 0; k < base.nConsentimientos; k++) {
      var mNo = FV.recorridoCompleto(caso, { noEnConsentimiento: k });
      recoger(mNo, 'No en consentimiento ' + (k + 1));
      if (!mNo.s.escalamiento && !mNo.s.cierre) { errores.push({ regla: 'consentimiento', texto: 'Tras decir No en el consentimiento ' + (k + 1) + ' el guion no termina.' }); }
    }
    // Variantes: pulsar "Hablar con una persona" antes de cada paso.
    if (!caso.sin_conversacion) {
      for (var j = 0; j <= base.nPasos; j++) {
        var mH = FV.recorridoCompleto(caso, { humanoEnPaso: j });
        if (mH.s.terminado && !mH.s.escalamiento) { continue; } // ya había terminado antes de ese paso
        recoger(mH, 'Persona en paso ' + j);
        if (!mH.s.escalamiento) { errores.push({ regla: 'humano', texto: 'Pulsar «Hablar con una persona» en el paso ' + j + ' no escaló.' }); }
      }
    }
    return { errores: errores, variantes: variantes, obtenido: obtenido };
  };

  /* ===================================================================
     PIEZAS COMUNES DE PÁGINA
     =================================================================== */
  FV.nav = function (actual, id) {
    var q = id ? '?escenario=' + id : '';
    var links = [
      ['index', 'index.html', 'Inicio'],
      ['usuario', 'usuario.html' + (q || '?escenario=1'), 'Vista usuario'],
      ['n2', 'n2.html' + q, 'Consola N2'],
      ['caso', 'caso.html' + (q || '?escenario=1'), 'Auditoría del caso'],
      ['metricas', 'metricas.html', 'Métricas']
    ];
    var h = '<nav class="nav"><span class="marca">Prototipo de validación · Caso 5 <small>(datos sintéticos)</small></span>';
    links.forEach(function (l) { h += '<a href="' + l[1] + '"' + (l[0] === actual ? ' class="activo"' : '') + '>' + l[2] + '</a>'; });
    h += '</nav>';
    return h;
  };

  FV.selectorEscenario = function (pagina, id) {
    var h = '<label class="selector">Escenario: <select id="sel-escenario">';
    window.CASOS.forEach(function (c) { h += '<option value="' + c.id + '"' + (String(c.id) === String(id) ? ' selected' : '') + '>' + c.id + ' · ' + FV.esc(c.titulo) + '</option>'; });
    h += '</select></label>';
    return h;
  };
  function enlazarSelector(pagina) {
    var sel = el('sel-escenario');
    if (sel) { sel.addEventListener('change', function () { location.href = pagina + '.html?escenario=' + sel.value; }); }
  }

  FV.htmlGrafo = function (s, caso) {
    var nodos = window.GRAFO.filter(function (n) {
      if (caso.modulo === 'A') { return n.id === 'Lote' || n.id === 'Revision'; }
      return n.id !== 'Lote' && n.id !== 'Revision';
    });
    return '<div class="grafo" aria-label="Estado del grafo">' + nodos.map(function (n) {
      var cls = n.id === s.grafo ? 'actual' : (s.visitados.indexOf(n.id) >= 0 ? 'visitado' : '');
      return '<span class="nodo ' + cls + '">' + FV.esc(n.nombre) + '</span>';
    }).join('<span class="flecha">→</span>') + '</div>';
  };

  FV.htmlCaptura = function (cap) {
    return '<div class="captura-sim"><div class="captura-barra">' + FV.esc(cap.ventana) + '<span>✕</span></div><pre>' + FV.esc(cap.texto) + '</pre><div class="captura-botones">' +
      (cap.botones || []).map(function (b) { return '<span>' + FV.esc(b) + '</span>'; }).join('') + '</div><div class="captura-pie">' + FV.esc(cap.titulo) + ' · imagen dibujada con HTML/CSS</div></div>';
  };

  /* ===================================================================
     usuario.html
     =================================================================== */
  function renderItemChat(it, s, M) {
    var p = it.paso || {}, caso = s.caso, h = '';
    var hora = '<span class="hora">' + FV.esc(it.hora) + '</span>';
    function burbujaSistema(texto, extra) { return '<div class="burbuja sistema">' + hora + '<div class="texto">' + FV.esc(texto) + '</div>' + (extra || '') + '</div>'; }
    function tagKb(kb) { return kb ? '<span class="tag kb">Fuente: ' + FV.esc(kb) + '</span>' : ''; }
    switch (it.tipo) {
      case 'msg_usuario':
        if (p.captura) {
          var cap = (caso.capturas || []).filter(function (c) { return c.id === p.captura; })[0];
          return '<div class="burbuja usuario">' + hora + '<div class="texto">' + FV.esc(p.texto) + '</div>' + (cap ? FV.htmlCaptura(cap) : '') + '</div>';
        }
        return '<div class="burbuja usuario">' + hora + '<div class="texto">' + FV.esc(p.texto) + '</div>' +
          (p.senal ? '<span class="tag aviso">señal detectada: ' + FV.esc(p.senal) + '</span>' : '') +
          (p.pide_humano ? '<span class="tag aviso">interrupción global: pide una persona' + (p.boton ? ' (botón)' : '') + '</span>' : '') + '</div>';
      case 'msg_sistema':
        if (it.cita) {
          return burbujaSistema(p.texto, '<blockquote class="cita-oficial">' + (it.cita.fuente === 'tablero' ? 'Tablero oficial · publicado a las ' : 'Aviso publicado por N2 · ') + FV.esc(it.cita.hora) +
            '<br>«' + FV.esc(it.cita.mensaje) + '»</blockquote><span class="tag">texto citado tal cual (fuente: ' + FV.esc(it.cita.fuente) + ')</span>');
        }
        return burbujaSistema(p.texto, tagKb(p.kb) +
          (p.pregunta ? '<span class="tag">pregunta · slot «' + FV.esc(p.pregunta) + '» (origen usuario)</span>' : '') +
          (p.nivel_adaptado ? '<span class="tag aviso">lenguaje ' + FV.esc(p.nivel_adaptado) + '</span>' : ''));
      case 'revisando':
        return '<div class="nota-sistema">' + hora + ' Revisando: ' + (p.lineas || []).map(function (l) { return FV.MARCAS[l.marca] + ' ' + FV.esc(l.herramienta); }).join(' · ') + ' <i>(detalle en el panel)</i></div>';
      case 'hipotesis':
        h = '<div class="burbuja sistema">' + hora + (p.mensaje ? '<div class="texto">' + FV.esc(p.mensaje) + '</div>' : '') + tagKb(p.kb) +
          '<div class="mini-hip">' + (it.cambios || []).map(function (c) { return '<div>' + FV.esc(c.id) + ' ' + FV.badgeEstadoHip(c.estado) + ' <small>' + FV.esc(c.evidencia) + '</small></div>'; }).join('') + '</div></div>';
        return h;
      case 'consentimiento':
        var cat = it.cat;
        if (p.mensaje) { h += burbujaSistema(p.mensaje); }
        h += '<div class="tarjeta consentimiento riesgo-borde-' + cat.riesgo + '">';
        h += '<div class="tarjeta-titulo">Necesito tu permiso · ' + FV.esc(cat.nombre) + ' ' + FV.badgeRiesgo(cat.riesgo) + ' ' + FV.badgePolitica(cat.politica) + '</div>';
        h += '<dl><dt>Qué haré</dt><dd>' + FV.esc(p.detalle || cat.descripcion) + '</dd>';
        h += '<dt>Qué efecto tiene</dt><dd>' + FV.esc(cat.aviso_obligatorio) + ' <small class="fuente">(aviso tomado del catálogo: ' + FV.esc(cat.id) + ')</small></dd>';
        h += '<dt>Cómo se revierte</dt><dd>' + FV.esc(cat.reversion) + '</dd>';
        if (p.parametros) { h += '<dt>Parámetros</dt><dd><code>' + FV.esc(JSON.stringify(p.parametros)) + '</code></dd>'; }
        h += '</dl>';
        if (it.decision === null && s.pausa && s.pausa.item === it) {
          h += '<div class="botones"><button class="btn primario" data-ev="si">Sí, hazlo</button><button class="btn" data-ev="no">No, prefiero otra opción</button></div>';
          h += '<p class="espera">El guion está detenido hasta que elijas.</p>';
        } else if (it.decision === 'si') {
          h += '<p class="decision ok">✔ Aceptaste (' + FV.esc(it.hora) + ') · token de un solo uso <code>' + FV.esc(it.token) + '</code></p>';
        } else if (it.decision === 'no') {
          h += '<p class="decision no">✖ Elegiste «No, prefiero otra opción»' + (p.si_rechaza ? ' → rama alternativa del guion' : ' → no hay rama: se escala') + '</p>';
        }
        return h + '</div>';
      case 'aprobacion_n2':
        h += burbujaSistema(p.mensaje);
        h += '<div class="tarjeta aprobacion">';
        h += '<div class="tarjeta-titulo">Aprobación N2 · ' + FV.esc(it.cat.nombre) + ' ' + FV.badgeRiesgo(it.cat.riesgo) + ' ' + FV.badgePolitica(it.cat.politica) + '</div>';
        if (!it.resolucion) {
          h += '<p>⏳ <b>En espera.</b> ' + FV.esc(window.ANS.aprobacion.texto) + '</p>';
          h += '<p>Para continuar: abre la <a href="n2.html?escenario=' + caso.id + '#aprobaciones">consola N2 (en esta misma pestaña)</a>, aprueba y vuelve aquí; al recargar, el guion continúa.</p>';
          h += '<p class="espera">El guion está detenido hasta que N2 decida.</p>';
        } else {
          var r = it.resolucion;
          h += '<p class="decision ' + (r.estado === 'aprobada' ? 'ok' : 'no') + '">' + (r.estado === 'aprobada' ? '✔ N2 aprobó' : r.estado === 'tomada' ? '↪ N2 tomó el caso' : '✖ N2 rechazó') + ' · ' + FV.esc(r.quien) + ' · ' + FV.esc(r.hora) + (r.via ? ' · <small>' + FV.esc(r.via) + '</small>' : '') + '</p>';
          if (r.estado === 'aprobada') { h += '<p><small>Ahora falta tu consentimiento: la aprobación de N2 no reemplaza tu «Sí».</small></p>'; }
        }
        return h + '</div>';
      case 'accion':
        if (it.bloqueada) { return '<div class="tarjeta error">⛔ Acción «' + FV.esc(p.accion) + '» NO ejecutada: ' + FV.esc(it.bloqueada) + '</div>'; }
        return '<div class="tarjeta accion">' + hora + '<b>⚙ Ejecutado por el Ejecutor (sin LLM):</b> ' + FV.esc(it.cat.nombre) + ' → ' + FV.esc(p.resultado) + '<br><small>Token consumido: <code>' + FV.esc(it.token) + '</code></small></div>';
      case 'verificacion':
        h += '<div class="tarjeta verificacion ' + (p.ok ? 'ok' : 'falla') + '">' + hora + '<b>Verificación técnica:</b> ' + FV.esc(p.prueba) + ' → ' + (p.ok ? '✓ ' : '✗ ') + FV.esc(p.resultado_tecnico) + '</div>';
        h += burbujaSistema(p.pregunta);
        if (p.respuesta_usuario) { h += '<div class="burbuja usuario">' + hora + '<div class="texto">' + FV.esc(p.respuesta_usuario) + '</div></div>'; }
        return h;
      case 'rechazo_politica':
        return burbujaSistema(it.texto + (p.nota ? ' ' + p.nota : ''), '<span class="tag prohibida">rechazo por política · intento ' + FV.esc(p.intento) + ' · acción prohibida «' + FV.esc(p.accion) + '» (plantilla fija del catálogo)</span>');
      case 'bandera':
        return '<div class="bandera">' + hora + '⚑ <b>Bandera de seguridad (' + FV.esc(p.categoria) + '):</b> ' + FV.esc(p.texto) + (p.detalle ? '<br><small>' + FV.esc(p.detalle) + '</small>' : '') + '</div>';
      case 'vinculo_masivo':
        return '<div class="tarjeta masivo">' + hora + '<b>🔗 Vinculado a incidente masivo ' + FV.esc(p.incidente) + '.</b> ' + FV.esc(p.texto) + (p.suscripcion ? '<br><span class="tag">suscrito al aviso de resolución</span>' : '') + '</div>';
      case 'propuesta_masivo':
        var pr = p.propuesta;
        return burbujaSistema(p.texto, '<span class="tag aviso">posible masivo · propuesta ' + FV.esc(pr.id) + ' enviada a N2 · solo pruebas de lectura</span>');
      case 'espera_masivo':
        h = '<div class="tarjeta aprobacion"><div class="tarjeta-titulo">Posible masivo en revisión por N2 · ' + FV.esc(p.propuesta) + '</div>';
        if (!it.resolucion) {
          h += '<p>⏳ <b>En espera.</b> Estamos revisando si otros compañeros tienen el mismo problema.</p>';
          h += '<p>Para continuar: abre la <a href="n2.html?escenario=' + caso.id + '#posibles-masivos">consola N2 (en esta misma pestaña)</a>, confirma o descarta el masivo y vuelve aquí; al recargar, el guion continúa.</p>';
          h += '<p class="espera">El guion está detenido hasta que N2 decida. Mientras tanto no hay pasos individuales ni acciones.</p>';
        } else {
          var rm = it.resolucion;
          h += '<p class="decision ' + (rm.estado === 'confirmado' ? 'ok' : 'no') + '">' + (rm.estado === 'confirmado' ? '✔ N2 confirmó el masivo' : '✖ N2 descartó el masivo: sigue el diagnóstico individual') + ' · ' + FV.esc(rm.quien) + ' · ' + FV.esc(rm.hora) + (rm.via ? ' · <small>' + FV.esc(rm.via) + '</small>' : '') + '</p>';
        }
        return h + '</div>';
      case 'resolucion_masivo':
        h += '<div class="tarjeta masivo">' + hora + '<b>✅ Incidente ' + FV.esc(p.incidente) + ' resuelto.</b><blockquote class="cita-oficial">Tablero oficial · publicado a las ' + FV.esc(p.hora_tablero) + '<br>«' + FV.esc(p.mensaje_tablero) + '»</blockquote></div>';
        h += burbujaSistema(p.pregunta);
        return h;
      case 'adjunto':
        return '<div class="nota-sistema">' + hora + ' 📎 ' + FV.esc(p.texto || 'Esperando capturas…') + (s.pausa && s.pausa.item === it ? ' <b>→ usa «Adjuntar captura» en el panel.</b>' : '') + '</div>';
      case 'escalamiento':
        h += burbujaSistema(p.texto + ' ' + it.ans.texto, '<span class="tag">ANS: ' + FV.esc(it.ans.prioridad + ' · ' + it.ans.plazo) + '</span>' + (p.generico ? '<span class="tag aviso">escalamiento genérico (construido desde el estado)</span>' : ''));
        h += '<details class="tarjeta escalamiento" open><summary>Ficha enviada a N2 (lo recolectado hasta este punto)</summary>' + FV.htmlFicha(s) + '</details>';
        return h;
      case 'cierre':
        h += burbujaSistema(p.texto);
        var r2 = caso.registro_itsm;
        if (r2) { h += '<div class="tarjeta cierre"><b>Registro ITSM (simulado)</b><br>Síntoma: ' + FV.esc(r2.sintoma) + '<br>Causa: ' + FV.esc(r2.causa) + '<br>Solución: ' + FV.esc(r2.solucion) + '<br>Acciones: ' + FV.esc(r2.acciones) + '<br>Duración: ' + FV.esc(r2.duracion) + '</div>'; }
        return h;
      case 'error':
        return '<div class="tarjeta error">⛔ INVARIANTE ROTA (' + FV.esc(it.regla) + '): ' + FV.esc(it.texto) + '</div>';
    }
    return '';
  }

  FV.paginaUsuario = function () {
    var id = String(FV.param('escenario') || 1), caso = FV.caso(id);
    el('nav').innerHTML = FV.nav('usuario', id);
    if (!caso) { el('principal').innerHTML = '<p>Escenario no encontrado.</p>'; return; }
    el('cabecera').innerHTML = '<h1>Vista del colaborador · ' + caso.id + '. ' + FV.esc(caso.titulo) + '</h1>' + FV.selectorEscenario('usuario', id) +
      '<p class="sub">' + FV.esc(caso.usuario.nombre) + ' · ' + FV.esc(caso.usuario.area) + ' · nivel técnico ' + FV.esc(caso.usuario.nivel) + ' · ' + FV.esc(caso.usuario.equipo) + ' · ' + FV.badgeResultado(caso.resultado_esperado) + ' esperado</p>';
    enlazarSelector('usuario');

    var log = FV.almacen.get(FV.clave.log(id)) || [];
    var M = FV.reproducir(caso, log);
    // Si estaba esperando a N2 y ya hay decisión guardada, continúa al recargar.
    if (M.s.pausa && M.s.pausa.tipo === 'aprobacion' && M.revisarAprobacion()) { log.push('aprob'); FV.almacen.set(FV.clave.log(id), log); }
    if (M.s.pausa && M.s.pausa.tipo === 'masivo' && M.revisarMasivo()) { log.push('masivo'); FV.almacen.set(FV.clave.log(id), log); }

    function registrar(ev) {
      if (M.aplicar(ev)) { log.push(ev); FV.almacen.set(FV.clave.log(id), log); }
      pintar();
    }

    function pintar() {
      var s = M.s;
      el('grafo').innerHTML = FV.htmlGrafo(s, caso);
      el('chat').innerHTML = s.items.map(function (it) { return renderItemChat(it, s, M); }).join('') ||
        '<p class="vacio">Pulsa «Siguiente paso ▶» para empezar el guion.</p>';
      el('panel-revisando').innerHTML = s.revisiones.length ? s.revisiones.map(function (r) {
        return '<li class="rev-' + r.marca + '" title="' + FV.esc(FV.MARCA_TXT[r.marca]) + '"><span class="marca">' + FV.MARCAS[r.marca] + '</span><b>' + FV.esc(r.herramienta) + '</b> <span class="hora">' + FV.esc(r.hora) + '</span><br>' + FV.esc(r.resultado) +
          (r.texto_original ? '<br><small>Texto original (no confiable, solo lo ve el extractor): <code>' + FV.esc(r.texto_original) + '</code></small>' : '') + '</li>';
      }).join('') : '<li class="vacio">Todavía no he revisado nada.</li>';

      // Capturas (Módulo B)
      if (caso.capturas) {
        var esperando = s.pausa && s.pausa.tipo === 'adjunto';
        el('panel-capturas').innerHTML = '<h2>Adjuntar captura <small>(simulada)</small></h2>' + caso.capturas.map(function (c) {
          var hecha = s.capturas.some(function (x) { return x.id === c.id; });
          return '<div class="captura-opcion">' + FV.htmlCaptura(c) + '<button class="btn" data-ev="cap:' + c.id + '"' + (esperando && !hecha ? '' : ' disabled') + '>' + (hecha ? 'Adjuntada ✓' : 'Adjuntar esta captura') + '</button></div>';
        }).join('') + (esperando ? '' : '<p class="vacio">El control se activa cuando el guion pide las capturas.</p>');
      }

      // Panel de prototipo
      var proto = '<h2>Controles del prototipo</h2>';
      proto += '<p><small>Almacenamiento de sesión: ' + (FV.almacen.ok ? 'disponible (el avance se conserva al recargar)' : '<b>NO disponible</b>: el avance vive solo en esta página') + '</small></p>';
      if (s.pausa && s.pausa.tipo === 'aprobacion') {
        proto += '<p><small>Si la aprobación no llega (almacenamiento no disponible o abriste N2 en otra pestaña), usa:</small></p><button class="btn" data-ev="aprob-manual">Simular aprobación N2</button>';
      }
      if (s.pausa && s.pausa.tipo === 'masivo') {
        proto += '<p><small>Si la decisión de N2 sobre el posible masivo no llega, usa:</small></p><div class="botones"><button class="btn" data-ev="masivo-manual-confirmado">Simular: N2 confirma</button><button class="btn" data-ev="masivo-manual-descartado">Simular: N2 descarta</button></div>';
      }
      proto += '<p><small><b>Masivo:</b> ' + FV.esc(FV.textoMasivo(s.masivo)) + '</small></p>';
      proto += '<h3>Este escenario debe demostrar</h3><ul>' + caso.invariantes.map(function (t) { return '<li>' + FV.esc(t) + '</li>'; }).join('') + '</ul>';
      proto += '<p><a href="caso.html?escenario=' + id + '&modo=sesion">Ver el estado del caso de esta sesión →</a></p>';
      el('panel-proto').innerHTML = proto;

      // Botones
      var btn = el('btn-sig'), info = el('estado-guion'), hum = el('btn-humano');
      btn.disabled = s.terminado || (s.pausa && s.pausa.tipo !== 'aprobacion' && s.pausa.tipo !== 'masivo');
      hum.disabled = s.terminado || !!caso.sin_conversacion;
      var msg;
      if (s.terminado) { msg = 'Guion terminado · resultado: ' + (s.escalamiento ? 'escalado' : s.masivoVinculado ? 'vinculado a masivo' : caso.sin_conversacion ? 'pendiente de revisión' : 'cerrado'); }
      else if (s.pausa && s.pausa.tipo === 'consentimiento') { msg = 'Detenido: elige una opción en la tarjeta de consentimiento.'; }
      else if (s.pausa && s.pausa.tipo === 'aprobacion') { msg = 'Detenido: esperando la decisión de N2 («Siguiente» vuelve a comprobar).'; }
      else if (s.pausa && s.pausa.tipo === 'masivo') { msg = 'Detenido: N2 debe confirmar o descartar el posible masivo («Siguiente» vuelve a comprobar).'; }
      else if (s.pausa && s.pausa.tipo === 'adjunto') { msg = 'Detenido: adjunta una captura en el panel lateral.'; }
      else { msg = 'Pasos restantes en el guion: ' + s.cola.length; }
      info.textContent = msg + (s.errores.length ? ' · ⛔ ' + s.errores.length + ' invariante(s) rota(s)' : '');
      var chat = el('chat'); chat.scrollTop = chat.scrollHeight;
    }

    document.body.addEventListener('click', function (e) {
      var b = e.target.closest('[data-ev]');
      if (b && !b.disabled) { registrar(b.getAttribute('data-ev')); }
    });
    el('btn-sig').addEventListener('click', function () { registrar(M.s.pausa && M.s.pausa.tipo === 'aprobacion' ? 'aprob' : M.s.pausa && M.s.pausa.tipo === 'masivo' ? 'masivo' : 'sig'); });
    el('btn-humano').addEventListener('click', function () { registrar('humano'); });
    el('btn-reiniciar').addEventListener('click', function () {
      FV.almacen.del(FV.clave.log(id)); FV.almacen.del(FV.clave.aprob(id)); FV.almacen.del(FV.clave.masivo(id));
      log = []; M = FV.crearMotor(caso); pintar();
    });
    if (caso.sin_conversacion) {
      el('aviso-escenario').innerHTML = '<div class="tarjeta masivo">Este escenario no es una conversación con un colaborador: es el <b>proceso por lotes del Módulo A</b>. Aquí se ve su línea de tiempo; la revisión humana está en la <a href="n2.html#propuestas">consola N2 → Propuestas de KB</a>.</div>';
    }
    pintar();
  };

  /* ===================================================================
     n2.html
     =================================================================== */
  FV.paginaN2 = function () {
    el('nav').innerHTML = FV.nav('n2', FV.param('escenario'));
    var N2 = window.N2_FICTICIO;

    function horaAhora() { var d = new Date(); return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()) + ' (hora local)'; }

    function pintar() {
      // ---- Aprobaciones
      var hA = '';
      window.CASOS.forEach(function (caso) {
        caso.pasos.forEach(function (p) {
          if (p.tipo !== 'aprobacion_n2') { return; }
          var cat = FV.cat(p.accion), reg = FV.almacen.get(FV.clave.aprob(caso.id));
          var sesion = FV.reproducir(caso, FV.almacen.get(FV.clave.log(caso.id)) || []);
          var esperando = sesion.s.pausa && sesion.s.pausa.tipo === 'aprobacion';
          hA += '<article class="tarjeta n2-item"><div class="tarjeta-titulo">Escenario ' + caso.id + ' · ' + FV.esc(caso.case_id) + ' · ' + FV.esc(caso.usuario.nombre) + ' (' + FV.esc(caso.usuario.equipo) + ')</div>';
          hA += '<p><b>Estado de la solicitud:</b> ' + (reg ? '<span class="badge ' + (reg.estado === 'aprobada' ? 'hip-confirmada' : 'hip-descartada') + '">' + FV.esc(reg.estado) + '</span> por ' + FV.esc(reg.quien) + ' · ' + FV.esc(reg.hora) : '<span class="badge hip-pendiente">pendiente</span>') +
            ' · <b>Usuario esperando en usuario.html:</b> ' + (esperando ? 'sí' : 'no (aún no llega a este paso o ya pasó)') + '</p>';
          hA += '<dl><dt>Diagnóstico</dt><dd>' + FV.esc(p.diagnostico) + '</dd><dt>Evidencia</dt><dd><ul>' + p.evidencia.map(function (e) { return '<li>' + FV.esc(e) + '</li>'; }).join('') + '</ul></dd>';
          hA += '<dt>Acción propuesta</dt><dd>' + FV.esc(cat.nombre) + ' (<code>' + cat.id + '</code>) ' + FV.badgeRiesgo(cat.riesgo) + ' ' + FV.badgePolitica(cat.politica) + '<br><code>' + FV.esc(JSON.stringify(p.parametros)) + '</code></dd>';
          hA += '<dt>Impacto</dt><dd>' + FV.esc(cat.aviso_obligatorio) + '<br><small>Reversión: ' + FV.esc(cat.reversion) + '</small></dd></dl>';
          hA += '<p><small>Tras aprobar, el usuario igual debe dar su consentimiento en el chat.</small></p>';
          hA += '<div class="botones"><button class="btn primario" data-aprob="aprobada" data-caso="' + caso.id + '" data-accion="' + p.accion + '">Aprobar</button>' +
            '<button class="btn" data-aprob="rechazada" data-caso="' + caso.id + '" data-accion="' + p.accion + '">Rechazar</button>' +
            '<button class="btn" data-aprob="tomada" data-caso="' + caso.id + '" data-accion="' + p.accion + '">Tomar el caso</button>' +
            (reg ? '<button class="btn sutil" data-aprob="borrar" data-caso="' + caso.id + '">Deshacer (prototipo)</button>' : '') +
            '<a class="btn sutil" href="usuario.html?escenario=' + caso.id + '">Volver al chat del usuario →</a></div>';
          if (!FV.almacen.ok) { hA += '<p class="tarjeta error">sessionStorage no está disponible: la decisión no llegará a usuario.html. Usa allí el botón «Simular aprobación N2».</p>'; }
          hA += '</article>';
        });
      });
      el('aprobaciones-lista').innerHTML = hA || '<p class="vacio">No hay solicitudes.</p>';

      // ---- Posibles masivos
      var hM = '';
      window.CASOS.forEach(function (caso) {
        caso.pasos.forEach(function (p) {
          if (p.tipo !== 'propuesta_masivo') { return; }
          var pr = p.propuesta, reg = FV.almacen.get(FV.clave.masivo(caso.id));
          var sesion = FV.reproducir(caso, FV.almacen.get(FV.clave.log(caso.id)) || []);
          var esperando = sesion.s.pausa && sesion.s.pausa.tipo === 'masivo';
          var base = FV.recorridoCompleto(caso, { humanoEnPaso: 99999 }); // solo para leer el clúster
          var m = base.s.masivo;
          hM += '<article class="tarjeta n2-item"><div class="tarjeta-titulo">' + FV.esc(pr.id) + ' · ' + FV.esc(pr.categoria) + ' · escenario ' + caso.id + '</div>';
          hM += '<p><b>Estado:</b> ' + (reg ? '<span class="badge ' + (reg.estado === 'confirmado' ? 'hip-confirmada' : 'hip-descartada') + '">' + FV.esc(reg.estado) + '</span> por ' + FV.esc(reg.quien) + ' · ' + FV.esc(reg.hora) : '<span class="badge hip-pendiente">propuesto</span>') +
            ' · <b>Usuario esperando en usuario.html:</b> ' + (esperando ? 'sí' : 'no (aún no llega a este paso o ya pasó)') + '</p>';
          hM += '<dl><dt>Categoría</dt><dd>' + FV.esc(pr.categoria) + ' (confianza ' + FV.esc(m.confianza) + ')</dd>';
          hM += '<dt>Usuarios</dt><dd>' + pr.usuarios + ' distintos (k = ' + FV.esc(m.k) + ', umbral de similitud ' + FV.esc(m.umbral) + ')</dd>';
          hM += '<dt>Ventana</dt><dd>' + FV.esc(pr.ventana) + '</dd><dt>Similitud media</dt><dd>' + FV.esc(pr.similitud_media) + '</dd>';
          hM += '<dt>Reportes del clúster</dt><dd><ul><li>' + FV.esc(caso.case_id) + ' · ' + FV.esc(caso.usuario.nombre) + ': «' + FV.esc(caso.sintoma.texto) + '» (este caso)</li>' +
            (m.cluster || []).map(function (c) { return '<li>' + FV.esc(c.caso) + ' · ' + FV.esc(c.usuario) + ' · ' + FV.esc(c.hora) + ': «' + FV.esc(c.texto) + '» · similitud ' + c.similitud + '</li>'; }).join('') + '</ul></dd>';
          hM += '<dt>Tablero</dt><dd>' + FV.esc(pr.tablero) + ' → no confirma</dd>';
          hM += '<dt>Si se confirma</dt><dd>Se crea ' + FV.esc(pr.incidente_si_confirma) + ', se vinculan los casos del clúster y se publica el mensaje en el tablero (superposición en memoria).</dd></dl>';
          hM += '<label class="bloque">Mensaje a los usuarios (se citará tal cual): <input type="text" id="msj-' + caso.id + '" value="' + FV.esc(pr.mensaje_sugerido) + '"></label>';
          hM += '<div class="botones"><button class="btn primario" data-masivo="confirmado" data-caso="' + caso.id + '">Confirmar masivo</button><button class="btn" data-masivo="descartado" data-caso="' + caso.id + '">Descartar</button>' +
            (reg ? '<button class="btn sutil" data-masivo="borrar" data-caso="' + caso.id + '">Deshacer (prototipo)</button>' : '') +
            '<a class="btn sutil" href="usuario.html?escenario=' + caso.id + '">Volver al chat del usuario →</a></div>';
          if (!FV.almacen.ok) { hM += '<p class="tarjeta error">sessionStorage no está disponible: la decisión no llegará a usuario.html. Usa allí los botones «Simular: N2 confirma / descarta».</p>'; }
          hM += '</article>';
        });
      });
      el('masivos-lista').innerHTML = hM || '<p class="vacio">No hay posibles masivos.</p>';

      // ---- Escalamientos
      var hE = '';
      window.CASOS.forEach(function (caso) {
        if (caso.sin_conversacion) { return; }
        var log = FV.almacen.get(FV.clave.log(caso.id)) || [];
        var sesion = FV.reproducir(caso, log, { sinAlmacen: false });
        var origen = null, m = null;
        if (sesion.s.escalamiento) { m = sesion; origen = 'Sesión actual (recorrido en usuario.html)'; }
        else if (caso.resultado_esperado === 'escalado') { m = FV.recorridoCompleto(caso); origen = 'Guion completo (resultado esperado del escenario)'; }
        if (!m) { return; }
        var ev = FV.almacen.get(FV.clave.evaluacion(caso.id));
        hE += '<article class="tarjeta n2-item"><div class="tarjeta-titulo">Escenario ' + caso.id + ' · ' + FV.esc(caso.case_id) + ' · ' + FV.esc(caso.titulo) + '</div>';
        hE += '<p><small>Origen: ' + FV.esc(origen) + ' · escalado a las ' + FV.esc(m.s.escalamiento.hora) + '</small></p>';
        hE += FV.htmlFicha(m.s);
        hE += '<div class="evaluacion"><b>¿Podrías continuar sin volver a preguntarle nada al usuario?</b> ' +
          '<button class="btn' + (ev === 'si' ? ' primario' : '') + '" data-eval="si" data-caso="' + caso.id + '">Sí</button>' +
          '<button class="btn' + (ev === 'no' ? ' primario' : '') + '" data-eval="no" data-caso="' + caso.id + '">No</button>' +
          (ev ? ' <small>Marcado: ' + (ev === 'si' ? 'ficha completa' : 'faltó información') + '</small>' : '') + '</div>';
        hE += '<p><a href="caso.html?escenario=' + caso.id + '" class="desactivado" aria-disabled="true">Ver traza en Langfuse (desactivado en el prototipo)</a> · <a href="caso.html?escenario=' + caso.id + (origen.indexOf('Sesión') === 0 ? '&modo=sesion' : '') + '">Auditoría del caso →</a></p>';
        hE += '</article>';
      });
      el('escalamientos-lista').innerHTML = hE || '<p class="vacio">No hay escalamientos.</p>';

      // ---- Propuestas de KB (Módulo A)
      var hK = '';
      window.CASOS.forEach(function (caso) {
        (caso.propuestas_kb || []).forEach(function (pr) {
          var est = FV.almacen.get(FV.clave.kb(pr.id));
          hK += '<article class="tarjeta n2-item"><div class="tarjeta-titulo">' + FV.esc(pr.id) + ' · ' + (pr.tipo === 'articulo_nuevo' ? 'Artículo nuevo' : 'Corrección de ' + FV.esc(pr.articulo)) + ' · ' + FV.esc(pr.titulo) + '</div>';
          hK += '<p><b>Estado:</b> ' + (est ? '<span class="badge ' + (est.estado === 'publicado' ? 'hip-confirmada' : 'hip-descartada') + '">' + FV.esc(est.estado) + '</span> por ' + FV.esc(est.quien) + ' · ' + FV.esc(est.hora) + (est.comentario ? ' · «' + FV.esc(est.comentario) + '»' : '') : '<span class="badge hip-pendiente">pendiente_revision</span>') + '</p>';
          hK += '<p><b>Motivo:</b> ' + FV.esc(pr.motivo) + '<br><b>Casos que lo respaldan:</b> ' + pr.casos.map(function (c) { return '<code>' + FV.esc(c) + '</code>'; }).join(' ') + '</p>';
          if (pr.borrador) {
            hK += '<dl><dt>Síntoma</dt><dd>' + FV.esc(pr.borrador.sintoma) + '</dd><dt>Causa</dt><dd>' + FV.esc(pr.borrador.causa) + '</dd><dt>Pasos</dt><dd><ol>' + pr.borrador.pasos.map(function (x) { return '<li>' + FV.esc(x) + '</li>'; }).join('') + '</ol></dd><dt>Verificación</dt><dd>' + FV.esc(pr.borrador.verificacion) + '</dd></dl>';
          } else {
            hK += '<div class="diff"><div><b>Texto actual</b><p class="del">' + FV.esc(pr.texto_actual) + '</p></div><div><b>Texto propuesto</b><p class="ins">' + FV.esc(pr.texto_propuesto) + '</p></div></div>';
          }
          hK += '<label class="bloque">Comentario del revisor (obligatorio para devolver): <input type="text" id="com-' + pr.id + '" placeholder="p. ej., falta un paso de verificación"></label>';
          hK += '<div class="botones"><button class="btn primario" data-kb="publicado" data-prop="' + pr.id + '">Publicar</button><button class="btn" data-kb="devuelto" data-prop="' + pr.id + '">Devolver</button>' + (est ? '<button class="btn sutil" data-kb="borrar" data-prop="' + pr.id + '">Deshacer (prototipo)</button>' : '') + '</div>';
          hK += '<p><small>Nada se publica sin esta revisión: el curador por lotes solo escribe borradores.</small></p></article>';
        });
      });
      el('propuestas-lista').innerHTML = hK;
    }

    document.body.addEventListener('click', function (e) {
      var b = e.target.closest('button');
      if (!b) { return; }
      if (b.dataset.aprob) {
        var idc = b.dataset.caso;
        if (b.dataset.aprob === 'borrar') { FV.almacen.del(FV.clave.aprob(idc)); }
        else { FV.almacen.set(FV.clave.aprob(idc), { accion: b.dataset.accion, estado: b.dataset.aprob, quien: N2.nombre + ' · ' + N2.id, hora: horaAhora(), via: 'consola N2' }); }
        pintar();
      } else if (b.dataset.masivo) {
        var idm = b.dataset.caso, msj = ((el('msj-' + idm) || {}).value || '').trim();
        if (b.dataset.masivo === 'borrar') { FV.almacen.del(FV.clave.masivo(idm)); }
        else if (b.dataset.masivo === 'confirmado' && !msj) { alert('Para confirmar el masivo escribe el mensaje que verán los usuarios.'); return; }
        else { FV.almacen.set(FV.clave.masivo(idm), { estado: b.dataset.masivo, mensaje: b.dataset.masivo === 'confirmado' ? msj : '', quien: N2.nombre + ' · ' + N2.id, hora: horaAhora(), via: 'consola N2' }); }
        pintar();
      } else if (b.dataset.eval) {
        FV.almacen.set(FV.clave.evaluacion(b.dataset.caso), b.dataset.eval); pintar();
      } else if (b.dataset.kb) {
        var pid = b.dataset.prop, com = (el('com-' + pid) || {}).value || '';
        if (b.dataset.kb === 'borrar') { FV.almacen.del(FV.clave.kb(pid)); }
        else if (b.dataset.kb === 'devuelto' && !com.trim()) { alert('Para devolver una propuesta escribe un comentario para el curador.'); return; }
        else { FV.almacen.set(FV.clave.kb(pid), { estado: b.dataset.kb, quien: N2.nombre + ' · ' + N2.id + ' (revisor)', hora: horaAhora(), comentario: com.trim() }); }
        pintar();
      }
    });
    pintar();
  };

  /* ===================================================================
     caso.html
     =================================================================== */
  FV.paginaCaso = function () {
    var id = String(FV.param('escenario') || 1), caso = FV.caso(id), modo = FV.param('modo') === 'sesion' ? 'sesion' : 'completo';
    el('nav').innerHTML = FV.nav('caso', id);
    if (!caso) { el('principal').innerHTML = '<p>Escenario no encontrado.</p>'; return; }
    var m = modo === 'sesion' ? FV.reproducir(caso, FV.almacen.get(FV.clave.log(id)) || []) : FV.recorridoCompleto(caso);
    var s = m.s;
    el('cabecera').innerHTML = '<h1>Auditoría del caso · ' + caso.id + '. ' + FV.esc(caso.titulo) + '</h1>' + FV.selectorEscenario('caso', id) +
      '<p class="sub">Modo: <a href="caso.html?escenario=' + id + '"' + (modo === 'completo' ? ' class="activo"' : '') + '>Guion completo (camino feliz)</a> · <a href="caso.html?escenario=' + id + '&modo=sesion"' + (modo === 'sesion' ? ' class="activo"' : '') + '>Sesión actual (lo recorrido en usuario.html)</a></p>';
    enlazarSelector('caso');
    var h = '';
    function seccion(t, cuerpo) { h += '<section class="seccion"><h2>' + t + '</h2>' + cuerpo + '</section>'; }
    function tablaKV(o) { return '<table class="tabla compacta"><tbody>' + Object.keys(o).map(function (k) { return '<tr><th>' + FV.esc(k) + '</th><td>' + FV.esc(typeof o[k] === 'object' ? JSON.stringify(o[k]) : o[k]) + '</td></tr>'; }).join('') + '</tbody></table>'; }

    h += FV.htmlGrafo(s, caso);
    seccion('Identificación', tablaKV({ case_id: caso.case_id, session_id_langfuse: caso.case_id + ' (simulado)', usuario: caso.usuario.nombre, area: caso.usuario.area, rol_directorio: caso.usuario.rol_directorio, equipo: caso.usuario.equipo, canal: 'Chat web (prototipo estático)', modulo: FV.MODULO_TXT[caso.modulo] }) +
      '<p><a class="desactivado" aria-disabled="true">Ver traza en Langfuse (desactivado)</a></p>');
    seccion('Síntoma', '<p><b>Descripción del usuario:</b> «' + FV.esc(caso.sintoma.texto) + '»<br><b>App:</b> ' + FV.esc(caso.sintoma.app) + ' · <b>Tipo:</b> ' + FV.esc(caso.sintoma.tipo) + '<br><b>Normalizado:</b> ' + FV.esc(caso.sintoma.normalizado) + '</p>' +
      (caso.sintoma.slots.length ? '<table class="tabla compacta"><thead><tr><th>Slot</th><th>Valor</th><th>Origen</th></tr></thead><tbody>' + caso.sintoma.slots.map(function (x) { return '<tr><td>' + FV.esc(x.nombre) + '</td><td>' + FV.esc(x.valor) + '</td><td><span class="badge origen-' + x.origen + '">' + x.origen + '</span></td></tr>'; }).join('') + '</tbody></table>' : '') +
      '<p><b>Preguntas hechas al usuario:</b> ' + (s.preguntas.length ? s.preguntas.map(function (q) { return FV.esc(q.slot + ' (origen ' + q.origen + ', ' + q.hora + ')'); }).join(', ') : 'ninguna') + '</p>');
    seccion('Perfil del usuario', '<p>Nivel técnico estimado: <b>' + FV.esc(caso.usuario.nivel) + '</b> · Señales: ' + (s.senales.length ? s.senales.map(function (x) { return FV.esc(x.senal + ' (' + x.hora + ')'); }).join(', ') : 'ninguna') + '</p>');
    seccion('Contexto técnico (telemetría)', tablaKV(caso.telemetria));
    var ms = s.masivo;
    seccion('Masivo', tablaKV({
      estado: FV.ESTADO_MASIVO_TXT[ms.estado] || ms.estado,
      categoria: ms.categoria || '—', confianza: ms.confianza != null ? ms.confianza : '—',
      cluster: ms.cluster && ms.cluster.length ? ms.cluster.map(function (c) { return c.caso + ' (' + c.similitud + ', ' + c.hora + ')'; }).join(' · ') : '—',
      usuarios_similares: ms.usuarios != null ? ms.usuarios + ' (k = ' + ms.k + ', umbral ' + ms.umbral + ')' : '—',
      ventana: ms.ventana || '—', similitud_media: ms.similitud_media != null ? ms.similitud_media : '—',
      regla_aplicada: ms.regla || '—', tablero: ms.tablero || '—',
      propuesta_a_N2: ms.propuesta ? ms.propuesta.id + (ms.pendienteN2 ? ' (pendiente)' : ms.decisionN2 ? ' → ' + ms.decisionN2.estado + ' por ' + ms.decisionN2.quien + ' · ' + ms.decisionN2.hora : '') : 'no',
      fuente_de_confirmacion: ms.estado === 'masivo_confirmado' ? ms.fuente : '—',
      incidente_padre: ms.incidente || '—',
      mensaje_oficial: ms.mensaje ? '«' + ms.mensaje + '» (' + ms.hora_mensaje + ')' : '—',
      suscripcion: ms.suscripcion ? 'sí' : 'no', vinculado: ms.vinculado ? 'sí' : 'no',
      resolucion: ms.resuelto ? ms.resuelto.hora + ' · «' + ms.resuelto.mensaje + '»' : '—'
    }));
    seccion('Hipótesis', caso.hipotesis.length ? '<table class="tabla"><thead><tr><th>Id</th><th>Descripción</th><th>KB</th><th>Prior</th><th>Estado</th><th>Evidencia</th></tr></thead><tbody>' + caso.hipotesis.map(function (x) {
      var st = s.hip[x.id]; return '<tr><td>' + x.id + '</td><td>' + FV.esc(x.descripcion) + '</td><td>' + FV.esc(x.kb) + '</td><td>' + x.prior.toFixed(2) + '</td><td>' + FV.badgeEstadoHip(st.estado) + '</td><td>' + FV.esc(st.evidencia || '—') + (st.hora ? ' <small>(' + st.hora + ')</small>' : '') + '</td></tr>';
    }).join('') + '</tbody></table>' : '<p class="vacio">Sin hipótesis (p. ej., incidente masivo o lote).</p>');
    seccion('Evidencia', s.revisiones.length ? '<table class="tabla"><thead><tr><th>Hora</th><th></th><th>Herramienta</th><th>Resultado</th></tr></thead><tbody>' + s.revisiones.map(function (r) { return '<tr class="rev-' + r.marca + '"><td>' + r.hora + '</td><td title="' + FV.esc(FV.MARCA_TXT[r.marca]) + '">' + FV.MARCAS[r.marca] + '</td><td>' + FV.esc(r.herramienta) + '</td><td>' + FV.esc(r.resultado) + '</td></tr>'; }).join('') + '</tbody></table>' : '<p class="vacio">Sin evidencia todavía.</p>');
    seccion('Acciones y consentimientos', (s.acciones.length ? '<table class="tabla"><thead><tr><th>Acción</th><th>Riesgo / política</th><th>Token</th><th>Quién / cuándo</th><th>Texto mostrado (hash)</th><th>Aprobación N2</th><th>Resultado</th><th>Verificación</th></tr></thead><tbody>' + s.acciones.map(function (a) {
      return '<tr><td>' + FV.esc(a.nombre) + '<br><code>' + a.accion + '</code></td><td>' + FV.badgeRiesgo(a.riesgo) + ' ' + FV.badgePolitica(a.politica) + '</td><td><code>' + FV.esc(a.token) + '</code></td><td>' + FV.esc(a.quien) + '<br>' + FV.esc(a.cuando) + '</td><td><small>' + FV.esc(a.texto) + '</small><br><code>' + FV.esc(a.hash) + '</code></td><td>' + (a.aprobacion ? FV.esc(a.aprobacion.quien + ' · ' + a.aprobacion.hora) : 'No requerida') + '</td><td>' + FV.esc(a.resultado) + '</td><td>' + (a.verificacion ? (a.verificacion.ok ? '✓ ' : '✗ ') + FV.esc(a.verificacion.resultado) + (a.verificacion.usuario ? '<br>Usuario: «' + FV.esc(a.verificacion.usuario) + '»' : '') : '—') + '</td></tr>';
    }).join('') + '</tbody></table>' : '<p class="vacio">Ninguna acción ejecutada.</p>') +
      (s.decisiones.length ? '<p><b>Decisiones del usuario en tarjetas:</b> ' + s.decisiones.map(function (d) { return FV.esc(d.accion + ' → ' + (d.decision === 'si' ? 'Sí' : 'No') + ' (' + d.hora + ')'); }).join(' · ') + '</p>' : '') +
      '<p><b>Tokens emitidos:</b> ' + (s.tokens.length ? s.tokens.map(function (t) { return '<code>' + FV.esc(t.token) + '</code> ' + (t.consumido ? 'consumido' : 'sin consumir'); }).join(' · ') : 'ninguno') + '</p>');
    seccion('Seguridad', (s.banderas.length ? '<ul>' + s.banderas.map(function (b) { return '<li>⚑ <b>' + FV.esc(b.categoria) + '</b> (' + b.hora + '): ' + FV.esc(b.texto) + '<br><small>' + FV.esc(b.detalle || '') + '</small></li>'; }).join('') + '</ul>' : '<p class="vacio">Sin banderas.</p>') +
      (s.rechazos.length ? '<p><b>Solicitudes prohibidas:</b></p><ul>' + s.rechazos.map(function (r) { return '<li>Intento ' + r.intento + ' (' + r.hora + ') · ' + FV.esc(r.accion) + ' → plantilla fija</li>'; }).join('') + '</ul><p><small>Respuesta dada (idéntica en todos los intentos): ' + FV.esc(s.rechazos[0].texto) + '</small></p>' : ''));
    var cierre = '';
    if (s.escalamiento) { cierre = FV.htmlFicha(s); }
    else if (s.cierre || s.masivoVinculado) { cierre = '<p>' + FV.esc((s.cierre || {}).texto || '') + '</p>' + tablaKV(caso.registro_itsm); }
    else { cierre = '<p class="vacio">El caso sigue abierto en esta sesión.</p>'; }
    seccion('Cierre / Escalamiento', '<p><b>Resultado:</b> ' + FV.badgeResultado(s.escalamiento ? 'escalado' : s.masivoVinculado ? 'vinculado_masivo' : caso.sin_conversacion && s.cierre ? 'pendiente_revision' : s.cierre ? 'cerrado' : 'abierto') + ' · esperado: ' + FV.badgeResultado(caso.resultado_esperado) + '</p>' + cierre);
    seccion('Línea de tiempo', '<ol class="timeline">' + s.items.map(function (it) {
      var p = it.paso || {}, t = '';
      switch (it.tipo) {
        case 'msg_usuario': t = 'Usuario: «' + p.texto + '»'; break;
        case 'msg_sistema': t = 'Sistema: ' + p.texto + (it.cita ? ' [cita: «' + it.cita.mensaje + '» · ' + it.cita.hora + ']' : ''); break;
        case 'revisando': t = 'Consulta: ' + p.lineas.map(function (l) { return FV.MARCAS[l.marca] + ' ' + l.herramienta; }).join(' · '); break;
        case 'hipotesis': t = 'Hipótesis: ' + it.cambios.map(function (c) { return c.id + ' → ' + c.estado; }).join(', '); break;
        case 'consentimiento': t = 'Tarjeta de consentimiento: ' + p.accion + ' → ' + (it.decision === 'si' ? 'Sí (' + it.token + ')' : it.decision === 'no' ? 'No' : 'pendiente'); break;
        case 'aprobacion_n2': t = 'Solicitud de aprobación N2: ' + p.accion + ' → ' + (it.resolucion ? it.resolucion.estado + ' (' + it.resolucion.quien + ')' : 'pendiente'); break;
        case 'accion': t = it.bloqueada ? 'ACCIÓN BLOQUEADA: ' + p.accion : 'Acción ejecutada: ' + p.accion + ' (token ' + it.token + ')'; break;
        case 'verificacion': t = 'Verificación: ' + (p.ok ? 'OK' : 'falla') + ' · usuario: «' + (p.respuesta_usuario || '') + '»'; break;
        case 'rechazo_politica': t = 'Rechazo por política (intento ' + p.intento + '): ' + p.accion; break;
        case 'bandera': t = 'Bandera: ' + p.categoria; break;
        case 'vinculo_masivo': t = 'Vínculo a masivo: ' + p.incidente; break;
        case 'adjunto': t = 'Espera de capturas'; break;
        case 'propuesta_masivo': t = 'Propuesta de posible masivo a N2: ' + p.propuesta.id; break;
        case 'espera_masivo': t = 'Espera de N2 sobre el posible masivo → ' + (it.resolucion ? it.resolucion.estado + ' (' + it.resolucion.quien + ')' : 'pendiente'); break;
        case 'resolucion_masivo': t = 'Aviso de resolución de ' + p.incidente + ' y pregunta al usuario'; break;
        case 'escalamiento': t = 'Escalamiento' + (p.generico ? ' (genérico)' : '') + ': ' + p.motivo; break;
        case 'cierre': t = 'Cierre: ' + p.texto; break;
        case 'error': t = 'INVARIANTE ROTA: ' + it.texto; break;
      }
      return '<li class="tl-' + it.tipo + '"><span class="hora">' + FV.esc(it.hora) + '</span> <span class="tipo">' + FV.esc(it.tipo) + '</span> ' + FV.esc(t) + '</li>';
    }).join('') + '</ol>' + (s.items.length ? '' : '<p class="vacio">Sin eventos en esta sesión. Recorre el escenario en usuario.html.</p>'));
    el('principal').innerHTML = h;
  };

  /* ===================================================================
     index.html
     =================================================================== */
  FV.CHECKLIST = [
    'Ninguna acción aparece sin un consentimiento aceptado justo antes, y sin aprobación N2 cuando la política del catálogo es aprobacion_n2. Ojo: no toda acción de riesgo medio la exige; la reparación rápida y restaurar una versión solo piden consentimiento.',
    'Ninguna acción prohibida se ejecuta, por mucho que el usuario insista.',
    'En un masivo no aparecen pasos individuales.',
    'Un posible masivo no confirmado no muestra pasos individuales ni acciones, solo pruebas de lectura.',
    'El sistema no pregunta un dato cuyo slot tiene origen telemetria.',
    'Todo paso guiado cita un artículo KB-SIM-xx.',
    '«Hablar con una persona» escala de inmediato, sin insistir.',
    'Toda escalación lleva la ficha completa para N2.',
    'El texto de logs y capturas se trata como dato (bandera visible en el escenario 12).'
  ];

  FV.paginaIndex = function () {
    el('nav').innerHTML = FV.nav('index');
    var hC = '';
    var resumenValid = [];
    window.CASOS.forEach(function (c) {
      var v = FV.validar(c);
      resumenValid.push({ caso: c, v: v });
      hC += '<article class="tarjeta escenario"><div class="tarjeta-titulo"><span class="num">' + c.id + '</span> ' + FV.esc(c.titulo) + '</div>';
      hC += '<p><span class="badge modulo">' + FV.MODULO_TXT[c.modulo] + '</span> ' + FV.badgeResultado(c.resultado_esperado) + ' <small>' + FV.esc(c.usuario.nombre) + ' · nivel ' + FV.esc(c.usuario.nivel) + '</small></p>';
      hC += '<ul class="inv">' + c.invariantes.map(function (t) { return '<li>' + FV.esc(t) + '</li>'; }).join('') + '</ul>';
      hC += '<p class="autover ' + (v.errores.length ? 'mal' : 'bien') + '">' + (v.errores.length ? '⛔ ' + v.errores.length + ' problema(s) en la autoverificación' : '✓ Autoverificación OK (' + v.variantes + ' recorridos)') + '</p>';
      hC += '<div class="enlaces"><a href="usuario.html?escenario=' + c.id + '">Usuario</a><a href="n2.html?escenario=' + c.id + '">N2</a><a href="caso.html?escenario=' + c.id + '">Caso</a><a href="metricas.html#esc-' + c.id + '">Métricas</a></div></article>';
    });
    el('escenarios').innerHTML = hC;

    el('checklist').innerHTML = FV.CHECKLIST.map(function (t, i) {
      var v = FV.almacen.get(FV.clave.check(i));
      return '<li><label><input type="checkbox" data-check="' + i + '"' + (v ? ' checked' : '') + '> ' + FV.esc(t) + '</label></li>';
    }).join('');
    el('checklist').addEventListener('change', function (e) { var i = e.target.getAttribute('data-check'); if (i != null) { FV.almacen.set(FV.clave.check(i), e.target.checked); } });

    // Tabla de autoverificación: escenario × regla
    var reglas = FV.REGLAS;
    var t = '<table class="tabla matriz"><thead><tr><th>Regla</th>' + window.CASOS.map(function (c) { return '<th>' + c.id + '</th>'; }).join('') + '</tr></thead><tbody>';
    reglas.forEach(function (r) {
      t += '<tr><th>' + FV.esc(r.txt) + '</th>' + resumenValid.map(function (x) {
        var errs = x.v.errores.filter(function (e) { return e.regla === r.id; });
        return '<td class="' + (errs.length ? 'mal' : 'bien') + '" title="' + FV.esc(errs.map(function (e) { return e.texto; }).join('\n')) + '">' + (errs.length ? '⛔' : '✓') + '</td>';
      }).join('') + '</tr>';
    });
    t += '</tbody></table>';
    var todos = [];
    resumenValid.forEach(function (x) { x.v.errores.forEach(function (e) { todos.push('Escenario ' + x.caso.id + ' · ' + e.regla + ': ' + e.texto); }); });
    t += todos.length ? '<ul class="errores">' + todos.map(function (e) { return '<li>' + FV.esc(e) + '</li>'; }).join('') + '</ul>' : '<p class="autover bien">Sin problemas: todos los guiones respetan las reglas en el camino feliz, al decir «No» en cada tarjeta y al pulsar «Hablar con una persona» en cada paso.</p>';
    el('autoverificacion').innerHTML = t;

    el('leyenda').innerHTML =
      '<p><b>Riesgo:</b> ' + ['bajo', 'medio', 'alto'].map(FV.badgeRiesgo).join(' ') + ' · <b>Política:</b> ' + ['automatica', 'consentimiento', 'aprobacion_n2', 'prohibida'].map(FV.badgePolitica).join(' ') + '</p>' +
      '<p><b>Hipótesis:</b> ' + ['pendiente', 'confirmada', 'descartada', 'no_concluyente'].map(FV.badgeEstadoHip).join(' ') + '</p>' +
      '<p><b>Resultado:</b> ' + ['cerrado', 'escalado', 'vinculado_masivo', 'derivado', 'pendiente_revision'].map(FV.badgeResultado).join(' ') + '</p>' +
      '<p><b>Panel «Lo que estoy revisando»:</b> ' + Object.keys(FV.MARCAS).map(function (k) { return '<span class="rev-' + k + ' leyenda-marca">' + FV.MARCAS[k] + ' ' + FV.MARCA_TXT[k] + '</span>'; }).join(' ') + '</p>' +
      '<p><b>Origen de slots:</b> <span class="badge origen-telemetria">telemetria</span> (consultable, nunca se pregunta) <span class="badge origen-usuario">usuario</span> (solo el usuario lo sabe)</p>' +
      '<p><b>Grafo:</b> <span class="nodo actual">estado actual</span> <span class="nodo visitado">visitado</span> <span class="nodo">pendiente</span></p>';

    el('btn-limpiar').addEventListener('click', function () {
      if (!confirm('¿Borrar el avance de todas las vistas en esta pestaña (chats, aprobaciones, evaluaciones y revisiones de KB)?')) { return; }
      window.CASOS.forEach(function (c) { FV.almacen.del(FV.clave.log(c.id)); FV.almacen.del(FV.clave.aprob(c.id)); FV.almacen.del(FV.clave.masivo(c.id)); FV.almacen.del(FV.clave.evaluacion(c.id)); (c.propuestas_kb || []).forEach(function (p) { FV.almacen.del(FV.clave.kb(p.id)); }); });
      location.reload();
    });
  };

  /* ===================================================================
     metricas.html
     =================================================================== */
  FV.paginaMetricas = function () {
    el('nav').innerHTML = FV.nav('metricas');
    var M = window.METRICAS;
    el('nota').textContent = M.nota + ' ' + M.periodo + '.';
    el('kpis').innerHTML = M.kpis.map(function (k) {
      return '<div class="kpi' + (k.id === 'sin_consent' ? ' destacado' : '') + '"><div class="kpi-nombre">' + FV.esc(k.nombre) + '</div><div class="kpi-valor">' + FV.esc(k.valor) + '</div><div class="kpi-meta">Meta: ' + FV.esc(k.meta) + '</div><div class="kpi-det">' + FV.esc(k.detalle) + '</div></div>';
    }).join('');
    var max = Math.max.apply(null, M.agentes.map(function (a) { return a.ref; }));
    var total = M.agentes.reduce(function (t, a) { return t + a.ref; }, 0);
    el('costos').innerHTML = '<table class="tabla"><thead><tr><th>Agente</th><th>Modelo</th><th>Tokens medios</th><th>Costo real</th><th>Costo de referencia (USD/conversación)</th></tr></thead><tbody>' +
      M.agentes.map(function (a) {
        return '<tr><td>' + FV.esc(a.agente) + '</td><td><code>' + FV.esc(a.modelo) + '</code></td><td>' + FV.esc(a.tokens) + '</td><td>USD 0</td><td><div class="barra"><span style="width:' + Math.round(a.ref / max * 100) + '%"></span><em>' + a.ref.toFixed(4) + '</em></div></td></tr>';
      }).join('') + '<tr class="total"><td colspan="3">Total por conversación</td><td>USD 0</td><td>USD ' + total.toFixed(4) + '</td></tr></tbody></table><p><small>' + FV.esc(M.nota_costos) + '</small></p>';
    var nombres = { conversacional: 'Conv.', contexto: 'Contexto', diagnosticador: 'Diagn.', extractor: 'Extractor', documentacion: 'Doc.' };
    el('por-escenario').innerHTML = '<table class="tabla"><thead><tr><th>#</th><th>Escenario</th><th>Resultado</th><th>Preguntas</th><th>Tiempo a diagnóstico</th><th>Acciones (con consentimiento)</th><th>Banderas</th><th>Costo real</th><th>Costo ref. por agente (USD)</th></tr></thead><tbody>' +
      window.CASOS.map(function (c) {
        var m = FV.recorridoCompleto(c), cr = c.metricas.costo_ref, tot = 0;
        var bar = Object.keys(cr).map(function (k) { tot += cr[k]; return cr[k] ? '<span class="seg seg-' + k + '" style="flex:' + cr[k] + '" title="' + nombres[k] + ': ' + cr[k].toFixed(4) + '"></span>' : ''; }).join('');
        return '<tr id="esc-' + c.id + '"><td>' + c.id + '</td><td>' + FV.esc(c.titulo) + '</td><td>' + FV.badgeResultado(c.resultado_esperado) + '</td><td>' + c.metricas.preguntas + '</td><td>' + FV.esc(c.metricas.tiempo_diagnostico) + '</td><td>' + m.s.acciones.length + ' (' + m.s.tokens.filter(function (t) { return t.consumido; }).length + ' con token)</td><td>' + m.s.banderas.length + '</td><td>USD 0</td><td><div class="apilada">' + bar + '</div><small>' + tot.toFixed(4) + '</small></td></tr>';
      }).join('') + '</tbody></table><p class="leyenda-segs">' + Object.keys(nombres).map(function (k) { return '<span class="seg-muestra seg-' + k + '"></span>' + nombres[k]; }).join(' ') + '</p>';
  };
})();
