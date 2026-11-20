/**
 * Monitor de agentes (ADR 0023): cliente del stream SSE propio de `/api/monitor/stream` y estado derivado.
 *
 * - `EventSource` no admite cabeceras y la identidad viaja en `X-Ver-Como` (nunca en la query string):
 *   se usa `fetch` + `ReadableStream` con la misma base que `pedir()`.
 * - Reconexión automática con *backoff* exponencial (tope 15 s). 401/403/404 no se reintentan.
 * - Solo llegan metadatos (agente, etapa, duración, error, caso, URL de la traza): nunca texto del usuario.
 */
import { API_URL } from "@/lib/api";

export interface EventoMonitor {
  tipo: "turno_inicio" | "turno_fin" | "etapa" | "agente_inicio" | "agente_fin" | "monitor_lleno" | string;
  caso: string | null;
  ts: number;
  seq: number;
  agente?: string;
  tipo_observacion?: string;
  duracion_ms?: number;
  error?: boolean;
  etapa?: string;
  etapa_final?: string;
  traza_url?: string | null;
}

export interface GrafoMonitor {
  nodos: { id: string }[];
  aristas: { origen: string; destino: string; condicional: boolean }[];
}

export type EstadoConexion = "conectando" | "conectado" | "reconectando" | "desconectado";

// ------------------------------------------------------------------ lectura del stream

/** Separa bloques SSE completos (`\n\n`). Devuelve los eventos `data:` válidos y el resto sin terminar. */
export function parsearBloques(buffer: string): { eventos: EventoMonitor[]; resto: string } {
  const partes = buffer.replace(/\r\n/g, "\n").split("\n\n");
  const resto = partes.pop() ?? "";
  const eventos: EventoMonitor[] = [];
  for (const bloque of partes) {
    const datos = bloque
      .split("\n")
      .filter((l) => l.startsWith("data:"))
      .map((l) => l.slice(5).trimStart())
      .join("\n");
    if (!datos) continue; // comentarios (`: ping`, `: conectado`)
    try {
      const ev = JSON.parse(datos) as EventoMonitor;
      if (ev && typeof ev.tipo === "string") eventos.push(ev);
    } catch {
      /* bloque malformado: se ignora */
    }
  }
  return { eventos, resto };
}

const NO_REINTENTAR = new Set([401, 403, 404]);
const ESPERA_MAX_MS = 15_000;

export function esperaReconexion(intento: number): number {
  return Math.min(ESPERA_MAX_MS, 1000 * 2 ** Math.max(0, intento));
}

/**
 * Abre el stream y lo mantiene vivo hasta que `senal` se aborta. Nunca lanza: informa por `alEstado`.
 */
export async function conectarMonitor(opciones: {
  verComo: string;
  senal: AbortSignal;
  alEvento: (ev: EventoMonitor) => void;
  alEstado: (estado: EstadoConexion, detalle?: string) => void;
  esperar?: (ms: number, senal: AbortSignal) => Promise<void>;
}): Promise<void> {
  const { verComo, senal, alEvento, alEstado } = opciones;
  const esperar = opciones.esperar ?? esperaAbortable;
  let intento = 0;
  while (!senal.aborted) {
    alEstado(intento === 0 ? "conectando" : "reconectando");
    try {
      const resp = await fetch(`${API_URL}/api/monitor/stream`, {
        headers: { "X-Ver-Como": verComo, Accept: "text/event-stream" },
        signal: senal,
        cache: "no-store",
      });
      if (NO_REINTENTAR.has(resp.status)) {
        alEstado("desconectado", resp.status === 404 ? "El monitor está desactivado" : "Tu rol no permite ver el monitor");
        return;
      }
      if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);
      alEstado("conectado");
      intento = 0;
      const lector = resp.body.getReader();
      const decodificador = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done } = await lector.read();
        if (done) break;
        const { eventos, resto } = parsearBloques(buffer + decodificador.decode(value, { stream: true }));
        buffer = resto;
        for (const ev of eventos) alEvento(ev);
      }
    } catch {
      if (senal.aborted) return;
    }
    if (senal.aborted) return;
    alEstado("reconectando");
    await esperar(esperaReconexion(intento), senal);
    intento += 1;
  }
}

