import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BandejaMasivos, type IncidenteMasivo } from "@/components/caso/bandeja-masivos";
import { SeguimientoMasivo, TarjetaMasivo } from "@/components/caso/tarjeta-masivo";

const propuesto: IncidenteMasivo = {
  id: "INC-SIM-0002", servicio_id: "teams", categoria_id: "teams.no_sincroniza", titulo: "Posible masivo: Teams",
  estado: "propuesto", origen: "cluster_reportes", mensaje_oficial: null, publicado_en: null, resuelto_en: null,
  confirmado_por: null, regla: { usuarios_distintos: 4, k: 3, umbral: 0.75, ventana_min: 60 }, casos_vinculados: 1,
};

afterEach(() => vi.unstubAllGlobals());

describe("tarjeta de masivo", () => {
  it("cita el mensaje oficial escapado con su hora", () => {
    const malicioso = '<img src=x onerror="alert(1)"> Demoras en el correo';
    const { container } = render(
      <TarjetaMasivo datos={{ estado: "masivo_confirmado", incidente_id: "INC-SIM-0001", servicio_nombre: "correo",
        mensaje_oficial: malicioso, hora_oficial: "19/11 08:10", usuarios_similares: 7 }} />,
    );
    expect(screen.getByText("Incidente general confirmado")).toBeInTheDocument();
    expect(screen.getByText(/Demoras en el correo/)).toBeInTheDocument();
    expect(screen.getByText("Publicado: 19/11 08:10")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("posible masivo: N2 lo está validando", () => {
    render(<TarjetaMasivo datos={{ estado: "posible_masivo", incidente_id: "INC-SIM-0002", servicio_nombre: "Teams",
      mensaje_oficial: null, hora_oficial: null, usuarios_similares: 4 }} />);
    expect(screen.getByText(/4 compañeros reportaron algo parecido/)).toBeInTheDocument();
  });
});

describe("bandeja de posibles masivos (N2)", () => {
  it("confirmar exige mensaje y lo envía; descartar sin cuerpo", async () => {
    const onAccion = vi.fn().mockResolvedValue(undefined);
    render(<BandejaMasivos lista={[propuesto]} onAccion={onAccion} />);
    const confirmar = screen.getByRole("button", { name: "Confirmar masivo" });
    expect(confirmar).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Mensaje oficial/), "Falla general en Teams; trabajamos en ello.");
    await userEvent.click(confirmar);
    await userEvent.click(screen.getByRole("button", { name: "Descartar" }));
    expect(onAccion.mock.calls).toEqual([
      ["/api/n2/masivos/INC-SIM-0002/confirmar", { mensaje: "Falla general en Teams; trabajamos en ello." }],
      ["/api/n2/masivos/INC-SIM-0002/descartar"],
    ]);
  });

  it("publicado: se puede marcar resuelto", () => {
    render(<BandejaMasivos lista={[{ ...propuesto, estado: "publicado", mensaje_oficial: "Falla general." }]} onAccion={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Marcar resuelto y avisar" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirmar masivo" })).toBeNull();
  });
});

describe("seguimiento del incidente vinculado", () => {
  it("al resolverse pregunta «¿ya te funciona?» y envía la respuesta", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      vinculado: true, incidente_id: "INC-SIM-0002", incidente_estado: "resuelto", estado_caso: "masivo_confirmado",
    }), { status: 200 })));
    const onResponder = vi.fn();
    render(<SeguimientoMasivo caseId="abc" verComo="USR-SIM-001" activo ocupado={false} onResponder={onResponder} />);
    await userEvent.click(await screen.findByRole("button", { name: "Sí" }));
    expect(onResponder).toHaveBeenCalledWith("Sí, ya me funciona");
  });
});
