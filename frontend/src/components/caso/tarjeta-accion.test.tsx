import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TarjetaAccion } from "@/components/caso/tarjeta-accion";
import type { DatosAccion } from "@/lib/mensajes";

const base: DatosAccion = {
  id: "accion-1",
  tool: "limpiar_cache_teams",
  nombre: "Limpiar la caché de Teams",
  descripcion: "Borrar los archivos temporales (caché) de Teams en tu equipo.",
  aviso: "Cerrará Teams y tendrás que volver a iniciar sesión.",
  reversion: "No hace falta revertir.",
  riesgo: "bajo",
  politica: "consentimiento",
  estado: "esperando_consentimiento",
  mensaje: "Pulsa «Autorizar» en la ventana de Soporte TI de tu equipo.",
};

describe("TarjetaAccion", () => {
  it("muestra qué hará, el efecto, la reversión y el riesgo tal como vienen del backend", () => {
    render(<TarjetaAccion accion={base} />);
    expect(screen.getByText(base.nombre)).toBeInTheDocument();
    expect(screen.getByText(base.descripcion)).toBeInTheDocument();
    expect(screen.getByText(base.aviso)).toBeInTheDocument();
    expect(screen.getByText(base.reversion)).toBeInTheDocument();
    expect(screen.getByText("Riesgo bajo")).toBeInTheDocument();
  });

  it("no ofrece un botón de autorizar: la autorización es en la ventana del equipo", () => {
    render(<TarjetaAccion accion={base} onRevisar={() => {}} />);
    expect(screen.getByText("Autoriza en tu equipo")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /autorizar|sí, hazlo|aprobar/i })).toBeNull();
    expect(screen.getByText(/Escribir «sí» en el chat no autoriza nada/)).toBeInTheDocument();
  });

  it("el botón de revisar solo pide consultar el estado", async () => {
    const onRevisar = vi.fn();
    render(<TarjetaAccion accion={base} onRevisar={onRevisar} />);
    await userEvent.click(screen.getByRole("button", { name: "Ya respondí la ventana" }));
    expect(onRevisar).toHaveBeenCalledOnce();
  });

  it("en espera de N2 lo indica y ofrece revisar la aprobación", () => {
    render(
      <TarjetaAccion
        accion={{ ...base, politica: "aprobacion_n2", estado: "esperando_n2", riesgo: "medio" }}
        onRevisar={() => {}}
      />,
    );
    expect(screen.getByText("Requiere N2")).toBeInTheDocument();
    expect(screen.getByText("Esperando aprobación de N2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Revisar la aprobación" })).toBeInTheDocument();
    expect(screen.queryByText("Autoriza en tu equipo")).toBeNull();
  });

  it("estados finales sin botones", () => {
    render(<TarjetaAccion accion={{ ...base, estado: "fallida" }} onRevisar={() => {}} />);
    expect(screen.getByText("No se pudo completar")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("escapa el texto del backend", () => {
    const malicioso = '<img src=x onerror="alert(1)">';
    const { container } = render(<TarjetaAccion accion={{ ...base, aviso: malicioso }} />);
    expect(screen.getByText(malicioso)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});
