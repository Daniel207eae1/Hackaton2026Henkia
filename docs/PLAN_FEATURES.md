# Plan por features · Caso 5

> Orden obligatorio F0 → F9 (prioridad R1–R8). Una feature se cierra con la **definición de
> terminado** de `CLAUDE.md`. Los criterios de aceptación salen del caso (§1, §2.3, §2.4, §8 del
> diseño y la tabla de escenarios de `front_validacion/LEEME.md`). Las estimaciones son horas de
> una persona con Claude Code; los datos de cada feature los entrega P2 según `db/PLAN_DATOS.md`.

## Resumen

| # | Feature | Requisitos | Escenarios | Dependencias | Horas |
|---|---|---|---|---|---|
| F0 | Fundaciones | Transversal | — | — | 10 |
| F1 | Entender el síntoma y consultar antes de preguntar | R1 | 4 | F0, datos `org`/`telemetria`, Zabbix | 12 |
| F2 | Detección de masivos | R3 | 3, 3b | F1, `buscar_reportes_similares`, `clasificar`, tablero | 10 |
| F3 | Diagnóstico por hipótesis + extractor en cuarentena | R2 | 1, 2, 10 | F1, `buscar_hibrido`, recetas KB, logs | 14 |
| F4 | Consentimiento, políticas, aprobación N2, ejecución vía Zabbix | R4 | 1, 2, 6, 7, 8 | F3, scripts Zabbix | 14 |
| F5 | Verificación, cierre y registro ITSM | R5 | 2, 4, 6, 7 | F4 | 6 |
| F6 | Escalamiento a N2 + "hablar con una persona" | R6 | 5, 8, 9, 10 | F3 (F4 para 8) | 8 |
| F7 | Módulo B: capturas (visión en cuarentena) | R8 | 12 | F3, capturas PNG | 8 |
| F8 | Módulo A: curador de KB + vista del revisor | R7 | 11 | F3, historial | 8 |
| F9 | Evaluación: usuario simulado, datasets, métricas y costo | NFR | todos | F1–F8 | 10 |

Total estimado: **100 h**.

> **Desbloqueo (2026-11-19):** BD de P2 conectada (ADR 0009) y Ollama con `qwen3-embedding:0.6b` (ADR 0011).
> `clasificar` y `buscar_hibrido` verificados en vivo: F2 (clúster semántico) y F3 (recetas de la KB) ya pueden construirse. Camino crítico para la demo (§7.3): F0 → F1 → F3 → F4 → F5 → F6 → F2 → F7.

> **Ajuste de orden justificado:** se mantiene el orden obligatorio, pero F2 puede construirse en
> paralelo a F3 (otra persona) porque solo comparte con F3 el nodo `Contexto`; el grafo ya reserva
> el nodo `ChequeoMasivo` **antes** de `Hipotesis` desde F0.

---

## F0 · Fundaciones (esta sesión)

- **Requisitos:** transversal (trazabilidad, costo, resiliencia, seguridad de acceso).
- **Historias:**
  - Como integrante del equipo, levanto todo con `docker compose up` y veo el sistema andando.
  - Como evaluador de la demo, elijo a quién "ver como" (colaborador, N2, revisor) sin login.
  - Como colaborador, escribo mi problema y recibo una respuesta en *streaming* en español.
  - Como equipo, veo cada turno en Langfuse agrupado por caso.
- **Criterios de aceptación:**
  1. `docker compose up --build` levanta `api`, `web` y `equipos-sim` sin errores; `GET /api/salud` responde 200.
  2. El selector "Ver como" lista personas de `org` (o del doble de pruebas si P2 no ha entregado) con su rol; la etiqueta "Modo demostración" está siempre visible.
  3. Con `MODO_DEMO=false`, cualquier petición con `X-Ver-Como` responde **403**. El rol nunca sale del texto del chat.
  4. Un mensaje produce respuesta en *streaming* (UI Message Stream) del agente Conversacional, a través de la capa LLM agnóstica, con la etapa del grafo visible.
  5. Cambiar el modelo del Conversacional solo requiere editar `config/modelos.yaml`. El arranque falla con mensaje claro si un modelo no cumple la capacidad requerida.
  6. Ante 429 o fallo del modelo principal, se usa el siguiente de la cadena (probado con doble).
  7. Langfuse muestra la traza del turno con `session_id = case_id`, `user_id`, *span* `agente_conversacional` y la *generation* con el modelo y los tokens.
