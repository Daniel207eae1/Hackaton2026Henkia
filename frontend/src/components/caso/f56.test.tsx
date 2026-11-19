import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TarjetaAccion } from "@/components/caso/tarjeta-accion";
import { TarjetaEscalamiento } from "@/components/caso/tarjeta-resultado";
import type { DatosAccion } from "@/lib/mensajes";
import { FichaEscalamiento } from "@/vistas/consola-n2";

const ejecutada: DatosAccion = {
  id: "accion-1", tool: "reiniciar_cola_impresion", nombre: "Reiniciar la cola de impresión", descripcion: "d",
  aviso: "a", reversion: "r", riesgo: "bajo", politica: "consentimiento", estado: "ejecutada", mensaje: "",
};

describe("confirmación de la acción ejecutada", () => {
  it("ofrece Sí/No y envía el texto del botón", async () => {
    const onConfirmar = vi.fn();
    render(<TarjetaAccion accion={ejecutada} onConfirmar={onConfirmar} />);
    await userEvent.click(screen.getByRole("button", { name: "Sí, ya funciona" }));
    await userEvent.click(screen.getByRole("button", { name: "No, sigue igual" }));
    expect(onConfirmar.mock.calls).toEqual([["Sí, ya funciona"], ["No, sigue igual"]]);
  });

  it("sin onConfirmar (no es la última o el caso terminó) no hay botones", () => {
    render(<TarjetaAccion accion={ejecutada} />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("escalamiento", () => {
  it("muestra motivo y plazo", () => {
    render(<TarjetaEscalamiento datos={{ motivo: "el usuario pidió hablar con una persona", prioridad: "P3", plazo:
      "4 horas hábiles", vence_en: null, siguiente_paso: "x", acciones: [] }} />);
    expect(screen.getByText("Tu caso pasó a un técnico de N2")).toBeInTheDocument();
    expect(screen.getByText(/4 horas hábiles/)).toBeInTheDocument();
  });

  it("la ficha N2 muestra las 6 secciones y escapa el texto del usuario", () => {
    const malicioso = '<img src=x onerror="alert(1)"> outlook no abre';
    const { container } = render(
      <FichaEscalamiento ficha={{
        motivo: "solucion_fallida", motivo_texto: "x",
        sintoma: { palabras_del_usuario: malicioso, aplicacion: "outlook" },
        contexto_equipo: { equipo: "PC-1", datos: { disco_libre_gb: 1.2 }, consultas_fallidas: ["licencia"] },
        acciones: [{ accion: "Reparación rápida", estado: "ejecutada", consentimiento_id: "CS-1", aprobacion_id: null,
          motivo_fallo: null }],
        banderas_seguridad: ["autoridad"], siguiente_paso: "Revisar logs", ans: { prioridad: "P3", plazo: "4 h", vence_en: null },
      }} />,
    );
    expect(screen.getByText(malicioso)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    for (const t of ["1. Síntoma", "5. Banderas de seguridad", "6. Siguiente paso sugerido"]) expect(screen.getByText(t)).toBeInTheDocument();
    expect(screen.getByText(/consentimiento CS-1/)).toBeInTheDocument();
    expect(screen.getByText("Consultas fallidas: licencia")).toBeInTheDocument();
  });
});
