import { BarChart3, FlaskConical, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { BarraProporcion, BarrasHorizontales, ColumnasApiladas, type Serie } from "@/components/graficas";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Cargando, EncabezadoVista, EstadoVacio } from "@/components/vista";
import { pedir, type Persona } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Guion {
  id: string;
  titulo: string;
  red_team: boolean;
  resultado: string;
  esperado: string[] | null;
  articulos_confirmados: string[];
  articulo_esperado: string | null;
  acciones: string[];
  acciones_sin_token: string[];
  banderas: string[];
  preguntas: number;
  turnos: number;
  segundos: number;
  costo_usd: number;
  ok: boolean;
  error: string | null;
}

interface Resumen {
  guiones: number;
  aciertos: number;
  tasa_acierto: number | null;
  fcr: number | null;
  precision_diagnostico: number | null;
  preguntas_promedio: number | null;
  acciones_sin_token: number;
  inyecciones_resistidas: number | null;
  segundos_p50: number | null;
  segundos_p95: number | null;
  costo_total_usd: number;
  costo_por_caso_usd: number | null;
  costo_por_agente_usd: Record<string, number>;
  modulo_a: { faltantes: string[]; desactualizados: string[]; ok: boolean } | null;
}

export interface RespuestaMetricas {
  operacion: {
    dias: number;
    casos: number;
    resueltos: number;
    escalados: number;
    vinculados_masivo: number;
    preguntas_promedio: number;
    acciones_sin_token: number;
    banderas: number;
    escalamientos_completos: number;
    escalamientos_evaluados: number;
    valoraciones: number;
    satisfaccion: number | null;
    fcr: number | null;
    por_dia?: { dia: string; resueltos: number; escalados: number; vinculados_masivo: number; abiertos: number }[];
    por_aplicacion?: Record<string, number>;
  };
  evaluacion: { experimento: string; fecha: string; resumen: Resumen; guiones: Guion[] } | null;
}

/** Resultado de un caso → serie (orden fijo de la paleta validada). */
const SERIES_RESULTADO: Serie[] = [
  { clave: "resueltos", nombre: "Resueltos", color: "var(--serie-1)" },
  { clave: "escalados", nombre: "Escalados a N2", color: "var(--serie-2)" },
  { clave: "vinculados_masivo", nombre: "Incidente general", color: "var(--serie-3)" },
  { clave: "abiertos", nombre: "En curso", color: "var(--serie-4)" },
];
const NOMBRE_APP: Record<string, string> = {
  outlook: "Outlook", teams: "Teams", excel: "Excel", word: "Word", onedrive: "OneDrive", impresora: "Impresión",
  office: "Office", powerpoint: "PowerPoint",
};

const seg = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${Math.round(v * 10) / 10} s`);
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)} %`);
const usd = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `US$ ${v.toFixed(4)}`);

/** Fila meta vs. valor: el estado se marca con texto (no solo color). */
function Fila({ nombre, valor, meta, cumple }: { nombre: string; valor: string; meta?: string; cumple?: boolean | null }) {
  return (
    <tr className="border-b transition-colors last:border-0 hover:bg-muted/40">
      <th scope="row" className="py-2.5 pr-4 pl-4 text-left font-normal">
        {nombre}
      </th>
      <td className="py-2.5 pr-4 text-right font-semibold tabular-nums">{valor}</td>
      <td className="py-2.5 pr-4 text-muted-foreground">{meta ?? ""}</td>
      <td className="py-2.5 pr-4">
        {cumple === undefined || cumple === null ? null : cumple ? (
          <Badge variant="outline" className="border-success/40 bg-success-soft text-success-foreground">
            cumple
          </Badge>
        ) : (
          <Badge variant="destructive">no cumple</Badge>
        )}
      </td>
    </tr>
  );
}

/** Tarjeta de indicador: valor grande, meta y estado con texto (no solo color). */
function Indicador({ nombre, valor, meta, cumple }: { nombre: string; valor: string; meta?: string; cumple?: boolean | null }) {
  return (
    <div
      className={cn(
        "rounded-xl border bg-card p-4 shadow-xs",
        cumple === true && "border-success/40",
        cumple === false && "border-destructive/40",
      )}
    >
      <p className="text-xs font-medium text-muted-foreground">{nombre}</p>
      <p className="mt-1 font-display text-4xl leading-none font-semibold tabular-nums">{valor}</p>
      {meta && (
        <p className="mt-2 text-xs text-muted-foreground">
          Meta {meta}
          {cumple !== undefined && cumple !== null && (
            <span className={cn("ml-1 font-medium", cumple ? "text-success-foreground" : "text-destructive")}>
              · {cumple ? "en meta" : "fuera de meta"}
            </span>
          )}
        </p>
      )}
    </div>
  );
}

const TABLA = "w-full text-sm";
const MARCO = "overflow-x-auto rounded-xl border bg-card shadow-xs";
const CABECERA = "border-b bg-muted/50 text-left text-xs tracking-wide text-muted-foreground uppercase";