- **Escenarios:** ninguno (habilita todos).
- **Frontend:** `AppShell` (barra superior, "Ver como", "Modo demostración"), `ChatColaborador` (Conversation, Message, PromptInput), `IndicadorEtapa`, `PanelRevisando` (vacío), botón "Hablar con una persona" (deshabilitado hasta F6), rutas de las 5 vistas como *placeholders*.
- **Backend:** `config/` (ajustes + `modelos.yaml` + validación), `llm/` (puerto + adaptador OpenAI‑compatible + `FakeLLM` + registro con *fallback*), `observabilidad/langfuse.py`, `api/` (`/api/salud`, `/api/personas`, `/api/chat`), `api/stream_protocol.py`, `seguridad/ver_como.py`, `orquestador/` (grafo §3.5 con nodos *stub*; `Recepcion → Aclaracion` con el Conversacional), repositorio `org` con doble en memoria.
- **Agentes:** Conversacional.
- **Langfuse:** traza por turno, sesión = `case_id`, *span* `agente_conversacional`, *generation* con `usage`.
- **Riesgos:** sin claves de OpenRouter/Langfuse no se puede verificar en vivo (mitigación: doble `fake` y `.env.example` documentado); incompatibilidades AI Elements ↔ Vite (mitigación: ADR 0002 y anotaciones en `frontend/CLAUDE.md`).
- **Estimación:** 10 h.

## F1 · Entender el síntoma y consultar antes de preguntar (R1)

> **Estado (2026-11-19): hecha** (ADR 0008). Intérprete único (slots + acción candidata), compuerta de preguntas
> por frase, guardia de entrada con respuesta fija (prohibidas, identidad, insistencia), lecturas según el síntoma
> (OneDrive, cola, Teams, perfil de Outlook), tablero oficial para masivos, *scores* `preguntas_hechas`,
> `pregunto_consultable`, `injection_risk`. 35 pruebas nuevas (esc. 4 y 8 incluidos); intérprete real 10/10.
> **Pendiente:** medir "≤ 3 preguntas de media" con usuarios simulados (F9); clasificador LLM de inyección cuando
> haya Ollama; repositorio `org` real (P2); prueba en vivo del turno completo cuando haya cuota de OpenRouter.

- **Historias:**
  - Como colaborador digo "Outlook no sirve" y el sistema entiende la app y el tipo de síntoma.
  - Como colaborador no me preguntan lo que el sistema puede consultar (versión, disco, licencia).
  - Como colaborador veo en "Lo que estoy revisando" qué consultó y qué encontró.
- **Criterios de aceptación:**
  1. Del lenguaje vago (incluido coloquial colombiano, sin tildes o con mensajes en inglés) se extraen `aplicacion` y `tipo_sintoma` en el *enum* del estado, con su origen.
  2. Antes de preguntar, el sistema consulta directorio → equipo → telemetría **vía el MCP `zabbix-ofimatica`** (tools `automatica`, ADR 0007) y llena los *slots* con origen `telemetria`. *(Adelantado en F0: telemetría, versión de Office, licencia y `problemas_activos`; falta OneDrive/cola según el síntoma.)*
  3. **Compuerta de preguntas:** el Conversacional solo puede preguntar *slots* con fuente `usuario` o cuya consulta falló; la guardia de salida bloquea cualquier pregunta por un *slot* consultable. *Score* `pregunto_consultable` = 0.
  4. Media de preguntas hasta el síntoma ≤ 3 en los usuarios simulados.
  5. Si una consulta falla, el usuario recibe "No pude consultar X; voy a revisar Y" (nunca silencio) y queda ⚠ en el panel.
  6. Guardia de entrada básica (heurística de inyección y frases de autoridad) con bandera en el estado.
