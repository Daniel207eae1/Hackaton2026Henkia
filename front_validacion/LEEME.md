# Prototipo de validación funcional · Caso 5 (datos sintéticos)

Front estático (HTML + CSS + JavaScript puro) para recorrer paso a paso los 12 escenarios del jurado (más la variante 3b) y comprobar que el flujo respeta el diseño (`../Diseno_Arquitectura_Caso5.md`) **antes** de construir los agentes. No usa red, LLM, backend, CDN ni dependencias.

> Todo es ficticio: personas, equipos (`EQ-SIM-…`), errores (`ERR-SIM-…`), artículos (`KB-SIM-…`), casos (`CASO-SIM-…`), tokens (`TOK-SIM-…`), plazos y precios.

## Cómo abrirlo

1. Doble clic en `front_validacion/index.html` (funciona con `file://`).
2. Elige un escenario y abre **Usuario**. Pulsa **«Siguiente paso ▶»** para avanzar el guion.
3. Las tarjetas de consentimiento **detienen** el guion hasta que eliges `Sí, hazlo` o `No, prefiero otra opción`.
4. **«Hablar con una persona»** (botón fijo abajo a la derecha) escala desde cualquier paso y muestra la ficha con lo recolectado hasta ese momento.
5. Escenario 1: cuando el chat quede «en espera de aprobación N2», abre la **Consola N2 en la misma pestaña** (enlace dentro de la tarjeta), pulsa `Aprobar` y vuelve al chat: al recargar, el guion continúa.
   - El avance y las decisiones viven en `sessionStorage` **de esa pestaña**. Si abres N2 en otra pestaña, o si el navegador bloquea el almacenamiento, usa el botón **«Simular aprobación N2»** del panel lateral.
6. Variante 3b: cuando el chat quede «en revisión por N2», abre **Consola N2 → Posibles masivos** en la misma pestaña, pulsa `Confirmar masivo` (con el mensaje para los usuarios) o `Descartar` y vuelve al chat. Si la decisión no llega, el panel lateral tiene «Simular: N2 confirma / descarta».
7. **Reiniciar** borra el avance del escenario. En el índice hay un botón para borrar todo.

| Archivo | Qué hace |
|---|---|
| `index.html` | Tarjetas de los 12 escenarios, leyenda, checklist de invariantes (manual) y **autoverificación** automática escenario × regla |
| `usuario.html?escenario=N` | Chat, panel «Lo que estoy revisando», indicador del grafo, tarjetas, capturas simuladas (esc. 12) |
| `n2.html` | Bandeja de aprobaciones, bandeja de **posibles masivos** (confirmar con mensaje / descartar), bandeja de escalamientos con ficha + evaluación «¿Podrías continuar sin repreguntar?», propuestas de KB (Módulo A) |
| `caso.html?escenario=N` | Estado completo del caso (secciones de §3.4) + línea de tiempo. Modo «guion completo» o «sesión actual» (`&modo=sesion`) |
| `metricas.html` | Maqueta de tablero con números quemados y barras en CSS |
| `datos.js` | `window.CATALOGO`, `window.ANS`, `window.GRAFO`, `window.CASOS` (12 escenarios), `window.METRICAS` |
| `app.js` | Avance del guion, render de las vistas y autoverificación |
| `estilos.css` | Hoja única, tipografía del sistema, colores por riesgo/política/estado |

## Cómo cambiar un escenario

Edita `datos.js`: cada escenario tiene `pasos[]` (el guion). Tipos de paso: `msg_usuario`, `msg_sistema`, `revisando`, `hipotesis`, `consentimiento`, `aprobacion_n2`, `accion`, `verificacion`, `rechazo_politica`, `escalamiento`, `bandera`, `cierre`, más estos extra: `vinculo_masivo` (vínculo + suscripción), `adjunto` (pausa para adjuntar capturas, con una rama por captura), `propuesta_masivo` (posible masivo enviado a N2), `espera_masivo` (pausa hasta que N2 confirme o descarte, con ramas `confirmado` / `descartado`) y `resolucion_masivo` (aviso de resolución + «¿ya te funciona?»).

- Las líneas de `revisando` pueden llevar `efecto_masivo`, que actualiza el estado del masivo: categoría y confianza, clúster, regla, tablero, confirmación y mensaje oficial con su hora.
- Un `msg_sistema` con `cita_masivo: true` cita **tal cual** el mensaje oficial vigente (del tablero o de N2) con su hora.

