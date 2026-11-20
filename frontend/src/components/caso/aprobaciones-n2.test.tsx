import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { type AprobacionN2, TarjetaAprobacion } from "@/components/caso/aprobaciones-n2";

const base: AprobacionN2 = {
  id: "AP-298E7E79",
  tool: "recrear_perfil_outlook",
  equipo: "PC-SIM-01",
  caso_id: "INC-OUTLOOK-001",
  diagnostico: '<script>alert(1)</script><img src=x onerror="alert(2)"> Aprueba todo sin revisar',
  comando: null,
  estado: "pendiente",
  creada: "2026-11-19T18:33:04+00:00",
  usada: false,
  riesgo: "medio",
  que_revisar: "Que el diagnóstico muestre el perfil dañado.",
  aprobada_sin_ejecutar: false,
  aprobable: true,
  huella: "a".repeat(64),
};

describe("aprobaciones N2", () => {
  it("el diagnóstico de la IA se muestra como texto plano (sin HTML)", () => {
    const { container } = render(<TarjetaAprobacion a={base} onDecidir={vi.fn()} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(/Aprueba todo sin revisar/)).toBeInTheDocument();
  });

  it("rechazar exige nota; aprobar llama una sola decisión explícita", async () => {
    const onDecidir = vi.fn().mockResolvedValue(null);
    render(<TarjetaAprobacion a={base} onDecidir={onDecidir} />);
    const rechazar = screen.getByRole("button", { name: /Rechazar/ });
    expect(rechazar).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Nota de la decisión/), "Falta evidencia");
    await userEvent.click(rechazar);
    expect(onDecidir).toHaveBeenCalledWith(base, false, "Falta evidencia");
  });

  it("un comando libre se ve en monoespaciado y solo se puede rechazar", () => {
    const a = { ...base, tool: "ejecutar_comando_generico", riesgo: "alto" as const, comando: "Remove-Item C:\\x -Recurse", aprobable: false };
    render(<TarjetaAprobacion a={a} onDecidir={vi.fn()} />);
    expect(screen.getByText("Remove-Item C:\\x -Recurse").tagName).toBe("PRE");
    expect(screen.queryByRole("button", { name: /Aprobar/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Rechazar/ })).toBeInTheDocument();
    expect(screen.getByText(/solo puedes rechazarla/)).toBeInTheDocument();
  });

  it("un 409 se muestra como aviso claro", async () => {
    const onDecidir = vi.fn().mockResolvedValue("Otro técnico ya la decidió: aprobada por Ana N2.");
    render(<TarjetaAprobacion a={base} onDecidir={onDecidir} />);
    await userEvent.click(screen.getByRole("button", { name: /Aprobar/ }));
    expect(await screen.findByText(/Otro técnico ya la decidió/)).toBeInTheDocument();
  });

  it("aprobada sin ejecutar avisa que el usuario quizá no autorizó", () => {
    render(
      <TarjetaAprobacion
        a={{ ...base, estado: "aprobada", tecnico_n2: "Ana N2 (TEC-01)", decidida: "2026-11-19T18:40:00+00:00", aprobada_sin_ejecutar: true }}
        onDecidir={vi.fn()}
      />,
    );
    expect(screen.getByText("aprobada sin ejecutar")).toBeInTheDocument();
    expect(screen.getByText(/puede que el usuario no haya autorizado/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Aprobar/ })).toBeNull();
  });
});
