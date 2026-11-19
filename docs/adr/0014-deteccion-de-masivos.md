# ADR 0014 · Detección de masivos: clúster semántico + incidente oficial + propuesta a N2 (F2)

- **Estado:** aceptado · 2026-11-19 · P1

## Contexto
§3.11 y R3: antes de cualquier hipótesis hay que saber si el síntoma es parte de un incidente general. Hay dos
fuentes: el tablero del MCP (`estado_servicio`) y la BD de P2 (`operacion.reportes`, `buscar_reportes_similares`,
`incidentes_masivos`, `incidente_casos`). El kit trae dos escenarios: 3 (correo, con `INC-SIM-0001` publicado) y 3b
(Teams, reportes sin incidente oficial).

## Decisiones
1. **Agente Masivos sin LLM** (`agentes/masivos.py`). El nodo `ChequeoMasivo` corre **antes** de `Hipotesis` y en este
   orden: (a) tablero del MCP; si confirma, se cita y se termina; (b) clúster. El clúster espera a que el intérprete
   entienda app + síntoma: el texto canónico los necesita.
2. **Texto canónico = `app · síntoma · texto`**, el mismo formato con que P2 embebió los reportes. Coseno 1,0 contra
   el vector guardado; 0,96 con el texto crudo. Mismo modelo que F3 (`qwen3-embedding:0.6b` en Ollama, ADR 0011).
3. **Categoría:** la tabla del intérprete o, si no alcanza, `conocimiento.clasificar` con el mismo vector, con las
   reglas de F3 (umbral 0,70 y margen 0,05).
4. **Regla (en código):**
   - Si hay un incidente `publicado` de la categoría → `masivo_confirmado`.
   - Si no, y hay ≥ k usuarios **distintos de quien reporta** con similitud ≥ umbral dentro de la ventana →
     `posible_masivo`. El caso se une a la propuesta abierta o se crea una (`propuesto`, origen `cluster_reportes`,
     `regla_disparo` con k, umbral, ventana, usuarios y reportes).
   - Si no → diagnóstico individual.
   - Parámetros: `MASIVO_MIN_EQUIPOS` (k=3), `MASIVO_UMBRAL` (0,75, el valor por defecto de P2) y
     `MASIVO_VENTANA_MIN` (60).
5. **Cero pasos individuales** mientras el caso es `posible_masivo` o `masivo_confirmado`: el diagnóstico no aplica y
   `Decision` descarta las acciones. El aviso al usuario es una **plantilla del código**. El mensaje oficial se cita
   **tal cual con su hora**, pasa por la guardia (`mensaje_seguro`) y **nunca** entra a un LLM.
6. **N2 decide** (`/api/n2/masivos/{id}/confirmar|descartar|resolver`, solo rol N2):
   - **Confirmar** exige un mensaje oficial (15–500 caracteres, sin instrucciones ni caracteres de control) →
     `publicado`.
   - **Descartar** → los casos vinculados siguen con el diagnóstico individual (`descartado_n2`).
   - **Resolver** → `notificado_en` en los vinculados.
7. **Seguimiento** (nodo `InformarMasivo`, cada turno de un caso vinculado) lee el incidente:
   - `publicado` → cita la confirmación de N2.
   - `descartado` → diagnóstico individual.
   - `resuelto` → «¿Ya te funciona?»: con «sí» → `Cierre` (solución = el incidente); con «no» → `resuelto_persiste`
     y diagnóstico individual.
   
   La UI consulta `GET /api/casos/{id}/masivo` cada 15 s y muestra los botones Sí/No sin que el usuario escriba.
8. **Registro:** la proyección ITSM liga `reportes.caso_id` e inserta `incidente_casos` (suscrito, regla, `verificado_en`).
   `posible_masivo` → caso en `chequeo_masivo`; confirmado → `vinculado_masivo`.
9. **Reloj de demostración** (`MASIVO_RELOJ_DEMO`, solo con `MODO_DEMO`): los reportes del kit son del 17 y del 19 a la
   mañana. Con `2026-11-19T09:00:00-05:00` y ventana de 2880 min se reproducen 3 y 3b. El reporte propio se fecha
   justo antes de ese «ahora», con una fracción de segundo distinta, para no chocar con `reportes_unicidad`.

## Verificación en vivo (2026-11-19, BD de P2 + MCP + Hugging Face + Ollama)
| Escenario | Resultado |
|---|---|
| 3 · Lorena (USR-003) «el Outlook no me descarga correos» | `INC-SIM-0001` publicado → cita del mensaje oficial (19/11 08:10), sin hipótesis ni acciones; caso `vinculado_masivo` |
| 3b · Hugo (USR-004) «en Teams no me cargan los mensajes» | 6 usuarios distintos ≥ 0,75 → propuesta `INC-SIM-0003`; N2 confirma con mensaje → cita; N2 resuelve → «¿Ya te funciona?» → «sí» → cierre (`incidente_casos` notificado y verificado) |
| Navegador | Bandeja «Posibles masivos» (confirmar desde la UI: `INC-SIM-0004`); tarjeta en el chat; el panel lateral pasa a «se resolvió» solo y el «Sí» cierra el caso |

## Revisión de seguridad (p1-seguridad), ya corregido
- **Alto:** la plantilla que cita el mensaje oficial se guardaba en `mensajes` y llegaba al conversacional en el turno
  siguiente. Ahora en el historial va «[citado en la tarjeta]», y el usuario sigue viendo la cita completa. Hay una
  prueba que revisa lo que recibe el LLM.
- **Medio:** el número de usuarios distintos se calcula en el backend con `usuario_id` y excluye al propio usuario, en
  vez de tomar el conteo que devuelve la función de P2.
- **Bajo:** el texto del reporte se guarda enmascarado (correos y rutas con el usuario).
- **Abiertos (bajos):**
  - `resolver` no guarda quién resolvió (falta columna en P2; queda en Langfuse).
  - Dos casos simultáneos pueden crear dos propuestas para la misma categoría (sugerir a P2 un índice único parcial).
  - Una acción ya pendiente antes de vincular el caso a un masivo: hoy no puede ocurrir, porque mientras hay una
    espera no se pasa por `ChequeoMasivo`.

## Consecuencias y pendientes
- **Para P2:** la semilla inserta `INC-SIM-0001` con id explícito sin avanzar `operacion.incidentes_seq`. El backend
  reintenta con el siguiente valor (en *savepoints*), pero conviene un `setval` en la semilla.
- Las pruebas en vivo dejaron `INC-SIM-0002..0004` (`origen=cluster_reportes`) y algunos reportes en la BD compartida.
- Solo las apps con servicio compartido (`correo`, `teams`, `nube`) forman clúster: `incidentes_masivos.servicio_id`
  es obligatorio. Impresión y Office local siguen el diagnóstico individual.
- El aviso «en vivo» es por consulta periódica, no por *push*. Con `MemorySaver`, un reinicio de la API pierde el caso
  (pendiente: *checkpointer* en el esquema `orquestador`).
- Calibración de k / umbral / ventana con el reporte de P2 y un experimento en Langfuse (F9).
