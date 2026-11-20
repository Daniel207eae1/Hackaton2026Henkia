import { BookOpen, Search, ShieldAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Cargando, EncabezadoVista, EstadoVacio } from "@/components/vista";
import { pedir, type Persona } from "@/lib/api";
import { cn } from "@/lib/utils";

export interface ArticuloKB {
  id: string;
  titulo: string;
  categoria_id: string | null;
  versiones_aplicables: string[];
  fecha_actualizacion: string | null;
  estado: string | null;
  marcado_inyeccion: boolean;
  casos_historial: number;
  receta: {
    hipotesis: string | null;
    tipo_solucion: string | null;
    accion_catalogo: string | null;
    pruebas: string[];
    criterio_confirmacion: string | null;
    criterio_descarte: string | null;
  };
  secciones?: Record<string, string>;
}

const SOLUCION: Record<string, string> = {
  accion: "Acción del catálogo (con consentimiento)",
  guia: "Guía paso a paso para el usuario",
  escalar: "Escalar a N2",
  derivar: "Derivar (fuera de alcance)",
};
const SECCIONES: [string, string][] = [
  ["resumen", "Resumen"],
  ["sintoma", "Síntoma"],
  ["causa", "Causa"],
  ["pasos", "Pasos"],
  ["verificacion", "Verificación"],
];

/** Artículo completo. El texto de la KB es dato externo: siempre como texto escapado, nunca HTML ni Markdown. */
function DetalleArticulo({ a }: { a: ArticuloKB }) {
  const r = a.receta;
  return (
    <article className="space-y-4 rounded-xl border bg-card p-5 shadow-xs">
      <header className="space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs text-muted-foreground">{a.id}</span>
          <Badge variant="outline">{a.categoria_id}</Badge>
          <Badge variant={a.estado === "publicado" ? "secondary" : "outline"}>{a.estado}</Badge>
          {a.marcado_inyeccion && (
            <Badge variant="destructive" className="gap-1">
              <ShieldAlert className="size-3" aria-hidden /> marcado por posible inyección
            </Badge>
          )}
        </div>
        <h2 className="text-lg font-semibold">{a.titulo}</h2>
        <p className="text-xs text-muted-foreground">
          {a.casos_historial} casos resueltos con este artículo
          {a.fecha_actualizacion && ` · actualizado ${a.fecha_actualizacion}`}
          {a.versiones_aplicables.length > 0 && ` · versiones: ${a.versiones_aplicables.join(", ")}`}
        </p>
      </header>
      <section className="rounded-lg border bg-muted/30 p-3 text-sm">
        <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">Receta de diagnóstico</h3>
        {r.hipotesis ? (
          <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[10rem_1fr]">
            <dt className="text-muted-foreground">Hipótesis</dt>
            <dd>{r.hipotesis}</dd>
            <dt className="text-muted-foreground">Solución</dt>
            <dd>
              {SOLUCION[r.tipo_solucion ?? ""] ?? r.tipo_solucion ?? "—"}
              {r.accion_catalogo && <span className="ml-1 font-mono text-xs">({r.accion_catalogo})</span>}
            </dd>
            <dt className="text-muted-foreground">Pruebas</dt>
            <dd className="font-mono text-xs">{r.pruebas.join(", ") || "—"}</dd>
            <dt className="text-muted-foreground">Confirma si</dt>
            <dd>{r.criterio_confirmacion ?? "—"}</dd>
            <dt className="text-muted-foreground">Descarta si</dt>
            <dd>{r.criterio_descarte ?? "—"}</dd>
          </dl>
        ) : (
          <p className="text-muted-foreground">
            Sin receta: el diagnóstico no lo puede confirmar con evidencia; se ofrece como guía si es la causa más probable.
          </p>
        )}
      </section>
      {a.secciones ? (
        SECCIONES.filter(([k]) => a.secciones?.[k]).map(([k, nombre]) => (
          <section key={k}>
            <h3 className="mb-1 text-sm font-semibold">{nombre}</h3>
            <p className="text-sm whitespace-pre-wrap text-foreground/90">{a.secciones?.[k]}</p>
          </section>
        ))
      ) : (
        <Cargando texto="Cargando el contenido…" />
      )}
    </article>
  );
}

