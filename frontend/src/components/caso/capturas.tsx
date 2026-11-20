import { ImagePlus, ShieldAlert, X } from "lucide-react";

import { PromptInputButton, usePromptInputAttachments } from "@/components/ai-elements/prompt-input";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import type { DatosCaptura } from "@/lib/mensajes";

export const TIPOS_CAPTURA = "image/png,image/jpeg,image/webp";
export const MAX_CAPTURA_BYTES = 5 * 1024 * 1024;
export const MAX_CAPTURAS = 3;

/** Botón «Adjuntar captura» (dentro de PromptInput). */
export function BotonAdjuntar({ disabled }: { disabled?: boolean }) {
  const adjuntos = usePromptInputAttachments();
  return (
    <PromptInputButton
      aria-label="Adjuntar captura de pantalla"
      tooltip="Adjuntar captura (PNG, JPEG o WebP, máx. 5 MB)"
      disabled={disabled}
      onClick={() => adjuntos.openFileDialog()}
    >
      <ImagePlus aria-hidden />
    </PromptInputButton>
  );
}

/** Capturas elegidas antes de enviar (nombre y botón para quitar). */
export function ListaAdjuntos() {
  const adjuntos = usePromptInputAttachments();
  if (adjuntos.files.length === 0) return null;
  return (
    <ul aria-label="Capturas por enviar" className="flex flex-wrap gap-2 px-3 pt-2 text-xs">
      {adjuntos.files.map((f) => (
        <li key={f.id} className="flex items-center gap-1.5 rounded-full border bg-muted/50 py-1 pr-1 pl-1.5">
          {f.mediaType.startsWith("image/") && f.url && (
            <img src={f.url} alt="" className="size-6 rounded object-cover" />
          )}
          <span className="max-w-40 truncate">{f.filename ?? "captura"}</span>
          <button
            type="button"
            aria-label={`Quitar ${f.filename ?? "captura"}`}
            className="rounded-full p-1 hover:bg-background"
            onClick={() => adjuntos.remove(f.id)}
          >
            <X className="size-3" aria-hidden />
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Resultado de la lectura en cuarentena de una captura (solo campos validados por el backend). */
export function TarjetaCaptura({ datos }: { datos: DatosCaptura }) {
  if (datos.contiene_instrucciones) {
    return (
      <Alert role="status" variant="destructive" className="max-w-xl border-destructive/40 bg-danger-soft p-3">
        <ShieldAlert aria-hidden />
        <AlertTitle>«{datos.nombre}» contiene instrucciones que no sigo</AlertTitle>
        <AlertDescription>
          Solo uso los códigos de error de las capturas. Quedó registrado como alerta de seguridad.
          {datos.codigo_error && <> Código válido: <code className="rounded bg-background px-1 font-mono">{datos.codigo_error}</code>.</>}
        </AlertDescription>
      </Alert>
    );
  }
  return (
    <Alert role="status" className="max-w-xl border-info/30 bg-info-soft/60 p-3">
      <ImagePlus aria-hidden className="text-info-foreground" />
      <AlertTitle>Captura «{datos.nombre}»</AlertTitle>
      <AlertDescription>
        {datos.estado === "rechazada" ? (
          <p>No se pudo usar: {datos.motivo}</p>
        ) : datos.codigo_error ? (
          <p>
            Código validado (lectura automática + modelo): <code className="rounded bg-background px-1 font-mono">{datos.codigo_error}</code>
            {datos.mensaje_resumido && <span className="block text-muted-foreground">«{datos.mensaje_resumido}»</span>}
          </p>
        ) : datos.estado === "no_concluyente" ? (
          <p>No pude confirmar el código. Escríbelo tal como aparece en la ventana.</p>
        ) : (
          <p>No veo un código de error en esta imagen.</p>
        )}
      </AlertDescription>
    </Alert>
  );
}
