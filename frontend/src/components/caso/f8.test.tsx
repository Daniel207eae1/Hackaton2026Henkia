import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { type PropuestaKB, TarjetaPropuesta } from "@/vistas/revisor-kb";

const p: PropuestaKB = {
  id: 7, tipo: "articulo_faltante", articulo_id: null, categoria_id: "teams.no_sincroniza",
  titulo: "Teams no sincroniza: credenciales en caché", borrador_md: '## Pasos\n1. <img src=x onerror="alert(1)"> Borrar',
  casos_soporte: ["HC-0042", "HC-0134"], justificacion: "[clave=faltante|x|y] 7 casos sin artículo", estado: "pendiente",
  revisor_id: null, comentario_revision: null,
};

describe("revisor de KB", () => {
  it("muestra casos, borrador escapado y oculta la clave interna", () => {
    const { container } = render(<TarjetaPropuesta p={p} onAccion={vi.fn()} />);
    expect(screen.getByText("HC-0042, HC-0134")).toBeInTheDocument();
    expect(screen.getByText("7 casos sin artículo")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("devolver exige comentario; publicar no", async () => {
    const onAccion = vi.fn().mockResolvedValue(undefined);
    render(<TarjetaPropuesta p={p} onAccion={onAccion} />);
    const devolver = screen.getByRole("button", { name: "Devolver" });
    expect(devolver).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Comentario para devolver/), "Faltan pasos de verificación");
    await userEvent.click(devolver);
    await userEvent.click(screen.getByRole("button", { name: "Publicar" }));
    expect(onAccion.mock.calls).toEqual([
      ["/api/kb/propuestas/7/devolver", { comentario: "Faltan pasos de verificación" }],
      ["/api/kb/propuestas/7/publicar"],
    ]);
  });
});
