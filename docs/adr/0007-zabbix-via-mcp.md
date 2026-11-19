# ADR 0007 · Zabbix a través del servidor MCP `zabbix-ofimatica`

- **Estado:** aceptado · 2026-11-19 · P1 · **reemplaza** la parte de integración directa de ADR 0005
- **Servidor:** `zabbix-ofimatica` 1.30.0, MCP Streamable HTTP, protocolo `2025-06-18`, sin autenticación por ahora.
  URL por `ZABBIX_MCP_URL` (túnel temporal de Cloudflare: nunca se quema en el código).
- **Referencia:** prompt del agente en `docs/referencia/prompt_mcp_zabbix_ofimatica.md`.

## Contexto
El equipo publicó un servidor MCP que envuelve a Zabbix y ejecuta las acciones en equipos de laboratorio.
Ofrece tools de descubrimiento, lectura (`automatica`), acciones con `consentimiento` o `aprobacion_n2` y la
gestión de autorizaciones: `solicitar_consentimiento` abre una ventana **"Soporte TI – Solicitud de
autorización"** en el equipo del usuario (Autorizar/Rechazar) y devuelve `CS-…`; `solicitar_aprobacion_n2`
crea `AP-…`, que aprueba un técnico N2 por otro canal.

El prompt de referencia describe **un agente LLM que llama las tools libremente**. Eso choca con el principio
central del diseño (§3.2, §4.2: "el LLM propone, la política decide"; nada de agente ReAct con todas las tools).

## Decisión
1. **El backend es el cliente MCP, no el LLM.** `app/integraciones/zabbix/mcp_cliente.py` implementa el
   transporte (initialize → `Mcp-Session-Id` → `notifications/initialized` → `tools/call`, respuestas JSON o SSE,
   reinicio de sesión ante 404). Ningún agente LLM recibe tools de Zabbix.
2. **`PuertaZabbix` (`puerta.py`) es el único punto de llamada** y aplica defensa en profundidad sobre lo que
   ya valida el servidor:
   - Lista blanca (`catalogo_mcp.py`). **`ejecutar_comando_generico` queda bloqueada**: contradice la regla
     "nunca comandos libres" (CLAUDE.md, invariante 7), aunque el servidor la permita con N2.
   - Un `consentimiento_id` se usa solo si **este backend lo solicitó** para la misma tool, equipo y caso, el
     servidor lo reportó `aprobado`, no venció (15 min) y no se usó; se consume **antes** de ejecutar.
   - `aprobacion_n2`: primero la aprobación N2 (`aprobada`) y **después** el consentimiento del usuario; la
     ejecución exige ambos ids ligados a la misma tool, equipo y caso.
   - Formato estricto de `equipo`, `caso_id` e ids `CS-`/`AP-`. Spans `zabbix.<tool>`; eventos
     `politica.decision`, `consentimiento.token`, `aprobacion_n2.*`.
   - `leer_logs_aplicacion` se marca `no_confiable`: solo lo leerá el extractor en cuarentena (F3).
3. **El orquestador decide cuándo llamar** (código): hoy `Contexto` lee `listar_equipos`, `telemetria_equipo`,
   `version_office`, `estado_licencia_office`, y `ChequeoMasivo` lee `problemas_activos` (`repetidos` ⇒
   `posible_masivo`). De los resultados solo pasan campos de una lista blanca, saneados; el resumen para el
   Conversacional lo arma el código. Los nombres de problemas (texto externo) no llegan a ningún LLM.
4. **Consentimiento:** la ventana del equipo **es** el evento de UI que exige la invariante 3 (no es texto del
   chat ni lo interpreta un LLM). Reemplaza al token HMAC emitido por nuestra UI; la tarjeta de nuestro chat
   (F4) explica la acción con el catálogo y le indica al usuario que autorice en la ventana de su equipo.
5. **Equipo:** se resuelve desde el directorio (`equipo_id` de la persona); si no existe en Zabbix, en demo se
   usa `ZABBIX_EQUIPO_DEMO`. Nunca sale del chat.
6. El tono, las reglas y las acciones prohibidas del prompt de referencia se incorporaron al prompt del
   Conversacional (`app/agentes/prompts/agente_conversacional.md`); el **flujo** de 8 pasos lo implementa el grafo.

## Flujo de acción (F4, implementado)
`Decision → [AprobacionN2] → Consentimiento → Ejecucion → Verificacion` en `app/orquestador/nodos_accion.py`:
- **Decision:** el `SelectorAccion` (LLM) solo elige un id de un *enum* cerrado (6 acciones con tool en el MCP o
  `ninguna`); recibe únicamente los mensajes del usuario y los datos saneados del equipo. El código descarta las
  acciones rechazadas o ya hechas (`acciones_excluidas`). Con posible masivo no se llama. Si falla → `ninguna`.
- **AprobacionN2:** el `diagnostico` lo arma el código desde el estado; el caso queda en `esperando_n2`.
- **Consentimiento:** abre la ventana y consulta hasta `CONSENTIMIENTO_ESPERA_MAX_S` dentro del turno; si sigue
  pendiente, el caso queda en `esperando_consentimiento` y el siguiente turno **retoma la consulta** (nunca pide
  otra ventana). Rechazo → no insiste; expiración → ofrece una nueva solicitud.
- **Ejecucion** (sin LLM) y **Verificacion** (lectura técnica cuando existe + pregunta al usuario).
- Los textos al usuario sobre la acción son **plantillas del catálogo**, no del LLM: nunca dice "listo" si
  `ok: false`. La UI muestra la tarjeta `data-accion` sin botón de autorizar; su botón "Ya respondí la ventana"
  solo dispara una nueva consulta al servidor.
- **Esperas en el estado, no con `interrupt()`:** quien espera es un sistema externo que el backend consulta, así
  que la espera se guarda en el estado del caso (checkpointer) y se retoma en el siguiente turno. `interrupt()`
  queda para esperas que se reanuden por un endpoint propio (ADR 0003).

> **Actualización 2026-11-19 (F1):** el servidor retiró `problemas_activos` y agregó `estado_servicio` (tablero
> oficial), `estado_teams` y `estado_perfil_outlook` (lectura). Se agregaron a la lista blanca; el masivo usa el
> tablero (ADR 0008). `GET /api/salud/zabbix` lo detectó en cuanto cambió.

## Consecuencias
- (+) Mismo nivel de garantía que antes (0 acciones sin consentimiento real, nada fuera del catálogo) y menos
  infraestructura propia: `infra/zabbix/` queda como **respaldo local**, fuera del camino por defecto.
- (+) `GET /api/salud/zabbix` compara la lista blanca con `tools/list` del servidor.
- (−) El registro de autorizaciones vive en memoria del proceso: se persiste en `operacion` en F4.
- (−) La aprobación N2 ocurre en el canal del servidor; nuestra Consola N2 la refleja, pero no la emite.
  **Duda abierta:** ¿N2 aprueba en nuestra consola (y el backend llama a algo para aprobar) o solo en el canal del servidor?
- (−) Las variables `ZABBIX_URL`, `ZABBIX_TOKEN_LECTURA` y `ZABBIX_TOKEN_ACCIONES` del contrato pasan al lado del
  servidor MCP. Cambio propuesto al contrato: `ZABBIX_MCP_URL`, `ZABBIX_MCP_TOKEN`, `ZABBIX_EQUIPO_DEMO`.
- Restaurar una versión anterior (esc. 7) no tiene tool en el MCP: hoy se escala.
