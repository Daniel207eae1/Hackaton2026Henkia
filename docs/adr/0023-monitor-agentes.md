# ADR 0023 · Monitor de agentes en tiempo real

- **Estado:** aceptado · 2026-11-20 · P1

## Contexto
Para la demo ante el jurado, y para que N2 vea qué está haciendo el sistema, se pidió una pantalla que muestre **en
vivo** qué nodos del grafo y qué agentes se activan mientras se atiende un caso. El sistema ya está probado de punta a
punta, así que la condición principal es **no dañar nada**: si el monitor falla, el chat sigue igual (como pasa con
Langfuse).

Todos los agentes ya pasan por `observacion()` (`app/observabilidad/langfuse.py`), y cada nodo emite
`{"tipo": "etapa"}` con `get_stream_writer()`, que `/api/chat` ya lee.

## Decisión
- **Bus de eventos en memoria** (`app/observabilidad/monitor.py`), pub/sub dentro del proceso:
  - Cada suscriptor tiene una `asyncio.Queue` con tope de 500 eventos. **Si se llena, el evento se descarta**: publicar
    nunca bloquea ni espera.
  - Admite como máximo 20 suscriptores. Al desconectarse un cliente, su cola se elimina.
  - `publicar()` nunca lanza excepciones y, sin suscriptores, sale en la primera línea.
  - Un `ContextVar` lleva el `case_id` del turno. LangGraph crea las tareas de los nodos dentro de `astream`, que
    heredan el contexto.
  - Si alguien publica desde otro hilo, el evento se entrega con `call_soon_threadsafe` en el bucle del suscriptor.
  - `MONITOR_ACTIVO=false`: no publica nada y `/api/monitor/*` responde 404 a todos.
- **Eventos (solo metadatos):**
  - `agente_inicio` / `agente_fin`: con `agente`, `tipo_observacion`, `duracion_ms` y `error`. Se publican desde
    `observacion()`, con y sin Langfuse.
  - `etapa`: el nodo activo.
  - `turno_inicio` / `turno_fin`: con `etapa_final`, `traza_url` y `error`. Salen de `/api/chat`.
  - Todos llevan `caso`, `ts` (epoch en ms) y un `seq` incremental.
  - Los nombres pasan por una lista de caracteres permitidos (`[A-Za-z0-9_.:-]`, máx. 80). **Nunca** van el texto del
    usuario, respuestas del LLM, `input`/`output` de observaciones, logs, capturas, parámetros ni tokens. Hay una
    prueba con un marcador único que lo verifica.
- **Cambios mínimos en el código existente.**
  - `observacion()` envuelve su `yield` en `try/except BaseException/finally`. No cambian su firma, lo que hace con
    Langfuse ni el valor del `yield`. La excepción del llamador se vuelve a lanzar con un `raise` sin argumentos, así
    que es la misma instancia, y Langfuse la sigue viendo.
  - `/api/chat` solo añade líneas. Lo que recibe la UI del chat es idéntico; hay una prueba de regresión que lo compara.
- **Endpoints** (`app/api/monitor.py`, en un router aparte):
  - `GET /api/monitor/grafo`: nodos y aristas generados con `get_graph()`, no escritos a mano. Así un nodo nuevo
    aparece solo.
  - `GET /api/monitor/stream`: SSE propio (`data: {json}\n\n`), con un latido `: ping` cada 15 s para que proxies y
    túneles no corten la conexión.
    - **No** usa el UI Message Stream del chat (ADR 0002): es otro contrato.
    - La cola se crea al empezar a emitir y se elimina en un `finally`, también cuando Starlette cancela la tarea al
      desconectarse el cliente.
  - Ambos exigen rol N2 o revisor KB (el colaborador recibe 403).
  - El stream admite 30 aperturas por persona y minuto (`LimiteTasa`) y responde 503 si no quedan cupos.
- **Frontend:**
  - La vista `/monitor` se conecta con `fetch` + `ReadableStream`. `EventSource` no admite cabeceras, y la identidad
    viaja en `X-Ver-Como`, nunca en la *query string*.
  - Se reconecta con *backoff* exponencial hasta 15 s. 401, 403 y 404 no se reintentan.
  - El estado se calcula con un reductor puro.
  - El diagrama usa `@xyflow/react@12.12.1`, con versión exacta y cargado con `React.lazy` en su propio chunk (159 kB).
    Las posiciones son un mapa fijo por etapa; un nodo desconocido cae en una cuadrícula.

## Alternativas descartadas
- **Consultar la API de Langfuse.** Las trazas llegan en lote (*flush*) con segundos de retraso, necesitaría las
  claves en otra ruta del backend y Langfuse puede no estar configurado. No sirve para «en vivo».
- **Reutilizar el stream del chat.** Solo lo ve el dueño del caso, y mezclar contratos rompe el aislamiento del ADR 0002.
- **Redis o un servicio nuevo.** Es más infraestructura para un solo proceso. Con varias réplicas se usaría
  `LISTEN/NOTIFY` de Postgres, que ya existe.
- **`EventSource`**: no permite la cabecera `X-Ver-Como`, y poner la identidad en la URL la dejaría en logs e historial.

## Límites
- **Un proceso.** Con varias réplicas de la API, cada monitor ve solo los turnos de su réplica (ver
  `LISTEN/NOTIFY` arriba).
- **Sin historial.** El monitor muestra lo que ocurre mientras está abierto. Al recargar, se pierde lo anterior.
- **El curador de KB no tiene caso.** Sus eventos (y los de las llamadas a modelos que hace) llegan con `caso = null`
  al carril «Procesos de fondo».
- **Orden entre agente y etapa.** Los eventos de agente se publican de forma síncrona y la `etapa` llega por el stream
  de LangGraph. Por eso, dentro de un mismo nodo, la línea de tiempo puede mostrar el agente unos milisegundos antes
  de que se encienda el nodo.
- **Consentimiento.** No usa `interrupt()` (ADR 0003, actualización F4): el estado «en espera» se muestra mientras el
  nodo `Consentimiento` o `AprobacionN2` está activo, y se mantiene si el turno termina en él.
- **Costo** (300 turnos con LLM fake, mediana):

  | Medición | Mediana por turno |
  |---|---|
  | Base `7fbb64d` | 21,1 ms |
  | Rama, sin monitor abierto | 21,2 ms (sin diferencia medible) |
  | Rama, con un monitor abierto en otro hilo (peor caso) | 24,6 ms |

  Con el monitor abierto se publican unos 37 eventos por turno (~0,09 ms por evento). Frente a un turno real, que
  tarda segundos por los modelos, es despreciable.