- **Escenarios:** 4 (disco lleno detectado sin preguntar); parcialmente 2, 5.
- **Frontend:** `PanelRevisando` con líneas ✓/✗/⚠ (AI Elements Task/Tool), partes `data-revisando` y `data-etapa`.
- **Backend:** nodos `Recepcion`, `Contexto`, `Aclaracion`; `integraciones/zabbix/lectura.py`; `seguridad/guardia_entrada.py`, `seguridad/compuerta_preguntas.py`; repositorio `org`.
- **Agentes:** Conversacional (*slots* con salida estructurada), Contexto (telemetría).
- **Langfuse:** *spans* `guardia_entrada`, `agente_contexto`, `zabbix.item.get`; *scores* `preguntas_hechas`, `pregunto_consultable`, `injection_risk`.
- **Riesgos:** Zabbix tarda en levantar (mitigación: puerto `TelemetriaPort` con doble); modelos `:free` débiles en *slot filling* (mitigación: *enum* + reintento + desambiguación).
- **Estimación:** 12 h.

## F2 · Detección de masivos (R3)

> **Estado (2026-11-19): hecha** (ADR 0014). Tablero del MCP → clúster semántico (texto canónico de P2 + `buscar_reportes_similares`)
> → incidente `publicado` (se cita tal cual) o propuesta a N2 (confirmar con mensaje / descartar / resolver), nodo
> `InformarMasivo`, aviso «¿ya te funciona?» por consulta periódica y cierre. Escenarios 3 y 3b verificados en vivo y en el
> navegador. **Pendiente:** calibrar k/umbral/ventana (F9), `setval` de `incidentes_seq` en la semilla de P2.

- **Historias:**
  - Como colaborador afectado por un masivo, me informan el estado oficial y quedo suscrito, sin pasos inútiles.
  - Como N2, recibo propuestas de posible masivo y las confirmo con un mensaje o las descarto.
- **Criterios de aceptación:**
  1. El chequeo de masivo ocurre **antes** de cualquier hipótesis (arista `Contexto → ChequeoMasivo`).
  2. Texto canónico → *embedding* (capa LLM) → `conocimiento.clasificar` → `operacion.buscar_reportes_similares` (misma categoría, ventana, otros usuarios).
  3. ≥ k usuarios distintos con similitud ≥ umbral → `posible_masivo`; si el tablero confirma → `masivo_confirmado`: vincula al incidente padre, cita el mensaje oficial **tal cual con su hora** y suscribe. **Cero pasos individuales.**
  4. Sin confirmación del tablero → propuesta a N2; mientras tanto solo lecturas y el mensaje "Estamos revisando si otros compañeros…". N2 confirma (mensaje obligatorio) → vincula; descarta → diagnóstico individual.
  5. Al resolverse el incidente, se avisa a los vinculados y se pregunta "¿ya te funciona?".
- **Escenarios:** 3 y 3b (ambas ramas).
- **Frontend:** `TarjetaMasivo` (cita del tablero), bandeja "Posibles masivos" en Consola N2 (Confirmar con mensaje / Descartar).
- **Backend:** nodos `ChequeoMasivo`, `InformarMasivo`; `rag/reportes.py`, `rag/clasificador.py`; endpoints `/api/n2/masivos/{id}/confirmar|descartar`; suscripciones.
- **Agentes:** Contexto y Masivos.
- **Langfuse:** *spans* `rag.clasificar`, `rag.buscar_reportes_similares`; *score* `masivo_vinculado`.
- **Riesgos:** umbrales mal calibrados (mitigación: reporte de calibración de P2 + experimento).
- **Estimación:** 10 h.

## F3 · Diagnóstico por hipótesis + extractor en cuarentena (R2)

> **Estado (2026-11-19): hecha** (ADR 0013). Recetas de la KB con prior del historial, reglas en código + Diagnosticador
> con evidencia citada, logs con consentimiento → extractor en cuarentena, guía citando `KB-SIM-xxx`, presupuesto →
> `sin_hipotesis`. Verificado en vivo con la BD de P2. **Pendiente:** lectura de logs en vivo (abre ventana), más
> herramientas del MCP para las recetas que hoy quedan sin evidencia, *score* `diagnostico_correcto` con los usuarios simulados (F9).

- **Historias:**
  - Como colaborador, el sistema prueba causas probables con consultas de solo lectura y me explica qué descartó.
  - Como equipo, ningún texto de logs o errores puede dar órdenes al sistema.
