/** Nombres legibles y posiciones fijas de los nodos del grafo (sin librerías de layout). */
import type { EstadoNodo } from "@/lib/monitor";

export const NOMBRE_NODO: Record<string, string> = {
  __start__: "Inicio",
  __end__: "Fin",
  Recepcion: "Recepción",
  Captura: "Captura",
  RespuestaPolitica: "Respuesta de política",
  Interpretacion: "Interpretación",
  Contexto: "Contexto",
  ChequeoMasivo: "Chequeo de masivo",
  InformarMasivo: "Informar masivo",
  Aclaracion: "Aclaración",
  Hipotesis: "Hipótesis",
  Prueba: "Prueba",
  Decision: "Decisión",
  Guia: "Guía",
  AprobacionN2: "Aprobación N2",
  Consentimiento: "Consentimiento",
  Ejecucion: "Ejecución",
  Verificacion: "Verificación",
  Confirmacion: "Confirmación",
  Reversion: "Reversión",
  Cierre: "Cierre",
  Escalar: "Escalar a N2",
  CasoTerminado: "Caso terminado",
};

export function nombreNodo(id: string): string {
  return NOMBRE_NODO[id] ?? id;
}

const X = 210;
const Y = 120;

/** Orden del flujo: Recepción → Captura → Interpretación → Contexto → Chequeo de masivo → Hipótesis → Decisión → … */
const POSICIONES: Record<string, { x: number; y: number }> = {
  __start__: { x: 0, y: Y },
  Recepcion: { x: X, y: Y },
  CasoTerminado: { x: X, y: 0 },
  Captura: { x: 2 * X, y: Y },
  RespuestaPolitica: { x: 2 * X, y: 0 },
  Confirmacion: { x: 3 * X, y: 0 },
  Interpretacion: { x: 3 * X, y: Y },
  Contexto: { x: 4 * X, y: Y },
  InformarMasivo: { x: 5 * X, y: 0 },
  ChequeoMasivo: { x: 5 * X, y: Y },
  Hipotesis: { x: 6 * X, y: Y },
  Guia: { x: 7 * X, y: Y },
  Decision: { x: 2 * X, y: 3 * Y },
  Aclaracion: { x: 2 * X, y: 4 * Y },
  AprobacionN2: { x: 3 * X, y: 3 * Y },
  Consentimiento: { x: 4 * X, y: 3 * Y },
  Ejecucion: { x: 5 * X, y: 3 * Y },
  Verificacion: { x: 6 * X, y: 3 * Y },
  Reversion: { x: 6 * X, y: 4 * Y },
  Cierre: { x: 8 * X, y: Y },
  Escalar: { x: 7 * X, y: 3 * Y },
  __end__: { x: 9 * X, y: 2 * Y },
};

export function tienePosicion(id: string): boolean {
  return id in POSICIONES;
}

/** Posición fija por etapa; un nodo desconocido cae en una cuadrícula debajo del flujo. */
export function posicionNodo(id: string, indiceDesconocido: number): { x: number; y: number } {
  return POSICIONES[id] ?? { x: (indiceDesconocido % 8) * X, y: 6 * Y + Math.floor(indiceDesconocido / 8) * Y };
}

export const TEXTO_ESTADO: Record<EstadoNodo, string> = {
  inactivo: "inactivo",
  activo: "activo",
  completado: "completado",
  espera: "en espera humana",
  error: "error",
};
