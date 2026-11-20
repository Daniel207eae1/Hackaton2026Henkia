import { Bot, CheckCircle2, CircleDashed, CircleHelp, CircleX, MessagesSquare, Microscope, Stethoscope, User, Wrench } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * Detalle completo de un caso para N2 y auditoría: lo que se entendió, el diagnóstico (hipótesis confirmadas,
 * descartadas y por qué), lo consultado, las acciones con su autorización, la conversación y la línea de tiempo.
 * Todo el texto llega del backend y se muestra escapado (texto de React), nunca como HTML.
 */

export interface HipotesisCaso {
  articulo_id: string;
  titulo?: string;
  hipotesis: string;
  prior?: number;
  casos_historial?: number;
  estado: "pendiente" | "confirmada" | "descartada" | "no_concluyente" | string;
  evidencia?: string[];
  justificacion?: string | null;
}

type Dict = Record<string, unknown>;

const ESTADO_HIP: Record<string, { texto: string; icono: typeof CheckCircle2; clase: string }> = {
  confirmada: { texto: "confirmada", icono: CheckCircle2, clase: "border-success/40 bg-success-soft text-success-foreground" },
  descartada: { texto: "descartada", icono: CircleX, clase: "border-border bg-muted text-muted-foreground line-through decoration-1" },
  no_concluyente: { texto: "no concluyente", icono: CircleHelp, clase: "border-warning/40 bg-warning-soft text-warning-foreground" },
  pendiente: { texto: "sin evaluar", icono: CircleDashed, clase: "border-border bg-card text-muted-foreground" },
};

const ETIQUETAS_SINTOMA: Record<string, string> = {
  descripcion_usuario: "En palabras del usuario",
  palabras_del_usuario: "En palabras del usuario",
  aplicacion: "Aplicación",
  tipo_sintoma: "Tipo de síntoma",
  que_ve: "Lo que ve",
  desde_cuando: "Desde cuándo",
};

const pctTxt = (v?: number) => (typeof v === "number" ? `${Math.round(v * 100)} %` : "—");
const txt = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v));

function Seccion({ titulo, icono: Icono, children, className }: { titulo: string; icono: typeof Bot; children: ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-xl border bg-card p-4 shadow-xs", className)}>
      <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <Icono className="size-4 text-muted-foreground" aria-hidden /> {titulo}
      </h3>
      {children}
    </section>
  );
}

/** Tabla de hipótesis: por qué se confirmó o descartó cada una (lo primero que necesita N2). */
export function TablaHipotesis({ hipotesis, confirmada, probable }: { hipotesis: HipotesisCaso[]; confirmada?: string | null; probable?: boolean }) {
  if (!hipotesis.length) return <p className="text-sm text-muted-foreground">No se evaluaron hipótesis (sin categoría en la KB o caso informativo).</p>;
  const orden = [...hipotesis].sort((a, b) => (b.prior ?? 0) - (a.prior ?? 0));
  return (
    <ol className="space-y-2">
      {orden.map((h) => {
        const e = ESTADO_HIP[h.estado] ?? ESTADO_HIP.pendiente;
        const Icono = e.icono;
        const elegida = h.articulo_id === confirmada;
        return (
          <li key={h.articulo_id} className={cn("rounded-lg border p-3 text-sm", elegida && "border-primary/50 bg-accent/40")}>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline" className={cn("gap-1", e.clase)}>
                <Icono className="size-3" aria-hidden /> {e.texto}
              </Badge>
              <span className="font-medium">{h.hipotesis}</span>
              <span className="font-mono text-xs text-muted-foreground">{h.articulo_id}</span>
              {elegida && (
                <Badge variant="secondary">{probable ? "se probó por ser la más probable" : "solución aplicada"}</Badge>
              )}
              <span className="ml-auto text-xs text-muted-foreground tabular-nums">
                prior {pctTxt(h.prior)}
                {typeof h.casos_historial === "number" && ` · ${h.casos_historial} casos en el historial`}
              </span>
            </div>
            {h.justificacion && <p className="mt-1.5 text-muted-foreground">{h.justificacion}</p>}
            {h.evidencia && h.evidencia.length > 0 && (
              <p className="mt-1 text-xs text-muted-foreground">
                Evidencia citada: <span className="font-mono">{h.evidencia.join(", ")}</span>
              </p>
            )}
          </li>
        );
      })}
    </ol>
  );
}