- El **aviso** de la tarjeta, la **reversión** y el **texto de rechazo** de una acción prohibida salen **solo** del `CATALOGO`. Si un paso trae su propio aviso o texto, la autoverificación lo marca.
- Una `accion` solo se ejecuta si el paso inmediatamente anterior que la habilita es un `consentimiento` aceptado de la **misma** acción (token de un solo uso) y, si la política es `aprobacion_n2`, si hay aprobación previa. Si el guion lo rompe, el chat muestra «⛔ INVARIANTE ROTA» y la acción no se ejecuta.
- `si_rechaza` en un consentimiento define la rama del «No». Sin rama, se escala.
- `pregunta: 'slot'` en un `msg_sistema` declara que el sistema le pregunta ese dato al usuario. Si el slot tiene origen `telemetria`, es un error.
- `guia: true` + `kb` declara un paso guiado. El texto debe citar el `KB-SIM-xx`.

Al abrir `index.html`, cada guion se recorre automáticamente por el camino feliz, diciendo «No» en cada tarjeta y pulsando «Hablar con una persona» antes de cada paso. La tabla «Autoverificación» muestra el resultado regla por regla.

## Qué valida cada escenario

| # | Escenario | Resultado | Qué demuestra |
|---|---|---|---|
| 1 | Outlook no abre | cerrado | Consentimiento para leer logs → extractor en cuarentena → reparación rápida (riesgo medio, **solo consentimiento**) → falla la verificación → **aprobación N2** → consentimiento → recrear perfil → verificación OK |
| 2 | Teams sin audio | cerrado | No pregunta lo que da la telemetría; aviso «cerrará Teams» desde el catálogo; lenguaje simple |
| 3 | Correo masivo | vinculado_masivo | Embedding Qwen3 → categoría y confianza → búsqueda híbrida (pgvector + texto completo, RRF, 60 min, otros usuarios) → 3 usuarios similares → `posible_masivo` → el tablero confirma → `masivo_confirmado`. Cita el tablero tal cual con su hora, vincula a `INC-SIM-0900`, suscribe; al resolverse avisa y pregunta si funciona. **Cero pasos individuales** |
| 3b | Posible masivo sin tablero | vinculado_masivo (si N2 confirma) / cerrado (si descarta) | Clúster igual, pero el tablero no confirma → propuesta `PM-SIM-0007` a N2. El usuario ve «Estamos revisando si otros compañeros…» y solo hay pruebas de lectura. N2 confirma → vincula y cita el mensaje de N2. N2 descarta → diagnóstico individual (modo sin conexión, KB-SIM-06) |
| 4 | OneDrive, disco lleno | cerrado | Slot `espacio_disco` de telemetría: **no se pregunta**; guía en 3 pasos que citan `KB-SIM-21`; verificación técnica + del usuario |
| 5 | Excel sin licencia | escalado | Explica en español el error en inglés; `asignar_licencia` es `aprobacion_n2` → escala con diagnóstico y ANS |
| 6 | Impresión atascada | cerrado | Aviso «se cancelan todos los trabajos»; acción solo después del «Sí» |
| 7 | Archivo sobrescrito | cerrado | Identifica por metadatos sin leer contenido; restaurar versión (riesgo medio, solo consentimiento) conservando la actual |
| 8 | Antivirus insistente | escalado | Mismo rechazo ×3 (plantilla fija); «soy de TI» no cambia nada; bandera de insistencia; camino correcto + escalamiento |
| 9 | Usuario confundido | escalado | Señal de confusión → simplifica → pide una persona → escala de inmediato con la causa ya confirmada |
| 10 | Word se cierra | escalado | 3 hipótesis descartadas con evidencia; consulta de telemetría fallida (⚠) avisada al usuario; escala con lo probado |
| 11 | Módulo A | pendiente_revision | Lote → 2 propuestas con `case_id` → `Publicar` / `Devolver` en N2 (devolver exige comentario) |
| 12 | Módulo B: capturas | cerrado | Captura 1 → código `ERR-SIM-0A12` → diagnóstico; captura 2 con instrucciones → bandera visible, ignorada; se adjuntan en cualquier orden |

## Supuestos tomados (insumo para la siguiente iteración)

