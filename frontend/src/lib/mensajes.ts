/** Tipos de las partes `data-*` que emite el backend (ADR 0002). */
import type { UIMessage } from "ai";

export type EstadoRevision = "ok" | "anomalia" | "fallo" | "pendiente" | "no_disponible";

export interface DatosRevisando {
  id: string;
  estado: EstadoRevision;
  texto: string;
}

export interface DatosEtapa {
  etapa: string;
}

export interface DatosCaso {
  case_id: string;
  etapa: string | null;
  traza_url: string | null;
}

export type EstadoAccion =
  | "propuesta"
  | "esperando_n2"
  | "aprobada_n2"
  | "esperando_consentimiento"
  | "autorizada"
  | "ejecutando"
  | "ejecutada"
  | "rechazada"
  | "rechazada_n2"
  | "expirada"
  | "fallida";

export interface DatosAccion {
  id: string;
  tool: string;
  nombre: string;
  descripcion: string;
  aviso: string;
  reversion: string;
  riesgo: string;
  politica: "consentimiento" | "aprobacion_n2";
  estado: EstadoAccion;
  mensaje: string;
}

export interface DatosEscalamiento {
  motivo: string;
  prioridad: string;
  plazo: string;
  vence_en: string | null;
  siguiente_paso: string;
  acciones: string[];
}

export interface DatosCierre {
  resultado: string;
  solucion: string | null;
}

export type EstadoHipotesis = "pendiente" | "confirmada" | "descartada" | "no_concluyente";

export interface DatosHipotesis {
  categoria: string | null;
  hipotesis: { articulo_id: string; hipotesis: string; prior: number; estado: EstadoHipotesis; justificacion: string | null }[];
}

export interface DatosFuentes {
  fuentes: { articulo_id: string; titulo: string; seccion: string }[];
}

export interface DatosMasivo {
  estado: string;
  incidente_id: string | null;
  servicio_nombre: string | null;
  mensaje_oficial: string | null;
  hora_oficial: string | null;
  usuarios_similares: number | null;
  incidente_estado?: string | null;
}

export interface DatosCaptura {
  nombre: string;
  estado: "procesada" | "no_concluyente" | "rechazada";
  codigo_error: string | null;
  aplicacion: string;
  mensaje_resumido: string | null;
  contiene_instrucciones: boolean;
  motivo: string | null;
}

export type PartesDatos = {
  masivo: DatosMasivo;
  captura: DatosCaptura;
  etapa: DatosEtapa;
  revisando: DatosRevisando;
  caso: DatosCaso;
  accion: DatosAccion;
  escalamiento: DatosEscalamiento;
  cierre: DatosCierre;
  hipotesis: DatosHipotesis;
  fuentes: DatosFuentes;
};

export type MensajeCaso = UIMessage<unknown, PartesDatos>;

/** Nodos del grafo §3.5 en el orden en que se muestran en el indicador. */
export const ETAPAS: { id: string; nombre: string }[] = [
  { id: "Recepcion", nombre: "Recepción" },
  { id: "Captura", nombre: "Captura" },
  { id: "Interpretacion", nombre: "Interpretación" },
  { id: "Contexto", nombre: "Contexto" },
  { id: "ChequeoMasivo", nombre: "¿Masivo?" },
  { id: "InformarMasivo", nombre: "Masivo" },
  { id: "Aclaracion", nombre: "Aclaración" },
  { id: "Hipotesis", nombre: "Hipótesis" },
  { id: "Prueba", nombre: "Prueba" },
  { id: "Decision", nombre: "Decisión" },
  { id: "AprobacionN2", nombre: "Aprobación N2" },
  { id: "Consentimiento", nombre: "Consentimiento" },
  { id: "Ejecucion", nombre: "Ejecución" },
  { id: "Verificacion", nombre: "Verificación" },
  { id: "Cierre", nombre: "Cierre" },
  { id: "Escalar", nombre: "Escalado a N2" },
];

export function ultimaParte<K extends keyof PartesDatos>(
  mensajes: MensajeCaso[],
  tipo: K,
): PartesDatos[K] | null {
  for (let i = mensajes.length - 1; i >= 0; i--) {
    const partes = mensajes[i].parts;
    for (let j = partes.length - 1; j >= 0; j--) {
      const p = partes[j];
      if (p.type === `data-${tipo}`) return (p as unknown as { data: PartesDatos[K] }).data;
    }
  }
  return null;
}

/** Todas las líneas de «Lo que estoy revisando», la más reciente por id. */
export function lineasRevisando(mensajes: MensajeCaso[]): DatosRevisando[] {
  const porId = new Map<string, DatosRevisando>();
  for (const m of mensajes)
    for (const p of m.parts) if (p.type === "data-revisando") porId.set(p.data.id, p.data);
  return [...porId.values()];
}

export function textoDe(m: MensajeCaso): string {
  return m.parts.map((p) => (p.type === "text" ? p.text : "")).join("");
}

/** Acciones de diagnóstico: se ejecutan, pero no son una solución (no preguntan «¿ya te funciona?»). */
export const ACCIONES_DIAGNOSTICO = new Set(["leer_logs_aplicacion"]);

/** id de la tarjeta que pregunta «¿ya te funciona?»: la última SOLUCIÓN ejecutada, y solo si está en la respuesta
 * más reciente (si la conversación siguió, los botones ya no aplican y confundirían). */
export function idUltimaEjecutada(mensajes: MensajeCaso[]): string | undefined {
  const ultimo = mensajes.at(-1);
  if (!ultimo || ultimo.role !== "assistant") return undefined;
  let id: string | undefined;
  for (const p of ultimo.parts)
    if (p.type === "data-accion" && p.data.estado === "ejecutada" && !ACCIONES_DIAGNOSTICO.has(p.data.tool))
      id = p.id ?? p.data.id;
  return id;
}
