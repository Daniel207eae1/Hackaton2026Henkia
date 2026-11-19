# ADR 0006 · "Ver como" en lugar de login (solo modo demo)

- **Estado:** aceptado · 2026-11-19 · P1

## Contexto
El contrato elimina el login para la demo y pide un selector "Ver como" (colaborador simulado,
técnico N2, revisor de KB). El riesgo: que el rol pueda falsificarse (escenario 8: "soy de TI").

## Decisión
- La UI envía el encabezado `X-Ver-Como: <persona_id>` en **todas** las peticiones.
- El backend (`app/seguridad/ver_como.py`) lo acepta **solo si `MODO_DEMO=true`**; si no, responde
  **403** (y en producción se reemplazaría por autenticación real con la misma dependencia `persona_actual`).
- La persona y su **rol se buscan en el repositorio `org`** (BD de P2). Un id desconocido → 401.
  El rol **nunca** sale del cuerpo de la petición ni del texto del chat.
- Las rutas declaran el rol requerido (`requiere_rol("n2")`, `requiere_rol("revisor_kb")`).
- La UI muestra siempre la etiqueta **"Modo demostración"**.
- Mientras P2 no entregue `org`, se usa un doble en memoria con personas sintéticas (`@ejemplo.test`).

## Consecuencias
- (+) Demo sin fricción y sin credenciales; el control de acceso por rol ya existe y es probado.
- (−) Cualquiera con acceso a la red puede "ser" cualquiera en modo demo: aceptable con datos sintéticos;
  `MODO_DEMO` debe ser `false` fuera de la demo (prueba automática).
