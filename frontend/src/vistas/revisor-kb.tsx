import { Play, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
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
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{TIPO[p.tipo]}</Badge>
          {p.articulo_id && <Badge variant="secondary">{p.articulo_id}</Badge>}
          <Badge variant={p.estado === "pendiente" ? "default" : "secondary"}>{ESTADO[p.estado]}</Badge>
          <span className="text-xs text-muted-foreground">{p.categoria_id}</span>
        </div>
        <CardTitle className="text-base">{p.titulo}</CardTitle>
        <CardDescription>{motivo(p.justificacion)}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div>
          <h3 className="font-medium">Casos que lo respaldan ({p.casos_soporte.length})</h3>
          <p className="font-mono text-xs">{p.casos_soporte.join(", ")}</p>
        </div>
        <div>
          <h3 className="font-medium">Borrador</h3>
          {/* Texto plano escapado: el borrador lo escribió un LLM a partir de tickets (nunca se renderiza HTML). */}
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md border bg-muted/40 p-3 font-sans text-sm">
            {p.borrador_md}
          </pre>
        </div>
        {p.comentario_revision && (
          <p>
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
              className="w-full rounded-md border bg-background p-2"
              value={comentario}
              onChange={(e) => setComentario(e.currentTarget.value)}
            />
          </div>
        )}
      </CardContent>
      {p.estado === "aprobada" && (
        <CardFooter>
          <Button size="sm" onClick={() => void onAccion(`/api/kb/propuestas/${p.id}/publicar`)}>
            Reintentar publicación
          </Button>
        </CardFooter>
      )}
      {p.estado === "pendiente" && (
        <CardFooter className="flex flex-wrap gap-2">
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
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Revisor de KB</h1>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => void lote()} disabled={corriendo}>
            <Play aria-hidden /> {corriendo ? "Ejecutando lote…" : "Ejecutar lote ahora"}
          </Button>
          <Button variant="outline" size="sm" onClick={cargar}>
            <RefreshCw aria-hidden /> Actualizar
          </Button>
        </div>
      </div>
      <p className="text-sm text-muted-foreground">
        El curador agrupa casos resueltos del historial: propone artículos que faltan y correcciones de artículos
        desactualizados. Nada se publica sin tu revisión; devolver exige un comentario.
      </p>
      {aviso && (
        <p role="status" className="text-sm">
          {aviso}
        </p>
      )}
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {lista === null ? (
        <p role="status">Cargando…</p>
      ) : lista.length === 0 ? (
        <p>No hay propuestas. Ejecuta el lote para revisar el historial.</p>
      ) : (
        lista.map((p) => <TarjetaPropuesta key={p.id} p={p} onAccion={accion} />)
      )}
    </div>
  );
}
