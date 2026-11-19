# ADR 0002 · Protocolo de *streaming* entre FastAPI y la UI

- **Estado:** aceptado · 2026-11-19 · P1
- **Versiones:** `ai@7.0.177`, `@ai-sdk/react@4.0.181`, AI Elements (CLI `ai-elements@1.9.1`), `shadcn@4.23.0`.

## Contexto
La UI usa AI Elements, diseñados para los mensajes del AI SDK (`UIMessage` con `parts`). Opciones:
**(a)** `useChat` del AI SDK con el backend emitiendo el **UI Message Stream protocol** (SSE), o
**(b)** componentes solo de presentación con un cliente SSE propio.

## Decisión
**(a) `useChat` + `DefaultChatTransport`** apuntando a `POST {VITE_API_URL}/api/chat`.

El backend implementa el protocolo en **un solo módulo**, `backend/app/api/stream_protocol.py`:
cabecera `x-vercel-ai-ui-message-stream: v1`, `Content-Type: text/event-stream`, eventos
`data: {json}\n\n` y cierre `data: [DONE]`. Partes usadas: `start`, `text-start/delta/end`,
`data-etapa`, `data-revisando`, `data-caso` (y en F3+: `tool-*`, `source-url`, `data-consentimiento`,
`data-espera-n2`), `finish`, `error`.

**Por qué mantiene el backend independiente del proveedor:** el protocolo es un contrato de
**presentación** entre la API y la UI, no del LLM. Los agentes producen eventos internos
(`EventoTexto`, `EventoEtapa`, …) a partir de la capa LLM agnóstica; `stream_protocol.py` los
traduce. Cambiar de proveedor de LLM no toca el protocolo, y cambiar de protocolo no toca a los agentes.
El backend **no** usa el SDK de JS ni ningún SDK de proveedor para emitirlo.

### Reglas que se derivan
- El cliente envía `{id, messages, trigger, messageId}`; el backend **solo usa el último mensaje
  del usuario** y el `id` como `case_id`. El historial vive en el estado del caso, no en lo que
  mande el cliente (evita que la UI reescriba la conversación).
- Consentimiento y aprobación **no** van por `/api/chat`: tienen endpoints propios (F4).
- Datos para la UI de seguridad (tarjetas) llegan como partes `data-*` estructuradas, nunca como texto a interpretar.

## AI Elements en Vite
- Se instala con `npx ai-elements@latest add <componente>` sobre shadcn inicializado para Vite
  (Tailwind 4, alias `@/`). Los componentes no importan `next/*`; `"use client"` es inocuo en Vite.
- AI Elements anunció su migración a los "patterns" de shadcn/ui (fin de nov. 2026). Como el código
  queda **copiado en el repo** (`src/components/ai-elements`), la deprecación no rompe el build. Migrar es opcional.

## Consecuencias
- (+) Reutilizamos `useChat` (estado, *streaming*, reintentos, adjuntos) y los componentes tal cual.
- (−) Dependemos de la estabilidad del protocolo v1; mitigado por estar aislado en un módulo con pruebas.
