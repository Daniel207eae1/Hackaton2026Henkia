# ADR 0003 · Orquestador: LangGraph con *checkpointer* en PostgreSQL

- **Estado:** aceptado · 2026-11-19 · P1
- **Versiones:** `langgraph==1.2.23`, `langgraph-checkpoint-postgres==3.2.1`, `psycopg[binary,pool]==3.3.9`.

## Contexto
§3.2 y §3.5 piden un grafo determinista con esperas humanas (consentimiento, aprobación N2) y
persistencia del caso mientras espera. Alternativa: máquina de estados propia.

## Decisión
**LangGraph** (`StateGraph`) con:
- Nodos = estados de §3.5 (`Recepcion`, `Contexto`, `ChequeoMasivo`, `InformarMasivo`, `Aclaracion`,
  `Hipotesis`, `Prueba`, `Decision`, `Guia`, `Consentimiento`, `AprobacionN2`, `Ejecucion`,
  `Verificacion`, `Reversion`, `Cierre`, `Escalar`). Las **aristas condicionales son funciones de
  Python** sobre el estado; el LLM nunca elige la siguiente arista.
- Esperas con `interrupt()`; reanudación con `Command(resume=...)` **solo** desde los endpoints de
  consentimiento/aprobación, que validan el token antes.
- Progreso hacia la UI con `get_stream_writer()` + `stream_mode=["custom", ...]`.
- `thread_id = case_id`.
- *Checkpointer*: `AsyncPostgresSaver` (conexiones con `autocommit=True`, `row_factory=dict_row`)
  en el esquema propuesto `orquestador`. **Mientras P2 no entregue la BD**, `MemorySaver`
  (variable `CHECKPOINTER=memoria|postgres`).
- El estado del caso de LangGraph es el *blackboard* de §3.4; además se proyecta a
  `operacion.casos` (JSONB + columnas clave) para N2, auditoría e ITSM.

> **Actualización (F4, ADR 0007):** el consentimiento y la aprobación N2 los resuelve el servidor MCP; sus esperas
> se guardan en el estado del caso y se retoman en el siguiente turno, sin `interrupt()`.

## Consecuencias
- (+) `interrupt` + *checkpointer* resuelven las esperas largas (N2) sin código propio.
- (−) Curva de aprendizaje; reglas de `interrupt` (no envolver en `try` genérico, orden fijo).
- En Windows nativo `psycopg` async exige `WindowsSelectorEventLoopPolicy`; se corre en Docker (Linux).
