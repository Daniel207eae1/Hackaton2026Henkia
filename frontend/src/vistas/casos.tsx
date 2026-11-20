import { FolderSearch, RefreshCw, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { DetalleCaso } from "@/components/caso/detalle-caso";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Cargando, EncabezadoVista, EstadoVacio } from "@/components/vista";
import { pedir, type Persona } from "@/lib/api";
import { cn } from "@/lib/utils";

export interface ResumenCaso {
  case_id: string;
  codigo: string | null;
  usuario_id: string | null;
  estado: string | null;
  resultado: string | null;
  creado_en: string | null;
  aplicacion: string | null;
  tipo_sintoma: string | null;
  categoria: string | null;
  confirmada: string | null;
  probable: boolean | null;
  etapa: string | null;
  turnos: number | null;
  masivo: string | null;
}

const FILTROS = [
  { clave: "todos", nombre: "Todos" },
  { clave: "abierto", nombre: "En curso" },
  { clave: "escalado", nombre: "Escalados" },
  { clave: "resuelto", nombre: "Resueltos" },
  { clave: "vinculado_masivo", nombre: "Incidente general" },
] as const;

const ETIQUETA_RESULTADO: Record<string, string> = {
  resuelto: "resuelto",
  escalado: "escalado a N2",
  vinculado_masivo: "incidente general",
};

function resultadoDe(c: ResumenCaso) {
  return c.resultado ?? "abierto";
}

export function Casos({ persona }: { persona: Persona }) {
  const [lista, setLista] = useState<ResumenCaso[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filtro, setFiltro] = useState<(typeof FILTROS)[number]["clave"]>("todos");
  const [texto, setTexto] = useState("");
  const [params, setParams] = useSearchParams();
  const elegido = params.get("caso");
  const [detalle, setDetalle] = useState<{ case_id: string; estado: Record<string, unknown> } | null>(null);
  const [errorDetalle, setErrorDetalle] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const cargar = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    let vigente = true;
    pedir<ResumenCaso[]>("/api/n2/casos", persona.id)
      .then((l) => vigente && (setLista(l), setError(null)))
      .catch((e: Error) => vigente && setError(e.message));
    return () => {
      vigente = false;
    };
  }, [persona.id, version]);

  useEffect(() => {
    if (!elegido) return;
    let vigente = true;
    pedir<{ case_id: string; estado: Record<string, unknown> }>(`/api/casos/${encodeURIComponent(elegido)}`, persona.id)
      .then((c) => vigente && (setDetalle(c), setErrorDetalle(null)))
      .catch((e: Error) => vigente && (setDetalle(null), setErrorDetalle(e.message)));
    return () => {
      vigente = false;
    };
  }, [elegido, persona.id, version]);

  const visibles = useMemo(() => {
    const t = texto.trim().toLowerCase();
    return (lista ?? []).filter(
      (c) =>
        (filtro === "todos" || resultadoDe(c) === filtro) &&
        (!t || [c.case_id, c.codigo, c.usuario_id, c.aplicacion, c.categoria].some((v) => v?.toLowerCase().includes(t))),
    );
  }, [lista, filtro, texto]);

  const abrir = (id: string) => setParams({ caso: id });

  return (
    <div className="space-y-5">
      <EncabezadoVista
        titulo="Casos"
        icono={FolderSearch}
        descripcion="Todos los casos con su diagnóstico: qué se entendió, qué se consultó, qué hipótesis se confirmaron o descartaron y por qué."
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
      <div className="grid gap-5 xl:grid-cols-[22rem_1fr]">
        <section aria-label="Lista de casos" className="space-y-3">
          <div className="relative">
            <Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-muted-foreground" aria-hidden />
            <label htmlFor="buscar-caso" className="sr-only">Buscar caso</label>
            <Input id="buscar-caso" value={texto} onChange={(e) => setTexto(e.target.value)} placeholder="Id, usuario, aplicación…" className="h-9 bg-card pl-8" />
          </div>
          <div role="group" aria-label="Filtrar por resultado" className="flex flex-wrap gap-1.5">
            {FILTROS.map((f) => (
              <Button key={f.clave} size="xs" variant={filtro === f.clave ? "default" : "outline"} aria-pressed={filtro === f.clave} onClick={() => setFiltro(f.clave)}>
                {f.nombre}
              </Button>
            ))}
          </div>
          {lista === null ? (
            error ? null : <Cargando />
          ) : visibles.length === 0 ? (
            <EstadoVacio icono={FolderSearch} titulo="No hay casos con ese filtro." />
          ) : (
            <ul className="max-h-[70vh] space-y-1.5 overflow-y-auto pr-1">
              {visibles.map((c) => {
                const r = resultadoDe(c);
                return (
                  <li key={c.case_id}>
                    <button
                      type="button"
                      onClick={() => abrir(c.case_id)}
                      aria-current={elegido === c.case_id ? "true" : undefined}
                      className={cn(
                        "w-full rounded-lg border bg-card px-3 py-2 text-left text-sm shadow-xs transition-colors hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                        elegido === c.case_id && "border-primary ring-1 ring-primary",
                      )}
                    >
                      <span className="flex items-center gap-2">
                        <span className="font-mono text-xs">{c.codigo ?? c.case_id.slice(0, 8)}</span>
                        <Badge variant={r === "escalado" ? "destructive" : r === "abierto" ? "secondary" : "outline"} className="text-[10px]">
                          {ETIQUETA_RESULTADO[r] ?? "en curso"}
                        </Badge>
                        <span className="ml-auto text-xs text-muted-foreground">{c.creado_en?.slice(5, 16).replace("T", " ")}</span>
                      </span>
                      <span className="mt-0.5 block truncate">
                        {c.aplicacion && c.aplicacion !== "desconocida" ? c.aplicacion : "sin identificar"}
                        {c.tipo_sintoma && c.tipo_sintoma !== "desconocido" && ` · ${c.tipo_sintoma}`}
                      </span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {c.usuario_id} · {c.confirmada ? `${c.probable ? "probó" : "confirmó"} ${c.confirmada}` : (c.categoria ?? "sin diagnóstico")}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
        <section aria-label="Detalle del caso" aria-live="polite">
          {!elegido ? (
            <EstadoVacio icono={FolderSearch} titulo="Elige un caso de la lista.">
              Verás el diagnóstico completo para continuar sin repreguntar al usuario.
            </EstadoVacio>
          ) : errorDetalle ? (
            <Alert variant="destructive" className="bg-danger-soft">
              <AlertDescription>{errorDetalle}</AlertDescription>
            </Alert>
          ) : detalle?.case_id === elegido ? (
            <DetalleCaso caseId={detalle.case_id} estado={detalle.estado} />
          ) : (
            <Cargando texto="Cargando el caso…" />
          )}
        </section>
      </div>
    </div>
  );
}
