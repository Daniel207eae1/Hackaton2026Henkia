# frontend/CLAUDE.md

React 19 + TypeScript 6 + Vite 8 + Tailwind 4 + shadcn/ui (preset `radix-nova`) + AI Elements +
AI SDK (`ai@7`, `@ai-sdk/react@4`). Versiones exactas en `package.json`. Reglas globales: `../CLAUDE.md`.

## Comandos

```powershell
npm ci
npm run dev        # http://localhost:5173 (VITE_API_URL, por defecto http://localhost:8000)
npm run typecheck; npm run lint; npm run test; npm run build
```

## Estructura

| Ruta | Qué hay |
|---|---|
| `src/main.tsx`, `src/App.tsx` | *Providers* (router, tooltip, «Ver como») y rutas por rol |
| `src/components/app-shell.tsx` | Barra superior: «Ver como», «Modo demostración», navegación por rol |
| `src/vistas/` | Una vista por pantalla: `chat-colaborador`, `consola-n2`, `casos` (N2: lista + detalle con diagnóstico), `base-conocimiento` (N2 y revisor, solo lectura), `revisor-kb`, `metricas` (con gráficas), `auditoria` |
| `src/components/graficas.tsx` | Gráficas en SVG propio (sin dependencias). Paleta validada `--serie-1..4` (CVD y contraste); siempre con leyenda, valores y «Ver como tabla» |
| `src/components/caso/detalle-caso.tsx` | Detalle del caso (hipótesis y por qué, lo consultado, acciones, conversación), usado por Casos, Auditoría y la ficha N2 |
| `src/components/caso/` | Piezas propias del caso: `panel-revisando`, `indicador-etapa` (F4: tarjetas de consentimiento/aprobación) |
| `src/lib/api.ts` | `pedir()` con `X-Ver-Como` |
| `src/lib/ver-como.tsx` | Contexto de la persona elegida (`localStorage` con try/catch) |
| `src/lib/mensajes.ts` | Tipos de las partes `data-*` y utilidades |
| `src/vistas/monitor.tsx`, `src/lib/monitor.ts`, `src/components/monitor/` | Monitor de agentes (ADR 0023): stream con `fetch` + `X-Ver-Como` y reconexión; diagrama con `@xyflow/react` cargado con `React.lazy` |
| `src/components/ui/` | Generado por shadcn — **no editar** |
| `src/components/ai-elements/` | Generado por AI Elements — **no editar** |

## Cómo agregar componentes

```powershell
npx shadcn@4.23.0 add <componente> -y
# AI Elements (el CLI pregunta si sobrescribe: responde "n" para no pisar los de shadcn)
npx ai-elements@1.9.1 add <componente>
```
AI Elements anunció su paso a shadcn/ui (fin de nov. 2026). El código ya está copiado en el repo; migrar a los
*patterns* de shadcn es opcional (ADR 0002).

## Streaming (ADR 0002)
- `useChat<MensajeCaso>` + `DefaultChatTransport({ api: API_URL + "/api/chat", headers: { "X-Ver-Como": id } })`.
- `id` del chat = `case_id` (uno nuevo por «Nuevo caso» y por persona).
- El backend emite partes `data-etapa`, `data-revisando`, `data-caso` (y en F3+ `tool-*`, `source-url`,
  `data-consentimiento`, `data-espera-n2`). Para una parte nueva: agrega su tipo en `src/lib/mensajes.ts`
  (`PartesDatos`) y un componente en `src/components/caso/`.

## Reglas
- Capturas (F7): `PromptInput` con `accept`/`maxFiles`/`maxFileSize`; `components/caso/capturas.tsx` (botón, lista, tarjeta). El transporte manda solo el último mensaje.
- **Consentimiento y aprobación = botón → `POST` a su endpoint** (F4), nunca `sendMessage`.
  Los textos de la tarjeta (qué hará, aviso, reversión, riesgo) vienen del backend tal cual.
- Texto del backend: siempre como texto de React (escapado). ESLint bloquea `dangerouslySetInnerHTML`.
- **No usar `MessageResponse` (Markdown/Streamdown)** con texto del LLM hasta verificar en F3 que no
  renderiza HTML crudo; mientras tanto, texto plano con `whitespace-pre-wrap`.
- Errores en inglés y texto de capturas: como cita escapada (`<blockquote>`/`<code>`), nunca como instrucción.
- Accesibilidad: foco visible, todo operable con teclado, `aria-live` en lo que se actualiza en vivo,
  `aria-label` en botones con solo icono, contraste AA. Textos en español.
- Siempre visibles: «Modo demostración» y «Hablar con una persona» (activo desde F6).
- La guarda por rol de la UI es solo de navegación: **el backend decide** con el rol de la BD.

## Pendientes conocidos
- Bundle de ~2 MB por Streamdown (Mermaid, KaTeX) arrastrado por `message.tsx`: dividir con `import()` en F9.
