import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

/** Encabezado común de las vistas: título con la tipografía de marca, descripción y acciones a la derecha. */
export function EncabezadoVista({
  titulo,
  descripcion,
  icono: Icono,
  acciones,
}: {
  titulo: string;
  descripcion?: ReactNode;
  icono?: LucideIcon;
  acciones?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 border-b pb-4">
      <div className="flex min-w-0 items-start gap-3">
        {Icono && (
          <span className="mt-0.5 grid size-10 shrink-0 place-items-center rounded-xl bg-accent text-accent-foreground">
            <Icono className="size-5" aria-hidden />
          </span>
        )}
        <div className="min-w-0 space-y-1">
          <h1 className="titulo-pagina">{titulo}</h1>
          {descripcion && <p className="max-w-3xl text-sm text-muted-foreground">{descripcion}</p>}
        </div>
      </div>
      {acciones && <div className="flex flex-wrap gap-2">{acciones}</div>}
    </div>
  );
}

/** Título de sección dentro de una vista (con contador opcional). */
export function TituloSeccion({ id, children, cuenta }: { id?: string; children: ReactNode; cuenta?: number | null }) {
  return (
    <h2 id={id} className="flex items-center gap-2 text-base font-semibold">
      {children}
      {cuenta !== undefined && cuenta !== null && (
        <span className="rounded-full bg-secondary px-2 py-0.5 text-xs font-medium text-secondary-foreground tabular-nums">
          {cuenta}
        </span>
      )}
    </h2>
  );
}

export function Cargando({ texto = "Cargando…", className }: { texto?: string; className?: string }) {
  return (
    <p role="status" className={cn("flex items-center gap-2 py-6 text-sm text-muted-foreground", className)}>
      <Spinner role="presentation" aria-hidden aria-label={undefined} /> {texto}
    </p>
  );
}

/** Estado vacío: un icono suave, un título y una pista de qué hacer. */
export function EstadoVacio({
  icono: Icono,
  titulo,
  children,
  className,
}: {
  icono: LucideIcon;
  titulo: string;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center gap-2 rounded-xl border border-dashed bg-card/60 px-6 py-10 text-center", className)}>
      <span className="grid size-11 place-items-center rounded-full bg-accent text-accent-foreground">
        <Icono className="size-5" aria-hidden />
      </span>
      <p className="font-medium">{titulo}</p>
      {children && <div className="max-w-md text-sm text-muted-foreground">{children}</div>}
    </div>
  );
}