function esperaAbortable(ms: number, senal: AbortSignal): Promise<void> {
  return new Promise((resolver) => {
    const t = setTimeout(resolver, ms);
    senal.addEventListener(
      "abort",
      () => {
        clearTimeout(t);
        resolver();
      },
      { once: true },
    );
  });
}

// ------------------------------------------------------------------ estado derivado (reductor puro)

/** Nodos en los que el flujo espera a una persona (consentimiento en el equipo o aprobación de N2). */
export const NODOS_ESPERA = new Set(["Consentimiento", "AprobacionN2"]);
/** Observaciones que no aportan en la línea de tiempo (el turno ya tiene su propia marca). */
const OCULTOS = new Set(["turno"]);
const MAX_LINEA = 200;
const MAX_FONDO = 100;
const MAX_CASOS = 30;

export type EstadoNodo = "inactivo" | "activo" | "completado" | "espera" | "error";

export interface EntradaLinea {
  clave: string;
  clase: "agente" | "turno_inicio" | "turno_fin";
  ts: number;
  agente?: string;
  tipoObservacion?: string;
  duracionMs?: number | null;
  estado: "en_curso" | "ok" | "error";
  etapaFinal?: string;
  trazaUrl?: string | null;
}

export interface CasoMonitor {
  id: string;
  ultimoTs: number;
  nodoActivo: string | null;
  completados: string[];
  recorrido: [string, string][];
  espera: string | null;
  errorNodo: string | null;
  enCurso: boolean;
  trazaUrl: string | null;
  linea: EntradaLinea[];
}

export interface EstadoMonitor {
  casos: Record<string, CasoMonitor>;
  /** Casos de más reciente a más antiguo. */
  orden: string[];
  /** Procesos de fondo (sin caso: curador de KB por lotes). */
  fondo: EntradaLinea[];
}

export const ESTADO_INICIAL: EstadoMonitor = { casos: {}, orden: [], fondo: [] };

function casoVacio(id: string, ts: number): CasoMonitor {
  return {
    id,
    ultimoTs: ts,
    nodoActivo: null,
    completados: [],
    recorrido: [],
    espera: null,
    errorNodo: null,
    enCurso: false,
    trazaUrl: null,
    linea: [],
  };
}

function conAgente(linea: EntradaLinea[], ev: EventoMonitor, max: number): EntradaLinea[] {
  if (!ev.agente || OCULTOS.has(ev.agente)) return linea;
  if (ev.tipo === "agente_inicio") {
    const nueva: EntradaLinea = {
      clave: `a-${ev.seq}`,
      clase: "agente",
      ts: ev.ts,
      agente: ev.agente,
      tipoObservacion: ev.tipo_observacion,
      duracionMs: null,
      estado: "en_curso",
    };
    return [...linea, nueva].slice(-max);
  }
  // agente_fin: cierra la última entrada abierta de ese agente (o crea una si se perdió el inicio)
  for (let i = linea.length - 1; i >= 0; i--) {
    const e = linea[i];
    if (e.clase === "agente" && e.agente === ev.agente && e.estado === "en_curso") {
      const copia = [...linea];
      copia[i] = { ...e, duracionMs: ev.duracion_ms ?? null, estado: ev.error ? "error" : "ok" };
      return copia;
    }
  }
  return [
    ...linea,
    {
      clave: `a-${ev.seq}`,
      clase: "agente" as const,
      ts: ev.ts,
      agente: ev.agente,
      tipoObservacion: ev.tipo_observacion,
      duracionMs: ev.duracion_ms ?? null,
      estado: ev.error ? ("error" as const) : ("ok" as const),
    },
  ].slice(-max);
}

