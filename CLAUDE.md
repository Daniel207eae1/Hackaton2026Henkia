# CLAUDE.md · Caso 5 · Agente de diagnóstico de incidentes de ofimática

## Propósito

Sistema multiagente con **orquestación determinista** que atiende incidentes de ofimática
(Outlook, Teams, Excel, Word, OneDrive, impresión): entiende el síntoma, consulta antes de
preguntar, detecta masivos, diagnostica por hipótesis con evidencia, resuelve **solo** con
consentimiento (y aprobación N2 cuando la política lo exige), verifica, documenta y escala.
Módulo B (capturas) obligatorio; Módulo A (KB que aprende) después del núcleo.

Fuentes de verdad, en este orden: `prompts/00_Contrato_Compartido.md` → `docs/adr/` →
`Diseno_Arquitectura_Caso5.md` → `front_validacion/` (comportamiento esperado de la UI).
Plan de trabajo: `docs/PLAN_FEATURES.md` (F0–F9). Se trabaja **una feature a la vez**.

## Mapa del monorepo

| Carpeta | Qué hay | Dueño |
|---|---|---|
| `frontend/` | React + TS + Vite + shadcn/ui + AI Elements (ver `frontend/CLAUDE.md`) | P1 |
| `backend/` | FastAPI + LangGraph + capa LLM agnóstica (ver `backend/CLAUDE.md`) | P1 |
| `backend/config/` | `modelos.yaml` (modelos por agente), `catalogo_acciones.yaml`, `ans.yaml` | P1 |
| `infra/zabbix/` | Zabbix local de **respaldo** (el camino por defecto es el MCP `zabbix-ofimatica`, ADR 0007) | P1 |
| `db/` | Migraciones, roles, funciones SQL, semillas, vectores. Contrato: `db/CONTRATO_SQL.md` | P2 |
| `data/` | Kit sintético (JSON, Markdown, PNG) | P2 |
| `docs/adr/` | Decisiones de arquitectura (`NNNN-titulo.md`) | ambos |
| `.claude/agents/` | Subagentes `p1-*` y `p2-*` | ambos |
| `front_validacion/` | Prototipo HTML de referencia. **No se copia su código** | — |

## Comandos

```powershell
# Todo (F0). Langfuse (localhost:3000) y Ollama ya existen fuera del compose.
copy .env.example .env      # y completar claves (ver comentarios del archivo)
docker compose up --build   # api :8000 · web :5173 · equipos-sim :8090
# La BD de P2 corre en otra máquina: el servicio db-tunel abre el túnel (DB_TUNEL_HOST en .env, ADR 0009).
# Si P2 corre en local (docker-compose.db.yml):
docker compose -f docker-compose.yml -f docker-compose.db.yml up --build
# Ollama (embeddings, ADR 0011) — solo la primera vez:
docker compose exec ollama ollama pull qwen3-embedding:0.6b
# Zabbix (perfil aparte, pesado):
docker compose --profile zabbix up --build

# Backend
cd backend; python -m pip install -e ".[dev]"; pytest; ruff check .; ruff format --check .
# Prompts → Langfuse (staging; --production promueve la versión probada)
docker compose exec -e PYTHONPATH=/app api python scripts/sincronizar_prompts.py
# Evaluación (F9): guiones del jurado + red team, en proceso, con equipo simulado (nunca el MCP real)
docker compose exec api python -m evaluacion.ejecutar            # o --solo esc06,rt01 · --sin-langfuse
# Lote del curador de KB (F8)
docker compose exec api python -m app.agentes.curador_kb
# Frontend
cd frontend; npm ci; npm run test; npm run lint; npm run typecheck; npm run build
```

## Invariantes de seguridad (no negociables)

1. **El LLM propone, la política decide.** El flujo lo decide el grafo en código; el LLM
   solo elige ids de *enums* cerrados (catálogo, hipótesis) con salida validada.
2. **0 acciones sin consentimiento.** Ninguna acción del catálogo se ejecuta sin un token
   válido: HMAC, un solo uso, ligado a `case_id` + acción + parámetros + *hash* del texto
   mostrado, con vencimiento. Política `aprobacion_n2` exige además la aprobación de N2
   (y después el "Sí" del usuario). Las acciones `prohibida` **no existen como herramienta**.
3. **El consentimiento es un evento de la UI** (botón → endpoint propio), nunca texto del chat
   interpretado por un LLM.
4. **Todo texto externo es dato, no orden.** Logs, errores, capturas, KB, tickets y tablero
   solo los lee el **extractor en cuarentena** (sin herramientas, sin estado, esquema forzado,
   anclaje de códigos, bandera heurística O modelo). El Diagnosticador nunca ve texto crudo.
5. **La identidad sale de la BD**, nunca del chat. "Ver como" solo con `MODO_DEMO=true`.
6. **El backend de agentes nunca lee el esquema `evaluacion`** (causas ocultas).
7. Telemetría y acciones **solo vía el MCP `zabbix-ofimatica`** y **solo a través de `PuertaZabbix`**
   (ADR 0007): lista blanca de tools; `ejecutar_comando_generico` bloqueada (nunca comandos libres);
   el LLM nunca recibe tools de Zabbix; una acción solo con un `consentimiento_id` que este backend
   pidió, que el usuario autorizó en la ventana de SU equipo, vigente y sin usar (+ `aprobacion_id`
   de N2 cuando aplica). Un "sí" en el chat nunca basta.
