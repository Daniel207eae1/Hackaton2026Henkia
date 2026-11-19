import { useState, type FormEvent } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { pedir, type Persona } from "@/lib/api";

interface EstadoCaso {
  case_id: string;
  etapa: string | null;
  turnos: number;
  estado: { linea_tiempo?: { hora: string; etapa: string; detalle: string }[] } & Record<string, unknown>;
}

/** Auditoría del caso (F0: línea de tiempo y estado crudo; F5 completa hipótesis, acciones y tokens). */
export function Auditoria({ persona }: { persona: Persona }) {
  const [caseId, setCaseId] = useState("");
  const [caso, setCaso] = useState<EstadoCaso | null>(null);
  const [error, setError] = useState<string | null>(null);

  const buscar = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setCaso(null);
    try {
      setCaso(await pedir<EstadoCaso>(`/api/casos/${encodeURIComponent(caseId.trim())}`, persona.id));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Auditoría del caso</h1>
      <form onSubmit={buscar} className="flex max-w-xl gap-2">
        <label htmlFor="case-id" className="sr-only">
          Id del caso
        </label>
        <Input id="case-id" value={caseId} onChange={(e) => setCaseId(e.target.value)} placeholder="Id del caso" />
        <Button type="submit" disabled={!caseId.trim()}>
          Buscar
        </Button>
      </form>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {caso && (
        <Card>
          <CardHeader>
            <CardTitle>
              {caso.case_id} · etapa {caso.etapa ?? "—"} · {caso.turnos} turnos
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <ol className="space-y-1 text-sm">
              {(caso.estado.linea_tiempo ?? []).map((h, i) => (
                <li key={i}>
                  <time className="text-muted-foreground">{h.hora}</time> · <strong>{h.etapa}</strong> · {h.detalle}
                </li>
              ))}
            </ol>
            <details>
              <summary className="cursor-pointer text-sm">Estado completo (JSON)</summary>
              <pre className="mt-2 max-h-96 overflow-auto rounded bg-muted p-2 text-xs">{JSON.stringify(caso.estado, null, 2)}</pre>
            </details>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