function agregarCompletado(completados: string[], nodo: string | null): string[] {
  return nodo && !completados.includes(nodo) ? [...completados, nodo] : completados;
}

export function reducir(estado: EstadoMonitor, ev: EventoMonitor): EstadoMonitor {
  if (!ev.caso) {
    if (ev.tipo !== "agente_inicio" && ev.tipo !== "agente_fin") return estado;
    return { ...estado, fondo: conAgente(estado.fondo, ev, MAX_FONDO) };
  }
  const previo = estado.casos[ev.caso] ?? casoVacio(ev.caso, ev.ts);
  let c: CasoMonitor = { ...previo, ultimoTs: ev.ts };
  switch (ev.tipo) {
    case "turno_inicio":
      c = {
        ...c,
        nodoActivo: null,
        completados: [],
        recorrido: [],
        espera: null,
        errorNodo: null,
        enCurso: true,
        linea: [...c.linea, { clave: `t-${ev.seq}`, clase: "turno_inicio" as const, ts: ev.ts, estado: "en_curso" as const }].slice(
          -MAX_LINEA,
        ),
      };
      break;
    case "etapa": {
      const etapa = ev.etapa ?? "";
      if (!etapa || etapa === c.nodoActivo) break;
      const desde = c.nodoActivo ?? (c.recorrido.length === 0 ? "__start__" : null);
      c = {
        ...c,
        completados: agregarCompletado(c.completados, c.nodoActivo),
        recorrido: desde ? [...c.recorrido, [desde, etapa]] : c.recorrido,
        nodoActivo: etapa,
        espera: NODOS_ESPERA.has(etapa) ? etapa : null,
      };
      break;
    }
    case "agente_inicio":
    case "agente_fin":
      c = { ...c, linea: conAgente(c.linea, ev, MAX_LINEA) };
      break;
    case "turno_fin": {
      const final = ev.etapa_final || c.nodoActivo;
      const espera = final && NODOS_ESPERA.has(final) ? final : null;
      const errorNodo = ev.error ? (c.nodoActivo ?? final ?? null) : null;
      c = {
        ...c,
        enCurso: false,
        espera,
        errorNodo,
        nodoActivo: null,
        completados: espera || errorNodo ? c.completados : agregarCompletado(c.completados, c.nodoActivo),
        recorrido: c.nodoActivo && !espera && !errorNodo ? [...c.recorrido, [c.nodoActivo, "__end__"]] : c.recorrido,
        trazaUrl: ev.traza_url ?? c.trazaUrl,
        linea: [
          ...c.linea,
          {
            clave: `t-${ev.seq}`,
            clase: "turno_fin" as const,
            ts: ev.ts,
            estado: ev.error ? ("error" as const) : ("ok" as const),
            etapaFinal: final ?? undefined,
            trazaUrl: ev.traza_url ?? null,
          },
        ].slice(-MAX_LINEA),
      };
      break;
    }
    default:
      return estado;
  }
  const orden = [ev.caso, ...estado.orden.filter((id) => id !== ev.caso)].slice(0, MAX_CASOS);
  const casos: Record<string, CasoMonitor> = {};
  for (const id of orden) casos[id] = id === ev.caso ? c : estado.casos[id];
  return { ...estado, casos, orden };
}

export function estadoDeNodo(caso: CasoMonitor | undefined, nodo: string): EstadoNodo {
  if (!caso) return "inactivo";
  if (caso.errorNodo === nodo) return "error";
  if (caso.espera === nodo) return "espera";
  if (caso.nodoActivo === nodo) return "activo";
  if (caso.completados.includes(nodo)) return "completado";
  return "inactivo";
}

/** Solo enlaces http(s): una URL `javascript:` nunca llega a un `href`. */
export function urlSegura(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:" ? u.toString() : null;
  } catch {
    return null;
  }
}
