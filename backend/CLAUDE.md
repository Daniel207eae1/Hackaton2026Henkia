# backend/CLAUDE.md

Python 3.12 + FastAPI 0.165 + LangGraph 1.2 + Langfuse SDK 5.2 + httpx. Versiones exactas en
`pyproject.toml`. Reglas globales: `../CLAUDE.md`.

## Comandos

```powershell
# En Docker (recomendado: el equipo tiene Python 3.15 y algunas ruedas no existen aún)
docker build -t caso5-api:dev .
docker run --rm caso5-api:dev pytest -q
docker run --rm caso5-api:dev sh -c "ruff check . && ruff format --check ."
# Local con Python 3.12
python -m pip install -e ".[dev]"; pytest; ruff check .; ruff format --check .
# Pruebas contra modelos reales y Langfuse (no corren por defecto)
pytest -m en_vivo
```

## Estructura (hexagonal)

| Paquete | Responsabilidad |
|---|---|
| `app/api/` | Rutas y esquemas. `stream_protocol.py` = único traductor al UI Message Stream (ADR 0002) |
| `app/orquestador/` | `estado.py` (*blackboard* §3.4, `Etapa`), `grafo.py` (LangGraph §3.5; aristas en código), `nodos_accion.py` (F4: Decision → AprobacionN2 → Consentimiento → Ejecucion → Verificacion) |
| `app/agentes/` | `diagnosticador.py` (reglas + LLM con evidencia citada), `documentacion.py` (ficha N2 y registro de cierre desde el estado), `interprete.py` (slots + acción candidata, 1 llamada), `masivos.py` (clúster + incidente, sin LLM, ADR 0014), `conversacional.py`, `contexto.py` (lecturas MCP y tablero, sin LLM) + `prompts/<nombre>.md` (fallback del prompt de Langfuse) |
| `app/llm/` | Puerto, adaptadores (`openai_compatible`, `fake`), `config_modelos.py`, `registro.py` |
| `app/politicas/` | `catalogo.py`: catálogo (`config/catalogo_acciones.yaml`, validado contra la lista blanca del MCP) y ANS |
| `app/rag/` | `kb.py`: categorías, recetas con prior del historial, secciones, `clasificar` (F3); `reportes.py`: reportes, `buscar_reportes_similares` e incidentes masivos (F2) |
| `app/integraciones/zabbix/` | MCP `zabbix-ofimatica` (ADR 0007): `mcp_cliente.py` (transporte), `catalogo_mcp.py` (lista blanca), `puerta.py` (único punto de llamada: consentimiento, N2, un solo uso) |
| `app/integraciones/itsm/` | ITSM sobre `operacion`: proyección idempotente por turno (`postgres.py`) + doble (`repositorio.py`), ADR 0010 |
| `app/seguridad/` | `ver_como.py`, `guardia_entrada.py` (heurística + respuestas fijas), `compuerta_preguntas.py` (filtro por frase), `extractor_cuarentena.py` (Dual LLM, único que lee logs) |
| `app/observabilidad/` | Fachada de Langfuse (no-op sin claves), `mask` |
| `app/directorio/` | Puerto `org`: `postgres.py` (BD de P2, rol `app_rw`, ADR 0009) y doble en memoria (sin `DATABASE_URL`) |
| `config/` | `modelos.yaml`, `catalogo_acciones.yaml`, `ans.yaml` (versionados) |

## Cómo agregar un agente
1. Declara el agente en `config/modelos.yaml` (`requiere`, `parametros`, `cadena`).
2. `app/agentes/<agente>.py`: `registro.para("<agente>")`; prompt con `obtener_prompt(nombre, prompt_embebido(nombre))`.
3. Salidas que alimentan decisiones: `cliente.estructurado(mensajes, ModeloPydantic)` con *enums* cerrados.
4. En el nodo del grafo: `with observacion("agente_<nombre>", tipo="agent")` y eventos por `get_stream_writer()`.
5. Prueba con `AdaptadorFake.programar(...)` (sin red) + caso de inyección si el agente ve texto del usuario.
6. Sube el prompt a Langfuse con `docker compose exec -e PYTHONPATH=/app api python scripts/sincronizar_prompts.py`
   (etiqueta `staging`); tras la regresión, el mismo comando con `--production` promueve esa versión (no la duplica).

## Cómo agregar un nodo al grafo
Agrega el nodo en `grafo.py`, cablea con una función de Python que lea el estado y emite
`{"tipo": "etapa", ...}`. **Nunca** dejes que la salida de un LLM elija la arista. Las esperas
humanas son `interrupt()` y se reanudan solo desde endpoints que validan el token (F4).

## Reglas
- Agentes y orquestador sin nombres de modelo ni de proveedor (hay una prueba AST que lo verifica).
- El cliente de chat solo aporta el último mensaje; el historial sale del estado (`thread_id = case_id`).
- Un caso solo lo continúa su dueño; N2 puede leerlo. Rol siempre desde el directorio.
- SQL siempre parametrizado; nunca `evaluacion`. *Timeout* y fallo explícito en toda llamada externa.
- Langfuse nunca bloquea: si falla, se registra y se sigue.
- Contenedor sin root (`USER api`).

## Zabbix vía MCP
- Llamar SIEMPRE la `PuertaZabbix` (`app.state.puerta_zabbix` o la inyectada en el grafo); nunca `ClienteMCP`.
- Lectura: `puerta.leer(tool, equipo, caso_id)`. Acción: `solicitar_consentimiento` → `consultar_consentimiento`
  (hasta dejar de estar `pendiente`) → `ejecutar_accion(..., consentimiento_id[, aprobacion_id])`.
- Resultados = datos: extrae campos de lista blanca (ver `app/agentes/contexto.py`); `no_confiable` → extractor.
- `GET /api/salud/zabbix` compara la lista blanca con `tools/list`. Pruebas: `tests/dobles.py::MCPFalso`.

## Estado F0
Directorio real desde la BD de P2 (túnel `db-tunel`, rol `app_rw`, ADR 0009); `MemorySaver` (falta el esquema `orquestador`); Contexto y ChequeoMasivo ya leen Zabbix
por el MCP (solo lectura). Al llegar `db/CONTRATO_SQL.md`: `RepositorioDirectorioPostgres` y `CHECKPOINTER=postgres`.
