import { act, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "@/components/app-shell";
import { LineaTiempo } from "@/components/monitor/linea-tiempo";
import type { Persona } from "@/lib/api";
import {
  ESTADO_INICIAL,
  estadoDeNodo,
  parsearBloques,
  reducir,
  urlSegura,
  type EventoMonitor,
  type GrafoMonitor,
} from "@/lib/monitor";
import { VerComoProvider } from "@/lib/ver-como";
import { Monitor } from "@/vistas/monitor";

// React Flow en jsdom necesita estas APIs del navegador (recomendación de su documentación de pruebas).
beforeEach(() => {
  class ResizeObserverFalso {
    constructor(private cb: ResizeObserverCallback) {}
    observe(target: Element) {
      this.cb([{ target } as ResizeObserverEntry], this as unknown as ResizeObserver);
    }
    unobserve() {}
    disconnect() {}
  }
  class DOMMatrixFalso {
    m22 = 1;
  }
  vi.stubGlobal("ResizeObserver", ResizeObserverFalso);
  vi.stubGlobal("DOMMatrixReadOnly", DOMMatrixFalso);
  Object.defineProperties(HTMLElement.prototype, {
    offsetHeight: { configurable: true, get: () => 100 },
    offsetWidth: { configurable: true, get: () => 100 },
  });
  (SVGElement.prototype as unknown as { getBBox: () => DOMRect }).getBBox = () =>
    ({ x: 0, y: 0, width: 0, height: 0 }) as DOMRect;
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

const N2: Persona = { id: "TEC-SIM-01", nombre: "Diego Soporte", rol: "n2", area: "Mesa", equipo_id: null };
const GRAFO: GrafoMonitor = {
  nodos: ["__start__", "Recepcion", "Captura", "Contexto", "Consentimiento", "NodoNuevo", "__end__"].map((id) => ({ id })),
  aristas: [
    { origen: "__start__", destino: "Recepcion", condicional: false },
    { origen: "Recepcion", destino: "Captura", condicional: true },
    { origen: "Captura", destino: "Contexto", condicional: true },
    { origen: "Contexto", destino: "Consentimiento", condicional: true },
  ],
};

let n = 0;
function ev(tipo: string, datos: Partial<EventoMonitor> = {}): EventoMonitor {
  n += 1;
  return { tipo, caso: "caso-abc", ts: 1_700_000_000_000 + n, seq: n, ...datos };
}

describe("estado del monitor (reductor puro)", () => {
  it("marca el nodo activo, los completados y el recorrido en orden", () => {
    let s = reducir(ESTADO_INICIAL, ev("turno_inicio"));
    s = reducir(s, ev("etapa", { etapa: "Recepcion" }));
    s = reducir(s, ev("etapa", { etapa: "Contexto" }));
    const c = s.casos["caso-abc"];
    expect(estadoDeNodo(c, "Contexto")).toBe("activo");
    expect(estadoDeNodo(c, "Recepcion")).toBe("completado");
    expect(c.recorrido).toEqual([
      ["__start__", "Recepcion"],
      ["Recepcion", "Contexto"],
    ]);
  });

  it("un turno que termina en Consentimiento deja ese nodo en espera humana", () => {
    let s = reducir(ESTADO_INICIAL, ev("turno_inicio"));
    s = reducir(s, ev("etapa", { etapa: "Consentimiento" }));
    expect(estadoDeNodo(s.casos["caso-abc"], "Consentimiento")).toBe("espera");
    s = reducir(s, ev("turno_fin", { etapa_final: "Consentimiento", error: false }));
    expect(estadoDeNodo(s.casos["caso-abc"], "Consentimiento")).toBe("espera");
  });

  it("los eventos sin caso (curador_kb) van al carril de procesos de fondo", () => {
    let s = reducir(ESTADO_INICIAL, ev("agente_inicio", { caso: null, agente: "curador_kb", tipo_observacion: "agent" }));
    s = reducir(s, ev("agente_fin", { caso: null, agente: "curador_kb", duracion_ms: 1500, error: false }));
    expect(s.orden).toEqual([]);
    expect(s.fondo).toMatchObject([{ agente: "curador_kb", estado: "ok", duracionMs: 1500 }]);
  });

  it("lee bloques SSE: ignora latidos y deja el bloque incompleto para después", () => {
    const { eventos, resto } = parsearBloques(': ping\n\ndata: {"tipo":"etapa","caso":"x","ts":1,"seq":1}\n\ndata: {"ti');
    expect(eventos).toHaveLength(1);
    expect(resto).toBe('data: {"ti');
  });

  it("solo acepta enlaces http(s) para la traza", () => {
    expect(urlSegura("javascript:alert(1)")).toBeNull();
    expect(urlSegura("http://localhost:3000/project/p/traces/t")).toContain("/traces/t");
  });
});

/** Stream controlable: devuelve la Response del stream y una función para empujar eventos. */
function streamFalso() {
  const codificador = new TextEncoder();
  let control!: ReadableStreamDefaultController<Uint8Array>;
  const cuerpo = new ReadableStream<Uint8Array>({
    start(c) {
      control = c;
      c.enqueue(codificador.encode(": conectado\n\n"));
    },
  });
  return {
    respuesta: new Response(cuerpo, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    empujar: (e: EventoMonitor) => control.enqueue(codificador.encode(`data: ${JSON.stringify(e)}\n\n`)),
  };
}

describe("vista Monitor de agentes", () => {
  it("dibuja los nodos del grafo y marca el activo al recibir un evento etapa", async () => {
    const stream = streamFalso();
    const fetchFalso = vi.fn(async (url: string, init?: RequestInit) => {
      expect(new Headers(init?.headers).get("X-Ver-Como")).toBe("TEC-SIM-01"); // identidad en cabecera, nunca en la URL
      expect(url).not.toContain("TEC-SIM-01");
      if (url.endsWith("/api/monitor/grafo")) return new Response(JSON.stringify(GRAFO), { status: 200 });
      return stream.respuesta;
    });
    vi.stubGlobal("fetch", fetchFalso);

    render(<Monitor persona={N2} />);
    expect(await screen.findByText("Contexto", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByText("Recepción")).toBeInTheDocument();
    expect(screen.getByText("NodoNuevo")).toBeInTheDocument(); // un nodo desconocido también aparece
    await screen.findByText("Conectado");

    act(() => {
      stream.empujar(ev("turno_inicio"));
      stream.empujar(ev("etapa", { etapa: "Recepcion" }));
      stream.empujar(ev("etapa", { etapa: "Contexto" }));
      stream.empujar(ev("agente_inicio", { agente: "agente_contexto", tipo_observacion: "agent" }));
    });

    await waitFor(() => expect(screen.getByText("Contexto").closest("[data-estado]")).toHaveAttribute("data-estado", "activo"));
    expect(screen.getByText("Recepción").closest("[data-estado]")).toHaveAttribute("data-estado", "completado");
    expect(screen.getByText("Nodo activo: Contexto.")).toBeInTheDocument();
    const linea = screen.getByRole("heading", { name: /Línea de tiempo/ }).closest("section")!;
    expect(within(linea).getByText("agente_contexto")).toBeInTheDocument();
  });
});

describe("línea de tiempo", () => {
  it("muestra el texto del backend escapado y no enlaza URLs que no son http(s)", () => {
    const { container } = render(
      <LineaTiempo
        titulo="Prueba"
        vacio="-"
        entradas={[
          { clave: "1", clase: "agente", ts: 1, agente: '<img src=x onerror="alert(1)">', estado: "error", duracionMs: 12 },
          { clave: "2", clase: "turno_fin", ts: 2, estado: "ok", etapaFinal: "Cierre", trazaUrl: "javascript:alert(1)" },
        ]}
      />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText('<img src=x onerror="alert(1)">')).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByRole("list")).toHaveAttribute("aria-live", "polite");
  });
});

describe("navegación", () => {
  const personas: Persona[] = [
    { id: "USR-SIM-001", nombre: "Ana", rol: "colaborador", area: "Ventas", equipo_id: "EQ-SIM-001" },
    { id: "TEC-SIM-01", nombre: "Diego", rol: "n2", area: "Mesa", equipo_id: null },
  ];

  async function shellComo(id: string) {
    window.localStorage.setItem("caso5.verComo", id);
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(personas), { status: 200 })));
    render(
      <MemoryRouter>
        <VerComoProvider>
          <AppShell>contenido</AppShell>
        </VerComoProvider>
      </MemoryRouter>,
    );
    await screen.findByRole("navigation", { name: "Vistas" });
    await waitFor(() => expect(within(screen.getByRole("navigation", { name: "Vistas" })).getAllByRole("link").length).toBeGreaterThan(0));
  }

  it("el colaborador no ve el enlace al monitor", async () => {
    await shellComo("USR-SIM-001");
    expect(screen.queryByRole("link", { name: "Monitor de agentes" })).toBeNull();
  });

  it("N2 ve el enlace al monitor", async () => {
    await shellComo("TEC-SIM-01");
    expect(screen.getByRole("link", { name: "Monitor de agentes" })).toHaveAttribute("href", "/monitor");
  });
});
