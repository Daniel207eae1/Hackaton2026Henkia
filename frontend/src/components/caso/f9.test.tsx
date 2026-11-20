import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { type RespuestaMetricas, TablaEvaluacion } from "@/vistas/metricas";

const ev: NonNullable<RespuestaMetricas["evaluacion"]> = {
  experimento: "11192300",
  fecha: "2026-11-19T23:00:00+00:00",
  resumen: {
    guiones: 2, aciertos: 1, tasa_acierto: 0.5, fcr: 0.5, precision_diagnostico: 1, preguntas_promedio: 1.5,
    acciones_sin_token: 0, inyecciones_resistidas: 1, segundos_p50: 20, segundos_p95: 40, costo_total_usd: 0.002,
    costo_por_caso_usd: 0.001, costo_por_agente_usd: { conversacional: 0.0012, interprete: 0.0008 },
    modulo_a: { faltantes: ["borrar_credenciales_teams"], desactualizados: ["KB-SIM-003", "KB-SIM-016"], ok: true },
  },
  guiones: [
    { id: "esc06", titulo: "Impresión", red_team: false, resultado: "cerrado", esperado: ["cerrado"], articulos_confirmados: ["KB-SIM-023"],
      articulo_esperado: "KB-SIM-023", acciones: ["reiniciar_cola_impresion"], acciones_sin_token: [], banderas: [], preguntas: 0,
      turnos: 2, segundos: 20, costo_usd: 0.001, ok: true, error: null },
    { id: "rt01", titulo: "Red team", red_team: true, resultado: "abierto", esperado: ["abierto"], articulos_confirmados: [],
      articulo_esperado: null, acciones: [], acciones_sin_token: [], banderas: ["inyeccion"], preguntas: 0, turnos: 1,
      segundos: 3, costo_usd: 0, ok: false, error: null },
  ],
};

describe("métricas (F9)", () => {
  it("muestra metas con estado en texto y el detalle por guion", () => {
    render(<TablaEvaluacion ev={ev} />);
    expect(screen.getByText("1/2 (50 %)")).toBeInTheDocument();
    expect(screen.getAllByText("cumple").length).toBeGreaterThan(0);
    expect(screen.getByText("no cumple")).toBeInTheDocument(); // FCR 50 % < 70 %
    expect(screen.getByText("pasa")).toBeInTheDocument();
    expect(screen.getByText("falla")).toBeInTheDocument();
    expect(screen.getByText("1 + 2")).toBeInTheDocument();
  });
});
