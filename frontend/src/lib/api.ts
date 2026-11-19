/** Cliente HTTP del backend. Toda petición lleva `X-Ver-Como` (ADR 0006). */

export const API_URL: string = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";

export type Rol = "colaborador" | "n2" | "revisor_kb";

export interface Persona {
  id: string;
  nombre: string;
  rol: Rol;
  area: string;
  equipo_id: string | null;
  /** Etiqueta del selector (p. ej., «Escenario 1 · Sebastián (outlook)»), si la BD la trae. */
  etiqueta?: string | null;
}

export class ErrorApi extends Error {
  constructor(
    public estado: number,
    mensaje: string,
  ) {
    super(mensaje);
  }
}

export async function pedir<T>(ruta: string, verComo: string | null, init: RequestInit = {}): Promise<T> {
  const cabeceras = new Headers(init.headers);
  if (verComo) cabeceras.set("X-Ver-Como", verComo);
  const resp = await fetch(`${API_URL}${ruta}`, { ...init, headers: cabeceras });
  if (!resp.ok) {
    let detalle = resp.statusText;
    try {
      detalle = ((await resp.json()) as { detail?: string }).detail ?? detalle;
    } catch {
      /* cuerpo no JSON */
    }
    throw new ErrorApi(resp.status, detalle);
  }
  return (await resp.json()) as T;
}
