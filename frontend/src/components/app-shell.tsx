import { FlaskConical, Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { NavLink } from "react-router-dom";

import isotipo from "@/assets/isotipo.svg";
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Rol } from "@/lib/api";
import { useTema, type Tema } from "@/lib/tema";
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
  { a: "/casos", texto: "Casos", roles: ["n2"] },
  { a: "/kb", texto: "Revisor de KB", roles: ["revisor_kb"] },
  { a: "/base-conocimiento", texto: "Base de conocimiento", roles: ["n2", "revisor_kb"] },
  { a: "/auditoria", texto: "Auditoría", roles: ["n2", "colaborador"] },
  { a: "/metricas", texto: "Métricas", roles: ["n2", "revisor_kb"] },
];

const TEMA: Record<Tema, { icono: typeof Sun; texto: string }> = {
  sistema: { icono: Monitor, texto: "Tema: según el sistema" },
  claro: { icono: Sun, texto: "Tema: claro" },
  oscuro: { icono: Moon, texto: "Tema: oscuro" },
};

/** Publica la altura real de la barra en `--alto-barra` para que el chat quepa en la pantalla sin pasarla. */
function useAltoBarra() {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const raiz = document.documentElement;
    const obs = new ResizeObserver(() => raiz.style.setProperty("--alto-barra", `${el.offsetHeight}px`));
    obs.observe(el);
    return () => obs.disconnect();
  }, []);
  return ref;
}

export function AppShell({ children }: { children: ReactNode }) {
  const { personas, persona, elegir } = useVerComo();
  const roles = [...new Set(personas.map((p) => p.rol))];
  const { tema, siguiente } = useTema();
  const { icono: IconoTema, texto: textoTema } = TEMA[tema];
  const barra = useAltoBarra();

  return (
    <div className="flex min-h-dvh flex-col bg-background text-foreground">
      <a
        href="#contenido"
        className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:absolute focus:top-2 focus:left-2"
      >
        Saltar al contenido
      </a>
      {/* Barra inicial sólida de la marca (#00170C) en ambos modos. */}
      <header ref={barra} className="sticky top-0 z-40 border-b border-white/10 bg-brand-dark text-white shadow-sm">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5">
          <div className="order-1 flex items-center gap-2.5">
            <img src={isotipo} alt="" className="h-7 w-auto drop-shadow md:h-8" />
            <div className="leading-none">
              <span className="block font-display text-xl font-semibold tracking-wide md:text-2xl">Soporte de ofimática</span>
              <span className="hidden text-[0.7rem] tracking-wide text-brand-sky sm:block">Mesa de ayuda · Henkia</span>
            </div>
          </div>
          <span
            role="status"
            className="order-3 inline-flex items-center gap-1 rounded-full border border-amber-300/60 bg-amber-300/10 px-2.5 py-0.5 text-xs font-medium text-amber-200"
          >
            <FlaskConical className="size-3" aria-hidden /> Modo demostración
          </span>
          <nav aria-label="Vistas" className="order-4 flex gap-1 overflow-x-auto">
            {NAVEGACION.filter((n) => persona && n.roles.includes(persona.rol)).map((n) => (
              <NavLink
                key={n.a}
                to={n.a}
                end
                className={({ isActive }) =>
                  cn(
                    "rounded-full px-3 py-1 text-sm whitespace-nowrap text-white/80 transition-colors hover:bg-white/10 hover:text-white",
                    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-green-bright",
                    isActive && "bg-brand-green-bright font-medium text-brand-dark hover:bg-brand-green-bright hover:text-brand-dark",
                  )
                }
              >
                {n.texto}
              </NavLink>
            ))}
          </nav>
          <div className="order-5 flex w-full min-w-0 items-center gap-2 md:ml-auto md:w-auto">
            <label htmlFor="ver-como" className="hidden text-sm whitespace-nowrap text-white/75 xl:inline">
              Ver como
            </label>
            <Select value={persona?.id ?? ""} onValueChange={elegir}>
              <SelectTrigger
                id="ver-como"
                className="min-w-0 flex-1 border-white/20 bg-white/5 text-white hover:bg-white/10 md:w-60 md:flex-none xl:w-72 dark:bg-white/5 dark:hover:bg-white/10 [&_svg]:text-white/70!"
                aria-label="Ver como"
              >
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
          <button
            type="button"
            onClick={siguiente}
            aria-label={`${textoTema}. Cambiar tema`}
            title={`${textoTema} (clic para cambiar)`}
            className="order-2 ml-auto grid size-8 shrink-0 md:order-6 md:ml-0 place-items-center rounded-lg border border-white/20 text-white/85 transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-brand-green-bright"
          >
            <IconoTema className="size-4" aria-hidden />
          </button>
        </div>
        <div className="degradado-marca h-0.5 w-full opacity-80" aria-hidden />
      </header>
      <main id="contenido" tabIndex={-1} className="mx-auto w-full max-w-7xl flex-1 px-4 py-4 outline-none">
        {children}
      </main>
    </div>
  );
}