export function BaseConocimiento({ persona }: { persona: Persona }) {
  const [lista, setLista] = useState<ArticuloKB[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [texto, setTexto] = useState("");
  const [categoria, setCategoria] = useState("");
  const [params, setParams] = useSearchParams();
  const elegido = params.get("articulo");
  const [detalle, setDetalle] = useState<ArticuloKB | null>(null);

  useEffect(() => {
    let vigente = true;
    pedir<ArticuloKB[]>("/api/kb/articulos", persona.id)
      .then((l) => vigente && (setLista(l), setError(null)))
      .catch((e: Error) => vigente && setError(e.message));
    return () => {
      vigente = false;
    };
  }, [persona.id]);

  useEffect(() => {
    if (!elegido) return;
    let vigente = true;
    pedir<ArticuloKB>(`/api/kb/articulos/${encodeURIComponent(elegido)}`, persona.id)
      .then((a) => vigente && setDetalle(a))
      .catch((e: Error) => vigente && setError(e.message));
    return () => {
      vigente = false;
    };
  }, [elegido, persona.id]);

  const categorias = useMemo(() => [...new Set((lista ?? []).map((a) => a.categoria_id ?? ""))].filter(Boolean).sort(), [lista]);
  const visibles = useMemo(() => {
    const t = texto.trim().toLowerCase();
    return (lista ?? []).filter(
      (a) =>
        (!categoria || a.categoria_id === categoria) &&
        (!t || [a.id, a.titulo, a.categoria_id, a.receta.hipotesis].some((v) => v?.toLowerCase().includes(t))),
    );
  }, [lista, texto, categoria]);

  return (
    <div className="space-y-5">
      <EncabezadoVista
        titulo="Base de conocimiento"
        icono={BookOpen}
        descripcion={`Los artículos que usa el diagnóstico${lista ? ` (${lista.length})` : ""}: receta para confirmar o descartar la causa y pasos para el usuario.`}
      />
      {error && (
        <Alert variant="destructive" className="bg-danger-soft">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div className="grid gap-5 xl:grid-cols-[24rem_1fr]">
        <section aria-label="Artículos" className="space-y-3">
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-muted-foreground" aria-hidden />
              <label htmlFor="buscar-kb" className="sr-only">Buscar en la base de conocimiento</label>
              <Input id="buscar-kb" value={texto} onChange={(e) => setTexto(e.target.value)} placeholder="Buscar…" className="h-9 bg-card pl-8" />
            </div>
            <label htmlFor="cat-kb" className="sr-only">Categoría</label>
            <select
              id="cat-kb"
              value={categoria}
              onChange={(e) => setCategoria(e.target.value)}
              className="h-9 max-w-40 rounded-md border bg-card px-2 text-sm"
            >
              <option value="">Todas las categorías</option>
              {categorias.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          {lista === null ? (
            error ? null : <Cargando />
          ) : visibles.length === 0 ? (
            <EstadoVacio icono={BookOpen} titulo="Ningún artículo coincide." />
          ) : (
            <ul className="max-h-[70vh] space-y-1.5 overflow-y-auto pr-1">
              {visibles.map((a) => (
                <li key={a.id}>
                  <button
                    type="button"
                    onClick={() => setParams({ articulo: a.id })}
                    aria-current={elegido === a.id ? "true" : undefined}
                    className={cn(
                      "w-full rounded-lg border bg-card px-3 py-2 text-left text-sm shadow-xs transition-colors hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                      elegido === a.id && "border-primary ring-1 ring-primary",
                    )}
                  >
                    <span className="flex items-center gap-2">
                      <span className="font-mono text-xs text-muted-foreground">{a.id}</span>
                      <span className="truncate text-xs text-muted-foreground">{a.categoria_id}</span>
                      {a.marcado_inyeccion && <ShieldAlert className="ml-auto size-3.5 text-destructive" aria-label="marcado por posible inyección" />}
                    </span>
                    <span className="mt-0.5 line-clamp-2 block">{a.titulo}</span>
                    <span className="block text-xs text-muted-foreground">
                      {SOLUCION[a.receta.tipo_solucion ?? ""]?.split(" (")[0] ?? "—"} · {a.casos_historial} casos
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section aria-label="Artículo" aria-live="polite">
          {!elegido ? (
            <EstadoVacio icono={BookOpen} titulo="Elige un artículo para ver su receta y sus pasos." />
          ) : detalle?.id === elegido ? (
            <DetalleArticulo a={detalle} />
          ) : (
            <Cargando texto="Cargando el artículo…" />
          )}
        </section>
      </div>
    </div>
  );
}
