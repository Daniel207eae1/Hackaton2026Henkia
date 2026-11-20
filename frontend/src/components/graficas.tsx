import { useId, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * Gráficas en SVG propio (sin dependencias): barras horizontales (una serie) y barras apiladas por categoría.
 * Paleta validada (CVD y contraste, claro y oscuro) en `--serie-1..4` de index.css. Como dos colores quedan bajo
 * 3:1 en modo claro, cada gráfica lleva leyenda, etiquetas de valor y su tabla (relief rule).
 * Texto con tokens de texto, nunca del color de la serie.
 */

export interface Serie {
  clave: string;
  nombre: string;
  color: string; // var(--serie-N)
}

function TablaDatos({ titulo, columnas, filas }: { titulo: string; columnas: string[]; filas: (string | number)[][] }) {
  return (
    <details className="mt-2 text-xs">
      <summary className="cursor-pointer text-muted-foreground hover:text-foreground">Ver como tabla</summary>
      <table className="mt-2 w-full text-left">
        <caption className="sr-only">{titulo}</caption>
        <thead>
          <tr className="border-b text-muted-foreground">
            {columnas.map((c, i) => (
              <th key={c} scope="col" className={cn("py-1 pr-3 font-medium", i > 0 && "text-right")}>
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filas.map((f, i) => (
            <tr key={i} className="border-b last:border-0">
              {f.map((v, j) =>
                j === 0 ? (
                  <th key={j} scope="row" className="py-1 pr-3 font-normal">
                    {v}
                  </th>
                ) : (
                  <td key={j} className="py-1 pr-3 text-right tabular-nums">
                    {v}
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

function Leyenda({ series }: { series: Serie[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label="Leyenda">
      {series.map((s) => (
        <li key={s.clave} className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm" style={{ background: s.color }} aria-hidden />
          {s.nombre}
        </li>
      ))}
    </ul>
  );
}

/** Marco común: título, subtítulo y contenido. */
export function MarcoGrafica({
  titulo,
  subtitulo,
  children,
  className,
}: {
  titulo: string;
  subtitulo?: string;
  children: React.ReactNode;
  className?: string;
}) {
  const id = useId();
  return (
    <figure aria-labelledby={id} className={cn("rounded-xl border bg-card p-4 shadow-xs", className)}>
      <figcaption id={id} className="mb-3">
        <span className="text-sm font-semibold">{titulo}</span>
        {subtitulo && <span className="block text-xs text-muted-foreground">{subtitulo}</span>}
      </figcaption>
      {children}
    </figure>
  );
}

/** Una serie, una barra por categoría (de mayor a menor); el valor va escrito al final de cada barra. */
export function BarrasHorizontales({
  titulo,
  subtitulo,
  datos,
  formato = (v) => String(v),
  color = "var(--serie-3)",
  meta,
}: {
  titulo: string;
  subtitulo?: string;
  datos: { etiqueta: string; valor: number }[];
  formato?: (v: number) => string;
  color?: string;
  meta?: { valor: number; etiqueta: string };
}) {
  const [activo, setActivo] = useState<number | null>(null);
  const max = Math.max(...datos.map((d) => d.valor), meta?.valor ?? 0, 0) || 1;
  return (
    <MarcoGrafica titulo={titulo} subtitulo={subtitulo}>
      {datos.length === 0 ? (
        <p className="text-sm text-muted-foreground">Sin datos todavía.</p>
      ) : (
        <div className="relative space-y-1.5" role="list">
          {meta && (
            <div
              className="pointer-events-none absolute inset-y-0 z-10 border-l-2 border-dashed border-foreground/40"
              style={{ left: `calc(9rem + (100% - 9rem - 4.5rem) * ${meta.valor / max})` }}
              aria-hidden
            >
              <span className="absolute -top-4 -translate-x-1/2 rounded bg-card px-1 text-[10px] text-muted-foreground">
                {meta.etiqueta}
              </span>
            </div>
          )}
          {datos.map((d, i) => (
            <div
              key={d.etiqueta}
              role="listitem"
              tabIndex={0}
              aria-label={`${d.etiqueta}: ${formato(d.valor)}`}
              className={cn(
                "grid grid-cols-[9rem_1fr_4.5rem] items-center gap-2 rounded-md px-1 py-0.5 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring",
                activo === i && "bg-muted/60",
              )}
              onMouseEnter={() => setActivo(i)}
              onMouseLeave={() => setActivo(null)}
              onFocus={() => setActivo(i)}
              onBlur={() => setActivo(null)}
            >
              <span className="truncate text-muted-foreground" title={d.etiqueta}>
                {d.etiqueta}
              </span>
              <span className="h-3.5 rounded-r-[4px]" style={{ width: `${(d.valor / max) * 100}%`, minWidth: d.valor > 0 ? 3 : 0, background: color }} />
              <span className="text-right font-medium tabular-nums">{formato(d.valor)}</span>
            </div>
          ))}
        </div>
      )}
      <TablaDatos titulo={titulo} columnas={["Categoría", "Valor"]} filas={datos.map((d) => [d.etiqueta, formato(d.valor)])} />
    </MarcoGrafica>
  );
}

/** Columnas apiladas (p. ej., casos por día según resultado), con 2 px de separación entre segmentos. */
export function ColumnasApiladas({
  titulo,
  subtitulo,
  series,
  datos,
  className,
}: {
  titulo: string;
  subtitulo?: string;
  className?: string;
  series: Serie[];
  datos: { etiqueta: string; valores: Record<string, number> }[];
}) {
  const [activo, setActivo] = useState<number | null>(null);
  const totales = datos.map((d) => series.reduce((s, x) => s + (d.valores[x.clave] ?? 0), 0));
  const max = Math.max(...totales, 1);
  const ancho = 640;
  const alto = 180;
  const izq = 28;
  const abajo = 22;
  const paso = (ancho - izq) / Math.max(datos.length, 1);
  const barra = Math.min(36, paso * 0.6);
  const arriba = 10; // margen para la etiqueta del tope del eje
  const y = (v: number) => ((alto - abajo - arriba) * v) / max;
  const marcas = Array.from(new Set([0, Math.round(max / 2), max]));
  return (
    <MarcoGrafica titulo={titulo} subtitulo={subtitulo} className={className}>
      <Leyenda series={series} />
      {datos.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">Sin datos todavía.</p>
      ) : (
        <div className="relative mt-2">
          <svg viewBox={`0 0 ${ancho} ${alto}`} className="h-auto w-full" role="img" aria-label={titulo}>
            {marcas.map((m) => (
              <g key={m}>
                <line x1={izq} x2={ancho} y1={alto - abajo - y(m)} y2={alto - abajo - y(m)} className="stroke-border" strokeWidth={1} />
                <text x={izq - 6} y={alto - abajo - y(m) + 3} textAnchor="end" className="fill-muted-foreground text-[10px]">
                  {m}
                </text>
              </g>
            ))}
            {datos.map((d, i) => {
              const x = izq + paso * i + (paso - barra) / 2;
              let base = alto - abajo;
              const visibles = series.filter((s) => (d.valores[s.clave] ?? 0) > 0);
              return (
                <g
                  key={d.etiqueta}
                  tabIndex={0}
                  role="button"
                  aria-label={`${d.etiqueta}: ${series.map((s) => `${s.nombre} ${d.valores[s.clave] ?? 0}`).join(", ")}`}
                  className="outline-none focus-visible:[&>rect.hit]:stroke-ring"
                  onMouseEnter={() => setActivo(i)}
                  onMouseLeave={() => setActivo(null)}
                  onFocus={() => setActivo(i)}
                  onBlur={() => setActivo(null)}
                >
                  <rect className="hit fill-transparent" strokeWidth={2} x={izq + paso * i} y={0} width={paso} height={alto - abajo} />
                  {activo === i && <rect x={izq + paso * i} y={0} width={paso} height={alto - abajo} className="fill-muted/60" />}
                  {visibles.map((s, j) => {
                    const h = y(d.valores[s.clave] ?? 0);
                    const tope = j === visibles.length - 1;
                    const top = base - h;
                    const alto_seg = Math.max(h - (j > 0 ? 2 : 0), 1);
                    base -= h;
                    const r = tope ? Math.min(4, alto_seg / 2) : 0;
                    const path = `M${x},${top + alto_seg} V${top + r} Q${x},${top} ${x + r},${top} H${x + barra - r} Q${x + barra},${top} ${x + barra},${top + r} V${top + alto_seg} Z`;
                    return <path key={s.clave} d={path} style={{ fill: s.color }} />;
                  })}
                  {datos.length <= 16 && (
                    <text x={x + barra / 2} y={alto - 6} textAnchor="middle" className="fill-muted-foreground text-[10px]">
                      {d.etiqueta.slice(5)}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
          {activo !== null && (
            <div
              role="status"
              className="pointer-events-none absolute top-0 z-20 min-w-36 rounded-md border bg-popover px-2.5 py-2 text-xs shadow-md"
              style={{ left: `min(calc(${((izq + paso * activo + paso) / ancho) * 100}% + 4px), calc(100% - 9.5rem))` }}
            >
              <p className="mb-1 font-semibold">{datos[activo].etiqueta}</p>
              {series.map((s) => (
                <p key={s.clave} className="flex items-center justify-between gap-3">
                  <span className="flex items-center gap-1.5 text-muted-foreground">
                    <span className="size-2 rounded-sm" style={{ background: s.color }} aria-hidden />
                    {s.nombre}
                  </span>
                  <span className="font-medium tabular-nums">{datos[activo].valores[s.clave] ?? 0}</span>
                </p>
              ))}
              <p className="mt-1 flex justify-between border-t pt-1 font-medium">
                <span>Total</span>
                <span className="tabular-nums">{totales[activo]}</span>
              </p>
            </div>
          )}
        </div>
      )}
      <TablaDatos
        titulo={titulo}
        columnas={["Día", ...series.map((s) => s.nombre), "Total"]}
        filas={datos.map((d, i) => [d.etiqueta, ...series.map((s) => d.valores[s.clave] ?? 0), totales[i]])}
      />
    </MarcoGrafica>
  );
}

/** Proporción en una sola barra (p. ej., resultados de los casos), con el porcentaje escrito en la leyenda. */
export function BarraProporcion({ titulo, subtitulo, series, valores }: {
  titulo: string;
  subtitulo?: string;
  series: Serie[];
  valores: Record<string, number>;
}) {
  const total = series.reduce((s, x) => s + (valores[x.clave] ?? 0), 0);
  const pct = (v: number) => (total ? `${Math.round((v / total) * 100)} %` : "—");
  return (
    <MarcoGrafica titulo={titulo} subtitulo={subtitulo}>
      {total === 0 ? (
        <p className="text-sm text-muted-foreground">Sin casos terminados todavía.</p>
      ) : (
        <div className="flex h-4 w-full gap-[2px] overflow-hidden rounded-[4px]" role="img"
          aria-label={series.map((s) => `${s.nombre} ${valores[s.clave] ?? 0} (${pct(valores[s.clave] ?? 0)})`).join(", ")}>
          {series.map((s) =>
            (valores[s.clave] ?? 0) > 0 ? (
              <span key={s.clave} title={`${s.nombre}: ${valores[s.clave]} (${pct(valores[s.clave])})`}
                style={{ flexGrow: valores[s.clave], background: s.color }} />
            ) : null,
          )}
        </div>
      )}
      <ul className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        {series.map((s) => (
          <li key={s.clave} className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <span className="size-2.5 rounded-sm" style={{ background: s.color }} aria-hidden />
              {s.nombre}
            </span>
            <span className="font-medium tabular-nums">
              {valores[s.clave] ?? 0} · {pct(valores[s.clave] ?? 0)}
            </span>
          </li>
        ))}
      </ul>
    </MarcoGrafica>
  );
}
