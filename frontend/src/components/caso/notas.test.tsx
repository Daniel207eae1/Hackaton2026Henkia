import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Valoracion } from "@/components/caso/valoracion";
import { idUltimaEjecutada, type MensajeCaso } from "@/lib/mensajes";

const accion = (id: string, tool: string) => ({
  type: "data-accion", id,
  data: { id, tool, nombre: "x", descripcion: "", aviso: "", reversion: "", riesgo: "bajo", politica: "consentimiento",
    estado: "ejecutada", mensaje: "" },
});

afterEach(() => vi.unstubAllGlobals());

describe("botones de confirmación", () => {
  it("leer logs no es una solución: no pregunta «¿ya te funciona?»", () => {
    const m = [{ id: "a", role: "assistant", parts: [accion("acc-1", "leer_logs_aplicacion")] }] as unknown as MensajeCaso[];
    expect(idUltimaEjecutada(m)).toBeUndefined();
  });

  it("solo la respuesta más reciente; si la conversación siguió, desaparecen", () => {
    const sol = { id: "a", role: "assistant", parts: [accion("acc-2", "reiniciar_cola_impresion")] };
    expect(idUltimaEjecutada([sol] as unknown as MensajeCaso[])).toBe("acc-2");
    const despues = [sol, { id: "u", role: "user", parts: [] }, { id: "b", role: "assistant", parts: [] }];
    expect(idUltimaEjecutada(despues as unknown as MensajeCaso[])).toBeUndefined();
  });
});

describe("valoración al terminar el caso", () => {
  it("envía útil + comentario una vez", async () => {
    const f = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", f);
    render(<Valoracion caseId="c1" verComo="USR-SIM-001" />);
    await userEvent.click(screen.getByRole("button", { name: "Sí" }));
    await userEvent.type(screen.getByLabelText(/Algo que debamos mejorar/), "rápido");
    await userEvent.click(screen.getByRole("button", { name: "Enviar valoración" }));
    expect(await screen.findByText("¡Gracias por tu valoración!")).toBeInTheDocument();
    expect(JSON.parse(f.mock.calls[0][1].body)).toEqual({ util: true, comentario: "rápido" });
  });
});

describe("indicador de progreso", () => {
  it("dice qué está haciendo según la etapa y el último hallazgo", async () => {
    const { IndicadorProgreso } = await import("@/components/caso/indicador-progreso");
    render(<IndicadorProgreso etapa="Consentimiento" detalle="Revisé tu equipo: 120 GB libres." />);
    expect(screen.getByRole("status")).toHaveTextContent("Esperando tu autorización en la ventana «Soporte TI»");
    expect(screen.getByText("Revisé tu equipo: 120 GB libres.")).toBeInTheDocument();
  });
});
