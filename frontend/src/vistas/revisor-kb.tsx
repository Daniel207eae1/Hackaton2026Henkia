import { BookOpenCheck, CheckCircle2, FileText, Play, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Cargando, EncabezadoVista, EstadoVacio, TituloSeccion } from "@/components/vista";
import { pedir, type Persona } from "@/lib/api";

export interface PropuestaKB {
  id: number;
  tipo: "articulo_faltante" | "articulo_desactualizado";
  articulo_id: string | null;
  categoria_id: string | null;
  titulo: string;
  borrador_md: string;
  casos_soporte: string[];
  justificacion: string | null;
  estado: "pendiente" | "aprobada" | "rechazada" | "publicada";
  revisor_id: string | null;
  comentario_revision: string | null;
}

const TIPO: Record<PropuestaKB["tipo"], string> = {
  articulo_faltante: "Artículo nuevo",
  articulo_desactualizado: "Corrección",
};
const MIN_COMENTARIO = 10;
const ESTADO: Record<PropuestaKB["estado"], string> = {
  pendiente: "Pendiente",
  aprobada: "Aprobada · falta publicar en la KB",
  rechazada: "Devuelta",
  publicada: "Publicada en la KB",
};

interface ResultadoPublicacion {
  en_kb?: boolean;
  articulo_publicado?: string | null;
}

/** Quita la clave interna del lote de la justificación visible. */
function motivo(j: string | null): string {
  return (j ?? "").replace(/^\[clave=[^\]]*\]\s*/, "");
}

export function TarjetaPropuesta({
  p,
  onAccion,
}: {
  p: PropuestaKB;
  onAccion: (ruta: string, cuerpo?: object) => Promise<void>;
}) {
  const [comentario, setComentario] = useState("");
  const id = `comentario-${p.id}`;
  return (
    <Card className={p.estado === "pendiente" ? "border-l-4 border-l-primary shadow-sm" : "shadow-sm"}>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline" className="border-info/40 bg-info-soft text-info-foreground">{TIPO[p.tipo]}</Badge>
          {p.articulo_id && <Badge variant="secondary">{p.articulo_id}</Badge>}
          <Badge variant={p.estado === "pendiente" ? "default" : "secondary"}>{ESTADO[p.estado]}</Badge>
          <span className="text-xs text-muted-foreground">{p.categoria_id}</span>
        </div>
        <CardTitle className="text-base font-semibold">{p.titulo}</CardTitle>
        <CardDescription>{motivo(p.justificacion)}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div>
          <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Casos que lo respaldan ({p.casos_soporte.length})</h3>
          <p className="mt-1 font-mono text-xs">{p.casos_soporte.join(", ")}</p>
        </div>
        <div>
          <h3 className="flex items-center gap-1 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            <FileText className="size-3.5" aria-hidden /> Borrador
          </h3>
          {/* Texto plano escapado: el borrador lo escribió un LLM a partir de tickets (nunca se renderiza HTML). */}
          <pre className="mt-1 max-h-72 overflow-auto rounded-lg border bg-muted/40 p-3 font-sans text-sm leading-relaxed whitespace-pre-wrap">
            {p.borrador_md}
          </pre>
        </div>
        {p.comentario_revision && (
          <p className="rounded-lg border border-warning/40 bg-warning-soft p-2.5">
            <span className="font-medium">Comentario de revisión:</span> {p.comentario_revision}
          </p>
        )}
        {p.estado === "pendiente" && (
          <div className="space-y-1">
            <label htmlFor={id} className="font-medium">
              Comentario para devolver (obligatorio)
            </label>
            <textarea
              id={id}
              rows={2}
              maxLength={1000}
              className="campo"
              value={comentario}
              onChange={(e) => setComentario(e.currentTarget.value)}
            />
          </div>
        )}
      </CardContent>
      {p.estado === "aprobada" && (
        <CardFooter className="border-t bg-muted/30 py-3">
          <Button size="sm" onClick={() => void onAccion(`/api/kb/propuestas/${p.id}/publicar`)}>
            Reintentar publicación
          </Button>
        </CardFooter>
      )}
      {p.estado === "pendiente" && (
        <CardFooter className="flex flex-wrap gap-2 border-t bg-muted/30 py-3">
          <Button size="sm" onClick={() => void onAccion(`/api/kb/propuestas/${p.id}/publicar`)}>
            Publicar
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={comentario.trim().length < MIN_COMENTARIO}
            onClick={() => void onAccion(`/api/kb/propuestas/${p.id}/devolver`, { comentario: comentario.trim() })}
          >
            Devolver
          </Button>
        </CardFooter>
      )}
    </Card>
  );
}

