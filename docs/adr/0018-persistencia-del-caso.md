# ADR 0018 · Persistencia del caso: rehidratar el grafo desde el registro ITSM

- **Estado:** aceptado · 2026-11-19 · P1

## Contexto
El grafo usa `MemorySaver`: si la API se reinicia (despliegue, recarga en caliente, caída), los casos abiertos se
pierden. Durante el día pasó varias veces. `AsyncPostgresSaver` crea sus propias tablas, lo que exige un esquema
nuevo (`orquestador`) en la BD de P2, es decir, un cambio al contrato compartido que primero hay que proponer.

## Decisión
Usar lo que el contrato ya ofrece:
- **Origen:** `operacion.casos.estado_caso` (JSONB, versionado por trigger en `casos_estado_versiones`) más
  `operacion.mensajes`. La proyección ITSM ya los escribe de forma idempotente al final de **cada** turno (ADR 0010).
- **Cuándo se rehidrata:** cuando el grafo no tiene el caso en memoria. `_estado_del_caso` lo carga del registro
  (`cargar_estado`) y lo restaura con `aupdate_state(..., as_node="CasoTerminado")`. Así queda como un turno
  terminado, sin nada pendiente, y el siguiente mensaje entra por Recepción. También emite el evento Langfuse
  `caso.rehidratado`.
- **Qué entra al historial:** los mensajes salen de `operacion.mensajes`. Son los del historial de los agentes, que
  nunca llevan texto externo (mensaje oficial y resumen de capturas excluidos), así que no se abre ningún camino de
  inyección.
- **Seguridad:** se mantiene igual.
  - El dueño del caso sale del estado rehidratado (`persona_id`), así que un caso ajeno sigue respondiendo 403.
  - **`case_id` canónico** (revisión de seguridad): solo 32 hex en minúscula se leen como UUID; cualquier otra forma
    (mayúsculas, guiones, llaves) va por `uuid5`. Así dos ids distintos nunca caen en el mismo registro. El upsert
    de `operacion.casos` solo actualiza si el `usuario_id` coincide (si no, la proyección falla sin tocar nada), y un
    caso ajeno no se rehidrata en el grafo: solo se lee su dueño para responder 403.
  - Una autorización pendiente antes del reinicio no se reutiliza: `PuertaZabbix` perdió su registro y el flujo la
    trata como expirada.

## Consecuencias
- Un reinicio ya no pierde casos. Probado en vivo con la BD de P2: un caso vinculado a `INC-SIM-0001` siguió en el
  turno 2 tras `docker compose restart api`. Hay 3 pruebas automáticas: continuidad del caso con su historial,
  caso escalado que sigue cerrado y caso desconocido.
- **Granularidad:** se pierde, como mucho, el turno que estaba en curso durante el reinicio.
- **Sin BD:** el ITSM en memoria se pierde con el proceso, así que los casos empiezan de cero, igual que antes.
- **El navegador no recupera el historial visual** si se recarga la página: `useChat` vive en memoria del cliente.
  El backend sí conserva el caso y su auditoría.
- **Evolución:** si P2 concede el esquema `orquestador`, `CHECKPOINTER=postgres` (`AsyncPostgresSaver`) da
  persistencia a mitad de turno sin cambiar el resto.