- **Criterios de aceptación:**
  1. Hipótesis ordenadas por prior (historial) y reordenadas con el contexto; cada una con artículo KB de origen, pruebas planeadas y estado.
  2. Pruebas solo de lectura; descartes **con evidencia** referenciada; criterios evaluados en código cuando es posible.
  3. **Plan-Then-Execute:** el plan de pruebas se fija antes de leer logs.
  4. Extractor en cuarentena: sin herramientas, esquema forzado, anclaje literal de `codigo_error`, re-escaneo, bandera = heurística O modelo; salida `no_concluyente` si falla. El Diagnosticador solo recibe campos validados (prueba automática).
  5. Errores en inglés se citan escapados y se explican en español desde la KB.
  6. Presupuesto del ciclo (N hipótesis / M pruebas / tiempo) → escalamiento (esc. 10).
  7. 100 % de las inyecciones del kit en logs marcadas (`injection_flag`).
- **Escenarios:** 1 (parte de diagnóstico), 2, 10.
- **Frontend:** `TarjetaHipotesis` (Reasoning/Task), `Tool` por prueba, `Sources` con `KB-SIM-xxx`, `CitaEscapada`.
- **Backend:** nodos `Hipotesis`, `Prueba`, `Decision`; `rag/kb.py` (`buscar_hibrido`), `seguridad/extractor_cuarentena.py`, `seguridad/heuristicas_inyeccion.py`.
- **Agentes:** Diagnosticador, Extractor en cuarentena.
- **Langfuse:** *spans* `agente_diagnosticador`, `extractor_cuarentena`, `rag.buscar_hibrido`; *scores* `diagnostico_correcto` (offline), `injection_flag`, `tiempo_a_diagnostico`.
- **Riesgos:** precisión baja con modelos `:free` (mitigación: criterios deterministas, A/B en Langfuse).
- **Estimación:** 14 h.

## F4 · Consentimiento, motor de políticas, aprobación N2 y ejecución vía Zabbix (R4)

> **Estado (2026-11-19): cableado** con el MCP `zabbix-ofimatica` (ADR 0007): nodos `Decision`, `AprobacionN2`,
> `Consentimiento`, `Ejecucion`, `Verificacion`; tarjeta `data-accion`; 13 pruebas de flujo + 23 de la puerta + 6 de la
> tarjeta. **Pendiente:** persistir autorizaciones en `operacion`; bandeja de aprobaciones en la Consola N2 (hoy N2
> aprueba en el canal del servidor); `leer_logs` cuando exista el extractor (F3); plantilla de rechazo de acciones
> prohibidas e insistencia (esc. 8); repetir la prueba en vivo con el selector LLM real (hoy simulado) y el camino N2.
> **Prueba en vivo (2026-11-19, DESKTOP-63091):** reiniciar_cola_impresion → ventana autorizada (CS-299384D8) →
> ejecutada → verificación técnica OK, en 25 s. Destapó un falso positivo de masivo (aviso informativo de Wi-Fi):
> la regla ahora exige k ≥ 3 (`MASIVO_MIN_EQUIPOS`) y severidad ≥ advertencia.

- **Historias:**
  - Como colaborador, veo qué hará la acción, su efecto, cómo se revierte y su riesgo, y decido con un botón.
  - Como N2, apruebo o rechazo las acciones con política `aprobacion_n2` con el diagnóstico a la vista.
  - Como colaborador que insiste en algo prohibido, recibo siempre la misma explicación y el camino correcto.