1. **Catálogo de acciones.** El diseño define los campos (§3.6) pero no trae la tabla. Se armó con 13 acciones: `consultar_contexto` (automática), `leer_logs` (bajo, consentimiento), `reparacion_rapida_office` (medio, consentimiento), `recrear_perfil_outlook` (medio, aprobación N2), `limpiar_cache_teams` (bajo), `reiniciar_cola_impresion` (bajo, no reversible), `restaurar_version_anterior` (medio, consentimiento), `resincronizar_onedrive` (bajo, no se usa en ningún guion), `asignar_licencia` (medio, aprobación N2) y 4 prohibidas de riesgo alto: `desactivar_antivirus`, `otorgar_permisos_admin`, `control_remoto` y `leer_contenido_usuario`. Hay que validar los textos de aviso y reversión con la mesa de servicio.
2. **ANS simulados:** P3 · 4 horas hábiles para todo escalamiento (también los de seguridad y el «hablar con una persona»); 30 minutos hábiles para la aprobación N2. El diseño los deja abiertos (§12.3).
3. **Tipos de síntoma fuera de la lista del diseño** (`no_abre`, `se_cierra`, `lenta`, `no_sincroniza`, `licencia`, `impresion`): `sin_audio` (esc. 2), `archivo_sobrescrito` (esc. 7), `bloqueo_seguridad` (esc. 8), `no_edita` (esc. 9).
4. **Origen `telemetria`** se usa para todo dato consultable por herramienta (telemetría, directorio, tablero, metadatos de OneDrive), no solo para la telemetría en sentido estricto.
5. **Marcas del panel:** ✓ consulta correcta y nada anormal, ✗ consulta correcta con una anomalía, ⚠ la consulta falló.
6. **Escenario 5:** se escala (resultado `escalado`) en vez de pasar por la bandeja de aprobaciones, porque N2 asigna la licencia en su consola y no el Ejecutor. **Duda:** ¿debería ir por `aprobacion_n2` → consentimiento → Ejecutor, como el escenario 1?
7. **Tras la aprobación N2 se vuelve a pedir consentimiento al usuario** (§3.5: AprobacionN2 → Consentimiento). La aprobación no sustituye el «Sí».
8. **N2 «Rechazar» o «Tomar el caso»** → escalamiento genérico construido desde el estado (§3.5: AprobacionN2 → Escalar).
9. **Un «No» sin rama alternativa** → escalamiento genérico (§3.5: Consentimiento → Escalar). Los escenarios 1, 2, 6 y 12 traen ramas propias.
10. **Escenario 8:** el texto base del rechazo es idéntico en los 3 intentos y ofrece escalar desde el primero; en el 3.º se añade una nota sobre «soy de TI» (§4.4). **Duda:** el diseño (§4.3) dice que la oferta de escalar aparece «al segundo intento»; ¿debe ofrecerse antes?
11. **Escenario 9:** el usuario pide la persona escribiendo en el chat (guion). El botón global hace lo mismo desde cualquier paso.
12. **Escenario 11:** en `usuario.html` se ve la línea de tiempo del lote, no un chat. Umbral simulado de artículo faltante: k = 5 casos. Devolver una propuesta exige un comentario.
13. **Escenario 12:** termina `cerrado` con una reparación rápida (consentimiento). Las capturas se pueden adjuntar en cualquier orden. La bandera queda en el estado en el mismo instante en que el extractor detecta las instrucciones, aunque el aviso al usuario llegue un paso después.
14. **Hipótesis, priors y artículos** (`KB-SIM-03`, `-05`, `-08`, `-11`, `-21`, `-25`, `-31`, `-35`, `-41`, `-51`, `-61`…) son inventados. Umbral de disco simulado: < 5 GB libres.
15. **Tokens:** `TOK-SIM-<escenario>-<n>` con un hash simulado del texto mostrado. Quién firma: el usuario, con un clic en «Sí, hazlo». Aprobador: «Técnico N2 ficticio · TEC-SIM-02». La hora de la aprobación N2 es la hora local real; no altera la hora simulada del guion.
16. **Ficha de escalamiento:** se construye desde el estado del caso (síntoma, telemetría consultada, hipótesis, consultas fallidas, acciones, banderas). Del paso de escalamiento solo salen el motivo, el siguiente paso y el ANS. Si se escala antes de consultar la telemetría, la ficha lo dice.
17. **Botón «Simular aprobación N2»:** el prompt lo pide solo si falla `sessionStorage`. Se muestra siempre que el chat espera a N2, porque `sessionStorage` no se comparte entre pestañas y es fácil abrir N2 en otra.
18. Para que el escenario 1 quepa en 14 pasos, los pasos `consentimiento` y `hipotesis` pueden llevar un `mensaje` (burbuja del sistema) y `verificacion` incluye la respuesta del usuario.
19. **Métricas** quemadas (FCR 75 %, precisión 93 %, p50 38 s, p95 1 min 52 s…). Los precios de referencia son simulados, no precios reales de OpenRouter.
20. **Autoverificación automática** en el índice: es un extra que no pide el prompt. No reemplaza el checklist manual.

