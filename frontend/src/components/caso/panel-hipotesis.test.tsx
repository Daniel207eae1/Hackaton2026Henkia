import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Fuentes, PanelHipotesis } from "@/components/caso/panel-hipotesis";

describe("PanelHipotesis", () => {
  it("muestra hipótesis con prior, estado y justificación (escapada)", () => {
    const malicioso = "<img src=x onerror=alert(1)> disco";
    const { container } = render(
      <PanelHipotesis
        datos={{ categoria: "onedrive.no_sincroniza", hipotesis: [
          { articulo_id: "KB-SIM-014", hipotesis: "Disco local lleno", prior: 0.53, estado: "confirmada", justificacion: malicioso },
          { articulo_id: "KB-SIM-015", hipotesis: "Conflictos", prior: 0.33, estado: "descartada", justificacion: null },
        ] }}
      />,
    );
    expect(screen.getByText("Confirmada")).toBeInTheDocument();
    expect(screen.getByText("Descartada")).toBeInTheDocument();
    expect(screen.getByText(/probabilidad previa 53 %/)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("no se muestra sin hipótesis", () => {
    const { container } = render(<PanelHipotesis datos={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("Fuentes cita el artículo de la KB", () => {
    render(<Fuentes datos={{ fuentes: [{ articulo_id: "KB-SIM-025", titulo: "Word se cierra", seccion: "pasos" }] }} />);
    expect(screen.getByText(/KB-SIM-025 · Word se cierra/)).toBeInTheDocument();
  });
});