- **Criterios de aceptación:**
  1. Catálogo en `config/catalogo_acciones.yaml`; las prohibidas **no** se registran como herramienta ni como script.
  2. Consentimiento real en la **ventana "Soporte TI" del equipo** (`solicitar_consentimiento` → `consultar_consentimiento`, ADR 0007). `PuertaZabbix` ya garantiza un solo uso, ligado a tool + equipo + caso, vigencia de 15 min y solo ids emitidos por este backend (probado). Falta persistirlo en `operacion` y el nodo `Consentimiento` con `interrupt()` mientras se consulta.
  3. La tarjeta del chat explica qué hará, efecto, reversión y riesgo (del catálogo) y pide autorizar en la ventana del equipo; un "sí" escrito no ejecuta nada.
  4. `aprobacion_n2`: aprobación desde la consola por un usuario con rol N2 de la BD **y luego** consentimiento del usuario.
  5. Ejecutor sin LLM: `PuertaZabbix.ejecutar_accion` con el `consentimiento_id` aprobado (y `aprobacion_id` si es N2); `ejecutar_comando_generico` bloqueada; nunca dice "resuelto" si `ok` es `false`.
  6. `leer_logs` pide consentimiento y su salida va directo al extractor.
  7. Acción prohibida → plantilla fija del catálogo, idéntica en cada intento; bandera de insistencia; oferta de escalar.
  8. *Score* `accion_sin_token` = 0 en todas las corridas.
- **Escenarios:** 1, 2, 6, 7, 8.
- **Frontend:** `TarjetaConsentimiento` (Card + Badge riesgo + Alert aviso + botones), `EsperaN2`, bandeja "Aprobaciones" en Consola N2 (Aprobar / Rechazar / Tomar el caso), pruebas de componente.
- **Backend:** `politicas/catalogo.py`, `politicas/motor.py`, `politicas/tokens.py`, nodos `Consentimiento`, `AprobacionN2`, `Ejecucion` (con `interrupt`), `integraciones/zabbix/acciones.py`, endpoints `/api/casos/{id}/consentimientos`, `/api/n2/aprobaciones/{id}`. `infra/zabbix/`: scripts webhook + `equipos-sim` con efectos.
- **Agentes:** Ejecutor (sin LLM), Conversacional (explica la tarjeta).
- **Langfuse:** eventos `politica.decision`, `consentimiento.token`, `aprobacion_n2.*`; *span* `ejecutor`, `zabbix.script.execute`; *score* `accion_sin_token`.
- **Riesgos:** permisos finos de Zabbix (mitigación: ADR 0005 + prueba de token de lectura).
- **Estimación:** 14 h.

## F5 · Verificación, cierre y registro ITSM (R5)

> **Estado (2026-11-19): hecha salvo la guía desde la KB** (ADR 0010). Confirmación del usuario (botones + reglas),
> cierre con verificación técnica + usuario, registro de cierre desde el estado, proyección ITSM a `operacion`
> (verificada en vivo), *score* `fcr`. **Pendiente:** guía paso a paso citando `KB-SIM-xxx` (F3), auditoría por secciones.

- **Criterios de aceptación:**
  1. Tras cada acción o guía: re-lectura de telemetría/logs vía Zabbix (verificación técnica) **y** confirmación del usuario.
  2. Cierre solo con ambas; si falla y la acción es reversible → reversión y escalamiento (o la siguiente acción, como en el esc. 1, ver ADR 0001).
  3. Registro ITSM replicable: síntoma, contexto, hipótesis, evidencia, acciones con token, verificación y resultado, construido **desde el estado**.
  4. Guía paso a paso desde la KB: cada paso cita `KB-SIM-xxx` (guardia de salida de fundamentación).
- **Escenarios:** 2, 4, 6, 7.
- **Frontend:** `TarjetaVerificacion` (¿Funcionó? Sí/No como evento de UI), vista **Auditoría del caso** (estado, línea de tiempo, hipótesis/evidencia, acciones/tokens, banderas, enlace a Langfuse).
- **Backend:** nodos `Guia`, `Verificacion`, `Reversion`, `Cierre`; `integraciones/itsm/`; `seguridad/guardia_salida.py`.
- **Agentes:** Documentación.
- **Langfuse:** *scores* `fcr`, `grounded`; *span* `agente_documentacion`.
- **Estimación:** 6 h.

## F6 · Escalamiento a N2 + "hablar con una persona" (R6)

> **Estado (2026-11-19): hecha** (ADR 0010). Nodo Escalar con motivo decidido por código (persona, prohibida ×2, N2
> rechaza, acción fallida, verificación negativa, hardware, límite), ficha §7.2 desde el estado, ANS, botón fijo activo,
> Consola N2 (lista, tomar, evaluar → *score* `escalamiento_completo`). Esc. 5, 8 y 9 cubiertos; esc. 10 depende de F3.

