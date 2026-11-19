import { FlaskConical } from "lucide-react";
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Rol } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useVerComo } from "@/lib/ver-como";

const NOMBRE_ROL: Record<Rol, string> = {
  colaborador: "Colaboradores",
  n2: "Técnicos N2",
  revisor_kb: "Revisión de KB",
};

const NAVEGACION: { a: string; texto: string; roles: Rol[] }[] = [
  { a: "/", texto: "Chat", roles: ["colaborador"] },
  { a: "/n2", texto: "Consola N2", roles: ["n2"] },
  { a: "/kb", texto: "Revisor de KB", roles: ["revisor_kb"] },
  { a: "/auditoria", texto: "Auditoría", roles: ["n2", "colaborador"] },
  { a: "/metricas", texto: "Métricas", roles: ["n2", "revisor_kb"] },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { personas, persona, elegir } = useVerComo();
  const roles = [...new Set(personas.map((p) => p.rol))];

  return (
    <div className="flex min-h-dvh flex-col bg-background text-foreground">
      <a href="#contenido" className="sr-only focus:not-sr-only focus:absolute focus:p-2">
        Saltar al contenido
      </a>
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-2">
          <span className="font-semibold">Soporte de ofimática</span>
          <Badge variant="outline" className="gap-1 border-amber-600 text-amber-800" role="status">
            <FlaskConical className="size-3" aria-hidden /> Modo demostración
          </Badge>
          <nav aria-label="Vistas" className="flex flex-wrap gap-1">
            {NAVEGACION.filter((n) => persona && n.roles.includes(persona.rol)).map((n) => (
              <NavLink
                key={n.a}
                to={n.a}
                end
                className={({ isActive }) =>
                  cn("rounded-md px-2 py-1 text-sm hover:bg-accent", isActive && "bg-accent font-medium")
                }
              >
                {n.texto}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <label htmlFor="ver-como" className="text-sm text-muted-foreground">
              Ver como
            </label>
            <Select value={persona?.id ?? ""} onValueChange={elegir}>
              <SelectTrigger id="ver-como" className="w-72" aria-label="Ver como">
                <SelectValue placeholder="Elige una persona" />
              </SelectTrigger>
              <SelectContent>
                {roles.map((rol) => (
                  <SelectGroup key={rol}>
                    <SelectLabel>{NOMBRE_ROL[rol]}</SelectLabel>
                    {personas
                      .filter((p) => p.rol === rol)
                      .map((p) => (
                        <SelectItem key={p.id} value={p.id}>
                          {p.etiqueta ?? `${p.nombre} · ${p.area}`}
                        </SelectItem>
                      ))}
                  </SelectGroup>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </header>
      <main id="contenido" className="mx-auto w-full max-w-7xl flex-1 px-4 py-4">
        {children}
      </main>
    </div>
  );
}
