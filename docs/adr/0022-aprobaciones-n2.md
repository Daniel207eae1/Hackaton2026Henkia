# ADR 0022 · Bandeja de aprobaciones N2 sobre la API REST del servidor MCP

- **Estado:** aceptado · 2026-11-20 · P1

## Contexto
Las acciones con política `aprobacion_n2` necesitan la aprobación de un técnico humano **y** el consentimiento del
usuario en su equipo. Hasta ahora la aprobación se daba en el canal del servidor MCP. El servidor expone una API REST
N2 (`/n2/aprobaciones`, `/aprobar`, `/rechazar`, `/n2/consentimientos`, `/auditoria`) protegida con `X-N2-Key`.

## Decisión
- **El navegador solo habla con nuestro backend.**
  - El backend llama a la API N2 con `N2_API_KEY`. La clave vive solo en el servidor: `repr=False` en los ajustes,
    `__repr__` propio en el cliente, errores con textos fijos y logs sin la clave ni trazas.
  - Un 401 se registra como error de configuración, sin mostrar la clave.
- **Solo humanos deciden.** El sondeo (cada `N2_POLL_S`) solo lee. Aprobar o rechazar es un `POST` por solicitud
  que dispara un técnico con rol N2 del directorio; no hay decisiones en lote.
  - El nombre del técnico sale de la sesión (persona del directorio), nunca del cuerpo, que solo acepta `nota` y
    `huella`.
- **La decisión queda ligada a lo que se vio.** Cada solicitud lleva una `huella`: el SHA-256 de tool, equipo,
  caso, diagnóstico y comando. La UI la devuelve al decidir, y si la solicitud cambió desde que se mostró, el backend
  responde 409.
- **Solo se aprueba lo que este sistema permite.**
  - `aprobar` solo vale para tools con política `aprobacion_n2` de nuestra lista blanca.
  - Un comando libre (`ejecutar_comando_generico`) o una tool desconocida solo se puede **rechazar**: invariante 7,
    «nunca comandos libres». Esto es más estricto que la guía del servidor, que permite aprobar comandos con doble
    confirmación.
- **Notificación única.** Las pendientes nuevas generan un aviso. Los ids vistos, los avisos y las decisiones se
  guardan en `N2_STATE_FILE` (volumen `n2`) con escritura atómica, así un reinicio no vuelve a notificar.
- **Errores.**
  - **409:** muestra quién decidió, sin reintentar.
  - **5xx o red:** reintento con espera exponencial.
  - **POST sin respuesta:** se lee el estado final antes de responder. Si no se puede leer, el mensaje es «estado
    incierto»; nunca dice «sigue pendiente».
  - **Varias pestañas:** el GET sirve la caché del sondeo si tiene menos de 5 s.
- **Datos.** `diagnostico` y `comando` (los escribe una IA) se devuelven como dato y la UI los muestra como texto
  escapado. Ningún agente ni prompt los lee. De la auditoría y los consentimientos del servidor solo pasan campos de
  una lista blanca, con el texto enmascarado. La nota del técnico se guarda enmascarada.
- **Seguimiento.** Una aprobada sigue visible hasta que `usada`. Pasados `N2_SIN_EJECUTAR_MIN` (30 min) sin
  ejecutarse, se marca «aprobada sin ejecutar», porque puede que el usuario no haya autorizado en su equipo.

## Riesgo aceptado (demo)
- **No hay login real.** La identidad sale de «Ver como» (`MODO_DEMO=true`). Por eso la API y la UI se publican
  **solo en `127.0.0.1`** (docker-compose): nadie más en la red puede llamar los endpoints de decisión.
- **Antes de exponerlo fuera de la máquina** hace falta autenticación real de los técnicos (sesión u OIDC).
- **Un solo worker escribe el archivo de estado.** Con varias réplicas habría que pasarlo a la BD.

## Consecuencias
- `test_n2_aprobaciones.py` (13 pruebas) y `aprobaciones-n2.test.tsx` (5) cubren:
  - rol N2 y clave ausente de las respuestas;
  - técnico tomado de la sesión;
  - 409 entre dos técnicos;
  - nota obligatoria al rechazar;
  - comando libre solo rechazable;
  - huella;
  - HTML y órdenes mostrados como dato;
  - notificación única tras un reinicio;
  - 401 sin la clave;
  - reintentos;
  - reconciliación de un POST sin respuesta;
  - lista blanca de la auditoría;
  - «aprobada sin ejecutar».
- Falta la clave `N2_API_KEY` en `.env` para probarlo contra el servidor real.