- **Criterios de aceptación:**
  1. Ficha N2 desde el estado (§7.2): síntoma (usuario + normalizado), telemetría, hipótesis probadas/descartadas con evidencia, acciones, banderas, siguiente paso sugerido y ANS (`config/ans.yaml`).
  2. "Hablar con una persona" escala **de inmediato** desde cualquier estado (botón e intención escrita), sin retener.
  3. Usuario confundido: simplifica primero; si pide persona, escala con la causa ya confirmada (esc. 9).
  4. El usuario recibe el plazo (ANS) explícito.
  5. N2 puede marcar "¿Podrías continuar sin repreguntar?" (meta 100 %).
- **Escenarios:** 5, 8, 9, 10.
- **Frontend:** bandeja "Escalamientos" con ficha completa en Consola N2; botón fijo activo.
- **Backend:** nodo `Escalar` + interrupción global; endpoint `/api/casos/{id}/humano`.
- **Agentes:** Escalamiento y Documentación, Conversacional (adaptación de nivel).
- **Langfuse:** *score* humano `escalamiento_completo` (cola de anotación).
- **Estimación:** 8 h.

## F7 · Módulo B: capturas (R8)

- **Criterios de aceptación:**
  1. Adjuntar imágenes en el chat (PromptInput con adjuntos); saneamiento (tipo, tamaño, sin metadatos).
  2. OCR determinista + modelo de visión **en cuarentena** con esquema cerrado (`aplicacion`, `codigo_error`, `mensaje_resumido`, `contiene_instrucciones`, `fragmento_sospechoso`).
  3. Código anclado; si OCR y visión difieren → `no_concluyente` y se pide confirmación.
  4. Captura con instrucciones → bandera visible, ignorada; el usuario recibe "contiene instrucciones que no sigo".
  5. El Diagnosticador nunca recibe el texto crudo de la imagen.
- **Escenarios:** 12.
- **Frontend:** adjuntos, `Image`, aviso de bandera.
- **Backend:** `seguridad/vision_cuarentena.py`, endpoint de carga.
- **Agentes:** Extractor (variante visión).
- **Langfuse:** *span* `extractor_cuarentena` (visión), *score* `injection_flag`.
- **Estimación:** 8 h.

## F8 · Módulo A: curador de KB + revisor (R7)

- **Criterios de aceptación:**
  1. Lote: agrupa casos resueltos; grupo ≥ k sin artículo = faltante; contradicción o versión vieja = desactualizado.
  2. Borradores con los `case_id` que los respaldan; tickets pasan por la cuarentena.
  3. Nada se publica sin el revisor; "Devolver" exige comentario.
  4. Detecta el faltante y las 2 correcciones sembradas del kit.
- **Escenarios:** 11.
- **Frontend:** vista **Revisor de KB** (Publicar / Devolver).
- **Backend:** `agentes/curador_kb.py` (CLI por lotes), endpoints de propuestas (escritura solo en `conocimiento.propuestas_kb`).
- **Langfuse:** traza del lote, *span* `curador_kb`, cola de anotación.
- **Estimación:** 8 h.

## F9 · Evaluación, métricas y costo

- **Criterios de aceptación:**
  1. Usuario simulado juega los 15+ guiones (proceso aparte, rol `evaluador`).
  2. Datasets `caso5-escenarios` y `caso5-red-team` en Langfuse; experimentos comparables.
  3. Vista **Métricas**: FCR (≥ 70 %), precisión (≥ 90 %), tiempo a diagnóstico p50/p95, preguntas por caso (≤ 3), costo real vs. de referencia por agente, inyecciones resistidas (100 %).
  4. Precios de referencia registrados en Langfuse para los modelos `:free`.
- **Escenarios:** todos.
- **Backend:** `evaluacion/` (fuera del proceso de agentes), endpoint `/api/metricas` (Langfuse API + BD).
- **Estimación:** 10 h.

---

## Siguiente paso recomendado

Con F0 cerrada y `db/CONTRATO_SQL.md` publicado por P2: **F1** (repositorio `org` real +
lectura de telemetría vía Zabbix + compuerta de preguntas), validando el escenario 4.
