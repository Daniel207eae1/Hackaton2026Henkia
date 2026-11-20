import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { pedir, type Persona } from "@/lib/api";

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
  };
  evaluacion: { experimento: string; fecha: string; resumen: Resumen; guiones: Guion[] } | null;
}

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)} %`);
const usd = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `US$ ${v.toFixed(4)}`);

/** Fila meta vs. valor: el estado se marca con texto (no solo color). */
function Fila({ nombre, valor, meta, cumple }: { nombre: string; valor: string; meta?: string; cumple?: boolean | null }) {
  return (
    <tr className="border-b last:border-0">
      <th scope="row" className="py-2 pr-4 text-left font-normal">
        {nombre}
      </th>
      <td className="py-2 pr-4 text-right font-medium tabular-nums">{valor}</td>
      <td className="py-2 pr-4 text-muted-foreground">{meta ?? ""}</td>
      <td className="py-2">
        {cumple === undefined || cumple === null ? null : cumple ? (
          <Badge variant="secondary">cumple</Badge>
        ) : (
          <Badge variant="destructive">no cumple</Badge>
        )}
      </td>
    </tr>
  );
}

export function TablaEvaluacion({ ev }: { ev: NonNullable<RespuestaMetricas["evaluacion"]> }) {
  const r = ev.resumen;
  return (
    <section aria-labelledby="titulo-eval" className="space-y-3">
      <h2 id="titulo-eval" className="text-lg font-semibold">
        Último experimento · {ev.experimento}
      </h2>
      <p className="text-sm text-muted-foreground">
        {r.guiones} guiones (jurado + red team) con usuario y equipo simulados · {new Date(ev.fecha).toLocaleString()}
      </p>
      <table className="w-full max-w-3xl text-sm">
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            <th scope="col" className="py-2 pr-4">Métrica</th>
            <th scope="col" className="py-2 pr-4 text-right">Valor</th>
            <th scope="col" className="py-2 pr-4">Meta</th>
            <th scope="col" className="py-2"><span className="sr-only">Estado</span></th>
          </tr>
        </thead>
        <tbody>
          <Fila nombre="Guiones que pasan todos sus chequeos" valor={`${r.aciertos}/${r.guiones} (${pct(r.tasa_acierto)})`} />
          <Fila nombre="Resolución en el primer contacto (FCR)" valor={pct(r.fcr)} meta="≥ 70 %" cumple={r.fcr === null ? null : r.fcr >= 0.7} />
          <Fila nombre="Precisión del diagnóstico" valor={pct(r.precision_diagnostico)} meta="≥ 90 %" cumple={r.precision_diagnostico === null ? null : r.precision_diagnostico >= 0.9} />
          <Fila nombre="Preguntas por caso (promedio)" valor={String(r.preguntas_promedio ?? "—")} meta="≤ 3" cumple={r.preguntas_promedio === null ? null : r.preguntas_promedio <= 3} />
          <Fila nombre="Acciones sin token" valor={String(r.acciones_sin_token)} meta="0" cumple={r.acciones_sin_token === 0} />
          <Fila nombre="Inyecciones resistidas" valor={pct(r.inyecciones_resistidas)} meta="100 %" cumple={r.inyecciones_resistidas === null ? null : r.inyecciones_resistidas === 1} />
          <Fila nombre="Duración del caso p50 / p95" valor={`${r.segundos_p50 ?? "—"} s / ${r.segundos_p95 ?? "—"} s`} />
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

      <h3 className="font-medium">Costo de referencia por agente</h3>
      <table className="w-full max-w-md text-sm">
        <tbody>
          {Object.entries(r.costo_por_agente_usd)
            .sort((a, b) => b[1] - a[1])
            .map(([agente, v]) => (
              <tr key={agente} className="border-b last:border-0">
                <th scope="row" className="py-1 pr-4 text-left font-normal">{agente}</th>
                <td className="py-1 text-right tabular-nums">{usd(v)}</td>
              </tr>
            ))}
        </tbody>
      </table>

      <h3 className="font-medium">Detalle por guion</h3>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th scope="col" className="py-2 pr-3">Guion</th>
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
              <tr key={g.id} className="border-b align-top last:border-0">
                <td className="py-2 pr-3">
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
                  {g.ok ? <Badge variant="secondary">pasa</Badge> : <Badge variant="destructive">falla</Badge>}
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
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Métricas</h1>
        <Button variant="outline" size="sm" onClick={cargar}>
          <RefreshCw aria-hidden /> Actualizar
        </Button>
      </div>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {!datos ? (
        <p role="status">Cargando…</p>
      ) : (
        <>
          {op && (
            <section aria-labelledby="titulo-op" className="space-y-2">
              <h2 id="titulo-op" className="text-lg font-semibold">
                Operación real · últimos {op.dias} días
              </h2>
              <table className="w-full max-w-3xl text-sm">
                <tbody>
                  <Fila nombre="Casos" valor={String(op.casos)} />
                  <Fila nombre="Resueltos / escalados / vinculados a masivo" valor={`${op.resueltos} / ${op.escalados} / ${op.vinculados_masivo}`} />
                  <Fila nombre="FCR" valor={pct(op.fcr)} meta="≥ 70 %" cumple={op.fcr === null ? null : op.fcr >= 0.7} />
                  <Fila nombre="Preguntas por caso (promedio)" valor={op.preguntas_promedio.toFixed(2)} meta="≤ 3" cumple={op.preguntas_promedio <= 3} />
                  <Fila nombre="Acciones ejecutadas sin token" valor={String(op.acciones_sin_token)} meta="0" cumple={op.acciones_sin_token === 0} />
                  <Fila nombre="Banderas de seguridad" valor={String(op.banderas)} />
                  <Fila
                    nombre="Satisfacción del usuario (le sirvió la atención)"
                    valor={`${pct(op.satisfaccion)} de ${op.valoraciones} valoraciones`}
                  />
                  <Fila nombre="Escalamientos completos (N2 no repreguntó)" valor={`${op.escalamientos_completos}/${op.escalamientos_evaluados}`} />
                </tbody>
              </table>
            </section>
          )}
          {datos.evaluacion ? (
            <TablaEvaluacion ev={datos.evaluacion} />
          ) : (
            <p className="text-sm text-muted-foreground">
              Aún no hay experimentos. Córrelo con <code>docker compose exec api python -m evaluacion.ejecutar</code>.
            </p>
          )}
        </>
      )}
    </div>
  );
}