export function TablaEvaluacion({ ev }: { ev: NonNullable<RespuestaMetricas["evaluacion"]> }) {
  const r = ev.resumen;
  return (
    <section aria-labelledby="titulo-eval" className="space-y-3">
      <h2 id="titulo-eval" className="flex items-center gap-2 text-base font-semibold">
        <FlaskConical className="size-4 text-muted-foreground" aria-hidden /> Último experimento · {ev.experimento}
      </h2>
      <p className="text-sm text-muted-foreground">
        {r.guiones} guiones (jurado + red team) con usuario y equipo simulados · {new Date(ev.fecha).toLocaleString()}
      </p>
      <div className={MARCO}>
        <table className={TABLA}>
          <thead>
            <tr className={CABECERA}>
              <th scope="col" className="py-2 pr-4 pl-4 font-medium">Métrica</th>
              <th scope="col" className="py-2 pr-4 text-right font-medium">Valor</th>
              <th scope="col" className="py-2 pr-4 font-medium">Meta</th>
              <th scope="col" className="py-2 pr-4"><span className="sr-only">Estado</span></th>
            </tr>
          </thead>
          <tbody>
            <Fila nombre="Guiones que pasan todos sus chequeos" valor={`${r.aciertos}/${r.guiones} (${pct(r.tasa_acierto)})`} />
            <Fila nombre="Resolución en el primer contacto (FCR)" valor={pct(r.fcr)} meta="≥ 70 %" cumple={r.fcr === null ? null : r.fcr >= 0.7} />
            <Fila nombre="Precisión del diagnóstico" valor={pct(r.precision_diagnostico)} meta="≥ 90 %" cumple={r.precision_diagnostico === null ? null : r.precision_diagnostico >= 0.9} />
            <Fila nombre="Preguntas por caso (promedio)" valor={String(r.preguntas_promedio ?? "—")} meta="≤ 3" cumple={r.preguntas_promedio === null ? null : r.preguntas_promedio <= 3} />
            <Fila nombre="Acciones sin token" valor={String(r.acciones_sin_token)} meta="0" cumple={r.acciones_sin_token === 0} />
            <Fila nombre="Inyecciones resistidas" valor={pct(r.inyecciones_resistidas)} meta="100 %" cumple={r.inyecciones_resistidas === null ? null : r.inyecciones_resistidas === 1} />
            <Fila nombre="Duración del caso p50 / p95" valor={`${seg(r.segundos_p50)} / ${seg(r.segundos_p95)}`} />
            <Fila nombre="Costo de referencia por caso" valor={usd(r.costo_por_caso_usd)} />
            {r.modulo_a && (
              <Fila
                nombre="Módulo A: faltante + correcciones detectadas"
                valor={`${r.modulo_a.faltantes.length} + ${r.modulo_a.desactualizados.length}`}
                meta="1 + 2 (kit)"
                cumple={r.modulo_a.ok}
              />
            )}
          </tbody>
        </table>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <BarrasHorizontales
          titulo="Duración por guion"
          subtitulo={`Segundos de punta a punta · p50 ${seg(r.segundos_p50)}`}
          datos={[...ev.guiones].sort((a, b) => b.segundos - a.segundos).map((g) => ({ etiqueta: `${g.id} · ${g.titulo}`, valor: g.segundos }))}
          formato={seg}
        />
        <BarrasHorizontales
          titulo="Preguntas al usuario por guion"
          subtitulo="Meta: 3 o menos por caso"
          datos={[...ev.guiones].sort((a, b) => b.preguntas - a.preguntas).map((g) => ({ etiqueta: `${g.id} · ${g.titulo}`, valor: g.preguntas }))}
          meta={{ valor: 3, etiqueta: "meta 3" }}
        />
      </div>
      <BarrasHorizontales
        titulo="Costo de referencia por agente"
        subtitulo={`Total del experimento ${usd(r.costo_total_usd)} · por caso ${usd(r.costo_por_caso_usd)}`}
        datos={Object.entries(r.costo_por_agente_usd).sort((a, b) => b[1] - a[1]).map(([agente, v]) => ({ etiqueta: agente, valor: v }))}
        formato={(v) => usd(v)}
      />

      <h3 className="pt-2 text-sm font-semibold">Detalle por guion</h3>
      <div className={MARCO}>
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className={CABECERA}>
              <th scope="col" className="py-2 pr-3 pl-4">Guion</th>
              <th scope="col" className="py-2 pr-3">Resultado (esperado)</th>
              <th scope="col" className="py-2 pr-3">Diagnóstico</th>
              <th scope="col" className="py-2 pr-3">Acciones</th>
              <th scope="col" className="py-2 pr-3 text-right">Preg.</th>
              <th scope="col" className="py-2 pr-3 text-right">s</th>
              <th scope="col" className="py-2">Estado</th>
            </tr>
          </thead>
          <tbody>
            {ev.guiones.map((g) => (
              <tr key={g.id} className="border-b align-top transition-colors last:border-0 hover:bg-muted/40">
                <td className="py-2 pr-3 pl-4">
                  <span className="font-mono text-xs">{g.id}</span> {g.titulo}
                  {g.banderas.length > 0 && <span className="block text-xs text-muted-foreground">banderas: {g.banderas.join(", ")}</span>}
                </td>
                <td className="py-2 pr-3">
                  {g.resultado} <span className="text-muted-foreground">({(g.esperado ?? []).join(" / ")})</span>
                </td>
                <td className="py-2 pr-3">
                  {g.articulo_esperado ? `${g.articulos_confirmados.join(", ") || "—"} (esperado ${g.articulo_esperado})` : "—"}
                </td>
                <td className="py-2 pr-3">{g.acciones.join(", ") || "—"}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{g.preguntas}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{g.segundos}</td>
                <td className="py-2">
                  {g.ok ? (
                    <Badge variant="outline" className="border-success/40 bg-success-soft text-success-foreground">
                      pasa
                    </Badge>
                  ) : (
                    <Badge variant="destructive">falla</Badge>
                  )}
                  {g.error && <span className="block text-xs text-destructive">{g.error}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function Metricas({ persona }: { persona: Persona }) {
  const [datos, setDatos] = useState<RespuestaMetricas | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const cargar = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    let vigente = true;
    pedir<RespuestaMetricas>("/api/metricas", persona.id)
      .then((d) => vigente && (setDatos(d), setError(null)))
      .catch((e: Error) => vigente && setError(e.message));
    return () => {
      vigente = false;
    };
  }, [persona.id, version]);

  const op = datos?.operacion;
  return (
    <div className="space-y-6">
      <EncabezadoVista
        titulo="Métricas"
        icono={BarChart3}
        descripcion="Operación real del asistente y resultado del último experimento de evaluación."
        acciones={
          <Button variant="outline" size="sm" onClick={cargar}>
            <RefreshCw aria-hidden /> Actualizar
          </Button>
        }
      />
      {error && (
        <Alert variant="destructive" className="bg-danger-soft">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {!datos ? (
        error ? null : <Cargando />
      ) : (
        <>
          {op && (
            <section aria-labelledby="titulo-op" className="space-y-2">
              <h2 id="titulo-op" className="flex items-center gap-2 text-base font-semibold">
                <BarChart3 className="size-4 text-muted-foreground" aria-hidden /> Operación real · últimos {op.dias} días
              </h2>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <Indicador nombre="Casos atendidos" valor={String(op.casos)} />
                <Indicador nombre="Resolución en el primer contacto" valor={pct(op.fcr)} meta="≥ 70 %" cumple={op.fcr === null ? null : op.fcr >= 0.7} />
                <Indicador nombre="Preguntas por caso" valor={op.preguntas_promedio.toFixed(1)} meta="≤ 3" cumple={op.preguntas_promedio <= 3} />
                <Indicador nombre="Acciones sin token" valor={String(op.acciones_sin_token)} meta="0" cumple={op.acciones_sin_token === 0} />
              </div>
              <div className="grid gap-3 lg:grid-cols-3">
                <ColumnasApiladas
                  className="lg:col-span-2"
                  titulo="Casos por día"
                  subtitulo="Según cómo terminó cada caso"
                  series={SERIES_RESULTADO}
                  datos={(op.por_dia ?? []).map(({ dia, ...valores }) => ({ etiqueta: dia, valores }))}
                />
                <div className="space-y-3">
                  <BarraProporcion
                    titulo="Resultado de los casos"
                    series={SERIES_RESULTADO}
                    valores={{ resueltos: op.resueltos, escalados: op.escalados, vinculados_masivo: op.vinculados_masivo,
                      abiertos: Math.max(op.casos - op.resueltos - op.escalados - op.vinculados_masivo, 0) }}
                  />
                  <BarrasHorizontales
                    titulo="Casos por aplicación"
                    datos={Object.entries(op.por_aplicacion ?? {}).sort((a, b) => b[1] - a[1])
                      .map(([app, n]) => ({ etiqueta: NOMBRE_APP[app] ?? app, valor: n }))}
                  />
                </div>
              </div>
              <div className={MARCO}>
                <table className={TABLA}>
                  <tbody>
                    <Fila nombre="Resueltos / escalados / vinculados a masivo" valor={`${op.resueltos} / ${op.escalados} / ${op.vinculados_masivo}`} />
                    <Fila nombre="Banderas de seguridad" valor={String(op.banderas)} />
                    <Fila
                      nombre="Satisfacción del usuario (le sirvió la atención)"
                      valor={`${pct(op.satisfaccion)} de ${op.valoraciones} valoraciones`}
                    />
                    <Fila nombre="Escalamientos completos (N2 no repreguntó)" valor={`${op.escalamientos_completos}/${op.escalamientos_evaluados}`} />
                  </tbody>
                </table>
              </div>
            </section>
          )}
          {datos.evaluacion ? (
            <TablaEvaluacion ev={datos.evaluacion} />
          ) : (
            <EstadoVacio icono={FlaskConical} titulo="Aún no hay experimentos.">
              Córrelo con <code className="rounded bg-muted px-1 font-mono text-xs">docker compose exec api python -m evaluacion.ejecutar</code>.
            </EstadoVacio>
          )}
        </>
      )}
    </div>
  );
}
