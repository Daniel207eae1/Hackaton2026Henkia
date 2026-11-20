import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { pedir } from "@/lib/api";

/** «¿Te sirvió la atención?» al cerrar o escalar el caso (una sola vez; el comentario es opcional). */
export function Valoracion({ caseId, verComo }: { caseId: string; verComo: string }) {
  const [util, setUtil] = useState<boolean | null>(null);
  const [comentario, setComentario] = useState("");
  const [estado, setEstado] = useState<"pregunta" | "enviando" | "enviada" | "error">("pregunta");

  const enviar = async (valor: boolean, texto?: string) => {
    setEstado("enviando");
    try {
      await pedir(`/api/casos/${caseId}/valoracion`, verComo, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ util: valor, comentario: texto?.trim() || null }),
      });
      setEstado("enviada");
    } catch {
      setEstado("error");
    }
  };

  if (estado === "enviada")
    return (
      <p role="status" className="text-sm font-medium text-success-foreground">
        ¡Gracias por tu valoración!
      </p>
    );
  return (
    <section aria-label="Valora la atención" className="max-w-xl space-y-2 rounded-xl border bg-muted/40 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">¿Te sirvió la atención?</span>
        <Button size="sm" variant={util === true ? "default" : "outline"} onClick={() => setUtil(true)} aria-pressed={util === true}>
          <ThumbsUp aria-hidden /> Sí
        </Button>
        <Button size="sm" variant={util === false ? "default" : "outline"} onClick={() => setUtil(false)} aria-pressed={util === false}>
          <ThumbsDown aria-hidden /> No
        </Button>
      </div>
      {util !== null && (
        <div className="space-y-2">
          <label htmlFor={`comentario-${caseId}`} className="block text-muted-foreground">
            ¿Algo que debamos mejorar? (opcional)
          </label>
          <textarea
            id={`comentario-${caseId}`}
            rows={2}
            maxLength={500}
            className="campo"
            value={comentario}
            onChange={(e) => setComentario(e.currentTarget.value)}
          />
          <Button size="sm" disabled={estado === "enviando"} onClick={() => void enviar(util, comentario)}>
            Enviar valoración
          </Button>
          {estado === "error" && (
            <p role="alert" className="text-destructive">
              No pude guardar tu valoración. Intenta de nuevo.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