export function RevisorKB({ persona }: { persona: Persona }) {
  const [lista, setLista] = useState<PropuestaKB[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [corriendo, setCorriendo] = useState(false);
  const [version, setVersion] = useState(0);
  const cargar = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    let vigente = true;
    pedir<PropuestaKB[]>("/api/kb/propuestas", persona.id)
      .then((l) => vigente && (setLista(l), setError(null)))
      .catch((e: Error) => vigente && setError(e.message));
    return () => {
      vigente = false;
    };
  }, [persona.id, version]);

  const accion = async (ruta: string, cuerpo?: object) => {
    setAviso(null);
    setError(null);
    try {
      const r = await pedir<ResultadoPublicacion>(ruta, persona.id, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: cuerpo ? JSON.stringify(cuerpo) : undefined,
      });
      if (ruta.endsWith("/publicar"))
        setAviso(
          r?.en_kb
            ? `Publicado en la KB como ${r.articulo_publicado ?? "artículo nuevo"}: el diagnóstico ya lo puede usar.`
            : "Aprobada. Quedará en la KB cuando la base de datos habilite la publicación (función de P2).",
        );
      cargar();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const lote = async () => {
    setCorriendo(true);
    setAviso(null);
    try {
      const r = await pedir<{ detectados: number; creadas: number[]; ya_propuestos: string[] }>("/api/kb/lote", persona.id, {
        method: "POST",
      });
      setAviso(`Lote: ${r.detectados} hallazgos · ${r.creadas.length} propuestas nuevas · ${r.ya_propuestos.length} ya propuestas.`);
      cargar();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCorriendo(false);
    }
  };

  return (
    <div className="space-y-4">
      <EncabezadoVista
        titulo="Revisor de KB"
        icono={BookOpenCheck}
        descripcion="El curador agrupa casos resueltos del historial: propone artículos que faltan y correcciones de artículos desactualizados. Nada se publica sin tu revisión; devolver exige un comentario."
        acciones={
          <>
            <Button size="sm" onClick={() => void lote()} disabled={corriendo}>
              <Play aria-hidden /> {corriendo ? "Ejecutando lote…" : "Ejecutar lote ahora"}
            </Button>
            <Button variant="outline" size="sm" onClick={cargar}>
              <RefreshCw aria-hidden /> Actualizar
            </Button>
          </>
        }
      />
      {aviso && (
        <p
          role="status"
          className="flex items-start gap-2 rounded-xl border border-success/40 bg-success-soft px-3 py-2 text-sm text-success-foreground"
        >
          <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden />
          {aviso}
        </p>
      )}
      {error && (
        <Alert variant="destructive" className="bg-danger-soft">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <section aria-labelledby="titulo-propuestas" className="space-y-3">
        <TituloSeccion id="titulo-propuestas" cuenta={lista?.length}>
          Propuestas del curador
        </TituloSeccion>
        {lista === null ? (
          <Cargando />
        ) : lista.length === 0 ? (
          <EstadoVacio icono={BookOpenCheck} titulo="No hay propuestas.">
            Ejecuta el lote para revisar el historial.
          </EstadoVacio>
        ) : (
          lista.map((p) => <TarjetaPropuesta key={p.id} p={p} onAccion={accion} />)
        )}
      </section>
    </div>
  );
}