export function DetalleCaso({ caseId, estado }: { caseId: string; estado: Dict }) {
  const sintoma = (estado.sintoma as Dict) ?? {};
  const d = (estado.diagnostico as Dict) ?? {};
  const hipotesis = ((d.hipotesis as HipotesisCaso[]) ?? (estado.hipotesis as HipotesisCaso[]) ?? []) as HipotesisCaso[];
  const slots = Object.entries((estado.slots as Record<string, { valor: unknown; origen?: string }>) ?? {});
  const fallidas = ((estado.contexto_tecnico as Dict)?.consultas_fallidas as string[]) ?? [];
  const acciones = (estado.acciones as Dict[]) ?? [];
  const capturas = (estado.capturas as Dict[]) ?? [];
  const mensajes = (estado.mensajes as { rol: string; texto: string; hora?: string }[]) ?? [];
  const linea = (estado.linea_tiempo as { hora: string; etapa: string; detalle: string }[]) ?? [];
  const banderas = (((estado.seguridad as Dict)?.banderas as Dict[]) ?? []).map((b) => String(b.bandera));
  const escal = estado.escalamiento as Dict | undefined;
  const cierre = estado.cierre as Dict | undefined;
  const masivo = (estado.masivo as Dict) ?? {};
  const extraccion = d.extraccion as Dict | undefined;
  const resultado = cierre ? `cerrado · ${txt(cierre.resultado)}` : escal ? `escalado · ${txt(escal.motivo_texto ?? escal.motivo)}` : "en curso";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-mono text-xs text-muted-foreground">{caseId}</span>
        <Badge variant={escal ? "destructive" : cierre ? "outline" : "secondary"}>{resultado}</Badge>
        <span className="text-muted-foreground">
          · {txt(estado.persona_id)} · etapa {txt(estado.etapa)} · {txt(estado.turnos)} turnos
        </span>
        {typeof masivo.estado === "string" && !["sin_masivo", "no_evaluado"].includes(masivo.estado) && (
          <Badge variant="outline">masivo: {txt(masivo.estado)}</Badge>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Seccion titulo="Lo que reportó" icono={User}>
          <dl className="space-y-1 text-sm">
            {Object.entries(ETIQUETAS_SINTOMA).map(([k, et]) =>
              sintoma[k] && k !== "palabras_del_usuario" ? (
                <div key={k}>
                  <dt className="inline text-muted-foreground">{et}: </dt>
                  <dd className="inline">{txt(sintoma[k])}</dd>
                </div>
              ) : null,
            )}
          </dl>
        </Seccion>
        <Seccion titulo="Lo que consultó el sistema" icono={Microscope}>
          {slots.length === 0 && fallidas.length === 0 ? (
            <p className="text-sm text-muted-foreground">Sin lecturas del equipo.</p>
          ) : (
            <ul className="space-y-0.5 text-sm">
              {slots.map(([k, v]) => (
                <li key={k}>
                  <span className="text-muted-foreground">{k}:</span> {txt(v.valor)}{" "}
                  {v.origen && <span className="text-xs text-muted-foreground">({v.origen})</span>}
                </li>
              ))}
              {fallidas.length > 0 && <li className="text-warning-foreground">No se pudo consultar: {fallidas.join(", ")}</li>}
            </ul>
          )}
          {extraccion && (
            <p className="mt-2 text-xs text-muted-foreground">
              Registros (extractor en cuarentena): códigos {txt((extraccion.codigos_error as string[])?.join(", "))}
              {extraccion.contiene_instrucciones ? " · ⚠ contenían instrucciones (ignoradas)" : ""}
            </p>
          )}
        </Seccion>
        <Seccion titulo="Resultado" icono={Stethoscope}>
          <dl className="space-y-1 text-sm">
            <div><dt className="inline text-muted-foreground">Categoría: </dt><dd className="inline font-mono text-xs">{txt(d.categoria)}</dd>
              {typeof d.confianza === "number" && <span className="text-xs text-muted-foreground"> ({pctTxt(d.confianza as number)})</span>}</div>
            <div><dt className="inline text-muted-foreground">Rondas de diagnóstico: </dt><dd className="inline">{txt(d.rondas)}</dd></div>
            {escal && <div><dt className="inline text-muted-foreground">Siguiente paso sugerido: </dt><dd className="inline">{txt(escal.siguiente_paso)}</dd></div>}
            {escal && <div><dt className="inline text-muted-foreground">ANS: </dt><dd className="inline">{txt((escal.ans as Dict)?.prioridad)} · vence {txt((escal.ans as Dict)?.vence_en)}</dd></div>}
            {cierre && <div><dt className="inline text-muted-foreground">Solución: </dt><dd className="inline">{txt(cierre.solucion)}</dd></div>}
            {banderas.length > 0 && <div><dt className="inline text-muted-foreground">Banderas de seguridad: </dt><dd className="inline">{banderas.join(", ")}</dd></div>}
          </dl>
        </Seccion>
      </div>

      <Seccion titulo={`Diagnóstico · ${hipotesis.length} hipótesis`} icono={Stethoscope}>
        <TablaHipotesis hipotesis={hipotesis} confirmada={d.confirmada as string | null} probable={Boolean(d.probable)} />
      </Seccion>

      <div className="grid gap-4 lg:grid-cols-2">
        <Seccion titulo="Acciones (con autorización)" icono={Wrench}>
          {acciones.length === 0 ? (
            <p className="text-sm text-muted-foreground">Ninguna acción.</p>
          ) : (
            <ul className="space-y-1.5 text-sm">
              {acciones.map((a, i) => (
                <li key={i} className="rounded-md border px-2.5 py-1.5">
                  <span className="font-medium">{txt(a.tool ?? a.accion)}</span> — {txt(a.estado)}
                  {a.consentimiento_id ? <span className="block font-mono text-xs text-muted-foreground">consentimiento {txt(a.consentimiento_id)}</span> : null}
                  {a.aprobacion_id ? <span className="block font-mono text-xs text-muted-foreground">aprobación N2 {txt(a.aprobacion_id)}</span> : null}
                  {a.motivo_fallo ? <span className="block text-xs text-destructive">Fallo: {txt(a.motivo_fallo)}</span> : null}
                </li>
              ))}
            </ul>
          )}
          {capturas.length > 0 && (
            <>
              <h4 className="mt-3 mb-1 text-xs font-semibold tracking-wide text-muted-foreground uppercase">Capturas ({capturas.length})</h4>
              <ul className="space-y-0.5 text-sm">
                {capturas.map((c, i) => (
                  <li key={i}>
                    Captura {i + 1}: {txt(c.resultado ?? c.estado)}
                    {(c.codigos_ocr as string[] | undefined)?.length ? ` · códigos ${(c.codigos_ocr as string[]).join(", ")}` : ""}
                  </li>
                ))}
              </ul>
            </>
          )}
        </Seccion>
        <Seccion titulo={`Conversación (${mensajes.length})`} icono={MessagesSquare}>
          <ol className="max-h-80 space-y-2 overflow-y-auto pr-1 text-sm">
            {mensajes.map((m, i) => (
              <li key={i} className={cn("rounded-lg px-3 py-2", m.rol === "usuario" ? "ml-6 bg-primary/10" : "mr-6 bg-muted/60")}>
                <span className="mb-0.5 flex items-center gap-1 text-xs text-muted-foreground">
                  {m.rol === "usuario" ? <User className="size-3" aria-hidden /> : <Bot className="size-3" aria-hidden />}
                  {m.rol === "usuario" ? "Usuario" : "Asistente"}
                  {m.hora && <time className="ml-auto font-mono">{m.hora.slice(11, 16)}</time>}
                </span>
                <span className="whitespace-pre-wrap">{m.texto}</span>
              </li>
            ))}
          </ol>
        </Seccion>
      </div>

      <details className="rounded-xl border bg-card shadow-xs">
        <summary className="cursor-pointer px-4 py-3 text-sm font-semibold">Línea de tiempo ({linea.length} hitos)</summary>
        <ol className="relative mx-4 mb-4 space-y-2 border-l-2 border-border pl-5 text-sm">
          {linea.map((h, i) => (
            <li key={i} className="relative">
              <span className="absolute top-1.5 -left-[1.6rem] size-2.5 rounded-full bg-brand-green ring-4 ring-card" aria-hidden />
              <time className="font-mono text-xs text-muted-foreground">{h.hora}</time> · <strong>{h.etapa}</strong> · {h.detalle}
            </li>
          ))}
        </ol>
      </details>
      <details className="rounded-xl border bg-muted/30">
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium">Estado completo (JSON)</summary>
        <pre className="max-h-96 overflow-auto border-t p-3 font-mono text-xs">{JSON.stringify(estado, null, 2)}</pre>
      </details>
    </div>
  );
}