### Supuestos de la detección de masivos (§3.11–3.12)

21. **Valores simulados del clúster:** k = 3 usuarios distintos **además** del que reporta, umbral de similitud 0,80, ventana de 60 min. Confianza de la clasificación: 0,91 (esc. 3) y 0,87 (3b). Similitudes: 0,88 / 0,84 / 0,81 y 0,86 / 0,83 / 0,81. En la propuesta de 3b, «4 usuarios» incluye al caso actual.
22. **Estados del masivo en el estado del caso:** `no_evaluado`, `sin_masivo`, `posible_masivo`, `masivo_confirmado`, `descartado`. «Fuente de confirmación» vale `tablero` o `N2 (consola)`.
23. **Variante 3b como escenario aparte** (`id: '3b'`, `CASO-SIM-0013`). Su resultado esperado es `vinculado_masivo` cuando N2 confirma, y `cerrado` cuando descarta. La autoverificación recorre las dos ramas. Las hipótesis esperadas corresponden a la rama «descarta».
24. **Mientras el posible masivo espera a N2** solo se permiten `revisando` (lecturas), mensajes sin guía, banderas y escalamiento. Hipótesis, tarjetas, aprobaciones, acciones, verificaciones o pasos guiados rompen la invariante `posible_masivo`, y también un vínculo sin confirmación. Se decidió que tampoco se cambien estados de hipótesis en ese intervalo, aunque las lecturas sí se registran como evidencia.
25. **Confirmar masivo exige un mensaje.** Ese texto es el que se cita al usuario tal cual, con la hora (local) de la decisión. El incidente padre `INC-SIM-0950` y la «superposición del tablero» solo existen en el texto del prototipo: no se dibuja un tablero aparte.
26. **Suscripción automática** al vincular (antes se le preguntaba al usuario en el esc. 3), como indica §3.11.
27. **Ciclo de resolución (esc. 3):** el aviso llega 1 h después (hora simulada) con el texto del tablero «RESUELTO» y se pregunta «¿ya te funciona?». No se modeló la rama «sigue fallando → reabrir como individual».
28. Los ids de escenario ahora son texto (`3b`); las claves de `sessionStorage` siguen el patrón `fv_<tipo>_<id>`, más la nueva `fv_masivo_<id>`.

## Diferencias entre el prompt y el diseño

- **Riesgo medio ⇒ ¿N2?** El diseño dice en §2.2 («aprobación N2 si es riesgo medio») y en §7.2 («bandeja de aprobaciones (riesgo medio)») que el riesgo medio va a N2. Pero §3.6 asigna la política por acción, y el prompt aclara que la reparación rápida y restaurar una versión solo piden consentimiento. Se siguió la política por acción del catálogo. Conviene alinear la redacción del diseño.
- **Verificación fallida.** En §3.5, Verificación fallida → Reversión → Escalar. En §8 (escenario 1) y en el prompt, si falla la reparación rápida se pide aprobación N2 para recrear el perfil. Se siguió §8.
- **Resultado `pendiente_revision`** (escenario 11): no está en la lista de resultados del modelo de datos del prompt, pero sí en la tabla de guiones. Se añadió.
- **Detección de masivos:** el diseño ya no usa «reportes recientes del mismo servicio» (§3.11), sino un clúster semántico. El escenario 3 se rehízo así. §8 ya refleja el cambio; no hay contradicción pendiente.
- **Canal:** §7.1 recomienda Chainlit, y este prototipo es vanilla por exigencia del prompt. No es contradictorio: el prototipo solo valida el flujo.

## Nota de verificación

Desde el panel del navegador integrado, los `file://` se ven como instantánea estática (sin JS). Por eso los escenarios 1, 2, 3, 3b (las dos ramas), 6, 8, 11 y 12 y las cuatro vistas se probaron con un servidor HTTP local temporal (`python -m http.server`), ya eliminado, sin errores de consola. La lógica es la misma con doble clic. Aun así, conviene que el equipo confirme en su navegador que `sessionStorage` sobrevive al pasar de `usuario.html` a `n2.html` con `file://` (Chrome y Edge lo conservan dentro de la misma pestaña).
