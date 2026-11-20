import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DetalleCaso, TablaHipotesis } from "@/components/caso/detalle-caso";
import { BarrasHorizontales, ColumnasApiladas } from "@/components/graficas";

describe("detalle del caso para N2", () => {
  const hipotesis = [
    { articulo_id: "KB-SIM-023", hipotesis: "Cola atascada", prior: 0.58, estado: "descartada", justificacion: "La solución no funcionó según el usuario" },
    { articulo_id: "KB-SIM-024", hipotesis: "Predeterminada incorrecta", prior: 0.42, estado: "confirmada", evidencia: ["impresora_predeterminada"] },
  ];

  it("muestra por qué se descartó o confirmó cada hipótesis y cuál se aplicó", () => {
    render(<TablaHipotesis hipotesis={hipotesis} confirmada="KB-SIM-024" />);
    expect(screen.getByText("descartada")).toBeInTheDocument();
    expect(screen.getByText("La solución no funcionó según el usuario")).toBeInTheDocument();
    expect(screen.getByText("solución aplicada")).toBeInTheDocument();
    expect(screen.getByText("impresora_predeterminada")).toBeInTheDocument();
  });

  it("el texto del caso se muestra escapado (sin HTML)", () => {
    const { container } = render(
      <DetalleCaso
        caseId="abc"
        estado={{ mensajes: [{ rol: "usuario", texto: '<img src=x onerror="alert(1)"> no imprime' }], diagnostico: { hipotesis } }}
      />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getAllByText(/no imprime/).length).toBeGreaterThan(0); // conversación (y el JSON crudo, escapado)
    expect(screen.getByText("Diagnóstico · 2 hipótesis")).toBeInTheDocument();
  });
});

describe("gráficas", () => {
  it("barras con valor escrito y tabla accesible", async () => {
    render(<BarrasHorizontales titulo="Casos por aplicación" datos={[{ etiqueta: "Outlook", valor: 7 }, { etiqueta: "Teams", valor: 3 }]} />);
    expect(screen.getByRole("listitem", { name: "Outlook: 7" })).toBeInTheDocument();
    await userEvent.click(screen.getByText("Ver como tabla"));
    expect(screen.getByRole("rowheader", { name: "Teams" })).toBeInTheDocument();
  });

  it("columnas apiladas: leyenda y tooltip con el total al enfocar", async () => {
    render(
      <ColumnasApiladas
        titulo="Casos por día"
        series={[{ clave: "a", nombre: "Resueltos", color: "red" }, { clave: "b", nombre: "Escalados", color: "blue" }]}
        datos={[{ etiqueta: "2026-11-19", valores: { a: 2, b: 1 } }]}
      />,
    );
    expect(screen.getAllByText("Resueltos").length).toBeGreaterThan(0);
    screen.getByRole("button", { name: /2026-11-19: Resueltos 2, Escalados 1/ }).focus();
    expect(await screen.findByRole("status")).toHaveTextContent("Total3");
  });
});
