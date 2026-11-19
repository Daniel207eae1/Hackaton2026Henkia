# ADR 0001 · Contradicciones entre fuentes y cómo se resuelven

- **Estado:** aceptado · 2026-11-19 · P1
- **Fuentes:** `prompts/00_Contrato_Compartido.md` (prevalece), `Diseno_Arquitectura_Caso5.md`, `front_validacion/LEEME.md`, prompt P1.

| # | Contradicción | Decisión |
|---|---|---|
| 1 | §7.1 del diseño recomienda **Chainlit**; el contrato fija React + shadcn/ui + AI Elements. | Contrato. Chainlit queda descartado. |
| 2 | §3.3 habla de un "agente de equipo simulado"/API propia; el contrato fija **Zabbix** para telemetría y acciones. | Zabbix + `equipos-sim` detrás de *scripts webhook* (ADR 0005). |
| 3 | §2.2 y §7.2: "riesgo medio ⇒ aprobación N2"; §3.6 asigna la política **por acción**. | La política es **por acción** (catálogo). Riesgo medio no implica N2 (`reparacion_rapida_office` y `restaurar_version_anterior` solo piden consentimiento). |
| 4 | §3.5: verificación fallida → Reversión → Escalar; §8 (esc. 1): si falla la reparación rápida se pide aprobación N2 para recrear el perfil. | El grafo admite `Verificacion → Decision` cuando la hipótesis sigue confirmada y queda otra acción en la receta; si no, `Reversion → Escalar`. |
| 5 | Prompt P1 cita "SDK de Langfuse v3"; la versión vigente es **5.2.0** (compatible con el servidor 4.83). | Se fija `langfuse==5.2.0` (API `start_as_current_observation` + `propagate_attributes`). |
| 6 | Prompt P1 lista los componentes "Actions" y "Loader" de AI Elements; en la versión vigente las acciones son `MessageActions` dentro de `message` y no hay `loader` (hay `shimmer`). Además AI Elements anuncia su paso a shadcn/ui a fines de noviembre de 2026. | Se usan los componentes vigentes; el código se copia al repo, así que la deprecación no rompe nada (ADR 0002). |
| 7 | El diseño menciona `qwen3.5:4b` y `bge-m3`; el contrato fija `qwen3-embedding:0.6b` para *embeddings*. | Contrato para *embeddings*; los demás modelos se declaran en `backend/config/modelos.yaml`, no en código. |
| 8 | Tipos de síntoma: el diseño lista 6; el prototipo agrega `sin_audio`, `archivo_sobrescrito`, `bloqueo_seguridad`, `no_edita`. | El *enum* del estado incluye los 10. P2 debe usar los mismos (propuesto al contrato). |
| 9 | Escenario 5 (licencia): el prototipo escala; `asignar_licencia` es `aprobacion_n2`. | Se mantiene el **escalamiento** (N2 asigna la licencia en su consola, no el Ejecutor). Duda abierta para la mesa de servicio. |
| 10 | §4.3 ofrece escalar "al segundo intento" de acción prohibida; el prototipo lo ofrece desde el primero. | Plantilla del catálogo (ofrece desde el primero) + bandera de insistencia desde el segundo. |
| 11 | El contrato no define dónde viven las tablas del *checkpointer* de LangGraph. | Se propone un esquema `orquestador` (propiedad de `app_rw`). Mientras P2 no lo cree, F0 usa `MemorySaver` (ADR 0003). |

## Consecuencias
Cambios propuestos al contrato (no aplicados): filas 8 y 11.