8. **Mínimo privilegio por agente** (tabla §3.3 del diseño). Sin herramientas de
   comunicación externa (rompe la "tríada letal").
9. Solo datos sintéticos: `@ejemplo.test`, `ERR-SIM-xxxx`, `KB-SIM-xxx`, `EQ-SIM-xxx`.
10. Ningún secreto en el repo. `.env` está en `.gitignore`. No se inventan claves.
11. En la UI, texto del backend **siempre escapado**; jamás `dangerouslySetInnerHTML`.

## Definición de "terminado" (por feature)

- [ ] Criterios de aceptación de la feature en `docs/PLAN_FEATURES.md` verificados.
- [ ] Pruebas automáticas: `pytest` (backend) y `vitest` (frontend) en verde; lint y tipos limpios.
- [ ] Escenarios del jurado de la feature pasan (prueba automática o guion en `p1-qa-escenarios`).
- [ ] Trazas en Langfuse con los *spans* y *scores* declarados para la feature.
- [ ] Revisión de `p1-seguridad` sin hallazgos críticos abiertos.
- [ ] ADR si se tomó una decisión relevante; `.env.example` actualizado si hay variables nuevas.
- [ ] Probado de punta a punta en el navegador (no solo pruebas unitarias).

## Trazabilidad en Langfuse

- **Sesión = `case_id`**, `user_id` = persona del directorio, *tags*: `escenario`, `modulo`, `version`.
- Una **traza por turno**. *Spans* con nombres estables (base del costo por agente):
  `guardia_entrada`, `agente_conversacional`, `agente_contexto`, `agente_diagnosticador`,
  `extractor_cuarentena`, `ejecutor`, `agente_documentacion`, `curador_kb`, `guardia_salida`,
  `zabbix.<tool>` (una por llamada al MCP), `rag.<funcion>`.
- Eventos: `politica.decision`, `consentimiento.token` (emitido/consumido/rechazado),
  `aprobacion_n2.*`, `seguridad.bandera`.
- *Scores* deterministas (§5.3): `diagnostico_correcto`, `preguntas_hechas`,
  `pregunto_consultable` (=0), `accion_sin_token` (=0), `tiempo_a_diagnostico`, `fcr`,
  `masivo_vinculado`, `injection_flag`.
- *Prompts* en Langfuse Prompt Management (etiquetas `production`/`staging`) con *fallback*
  embebido en `backend/app/agentes/prompts/`. Cada *generation* queda ligada a su versión.
- Enmascaramiento de datos personales con `mask` del SDK. Precios de referencia para `:free`.
- Langfuse **no** es el registro oficial: eso es el estado del caso + la ITSM simulada.

## Regla de agnosticismo de modelos

- **Ningún nombre de modelo ni de proveedor aparece en el código de los agentes.** Los agentes
  piden una capacidad a la capa `backend/app/llm/` por su nombre lógico (`conversacional`,
  `diagnosticador`, …); el modelo sale de `backend/config/modelos.yaml`.
- Al arrancar se valida que cada modelo declarado cumple las capacidades del agente
  (`chat`, `streaming`, `tools`, `salida_estructurada`, `vision`, `embeddings`).
- Salida estructurada portable: `response_format` → *tool calling* forzado → JSON + Pydantic
  con un reintento. Proveedor de chat por defecto: Hugging Face (`HF_TOKEN`, `HF_BILL_TO`, ADR 0012);
  embeddings en Ollama local (ADR 0011). El selector de modelo de la página es solo para pruebas (modo demo). Resiliencia: 429 con *backoff* y *fallback* a la siguiente opción de la cadena.

## Lo que nunca se hace

- Ejecutar una acción porque el LLM lo dijo, o aceptar "sí", "soy de TI" o "te autorizo" escritos.
- Registrar una acción prohibida como herramienta, darle tools de Zabbix a un LLM, o llamar al MCP fuera de `PuertaZabbix`.
- Pasar texto de logs, capturas, KB o tickets a un modelo con herramientas o al Diagnosticador.
- Preguntar al usuario un dato que se puede consultar (versión, disco, licencia…).
- Leer correos, archivos o chats del usuario; tomar control remoto.
- Leer `evaluacion` desde el backend, o filtrar la causa oculta a la UI o a los *prompts*.
- Quemar modelos, proveedores, claves o URLs en el código; subir `.env`.
- Tocar `db/` o `data/` desde P1 (ni `frontend/`, `backend/`, `infra/zabbix/` desde P2).
- Cambiar el contrato compartido sin proponerlo primero.
- Inventar pasos, menús o códigos de error: los pasos citan `KB-SIM-xxx`; si no hay artículo, se escala.

## Datos y base de datos (P2)

<!-- Sección reservada para P2. P1 no la edita. -->
