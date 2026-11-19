import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import { ExternalLink, Headset, MessageSquarePlus } from "lucide-react";
import { useMemo, useState } from "react";

import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import { Message, MessageContent } from "@/components/ai-elements/message";
import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { Shimmer } from "@/components/ai-elements/shimmer";
import { IndicadorEtapa } from "@/components/caso/indicador-etapa";
import { Fuentes, PanelHipotesis } from "@/components/caso/panel-hipotesis";
import { PanelRevisando } from "@/components/caso/panel-revisando";
import { TarjetaAccion } from "@/components/caso/tarjeta-accion";
import { SeguimientoMasivo, TarjetaMasivo } from "@/components/caso/tarjeta-masivo";
import { TarjetaCierre, TarjetaEscalamiento } from "@/components/caso/tarjeta-resultado";
import { leerModeloGuardado, SelectorModelo } from "@/components/selector-modelo";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { API_URL, type Persona } from "@/lib/api";
import { idUltimaEjecutada, lineasRevisando, ultimaParte, type MensajeCaso } from "@/lib/mensajes";

function nuevoCaseId(): string {
  return crypto.randomUUID().replaceAll("-", "");
}

export function ChatColaborador({ persona }: { persona: Persona }) {
  // Un caso nuevo por persona y por «Nuevo caso».
  const [caseId, setCaseId] = useState(nuevoCaseId);
  const [modelo, setModelo] = useState(leerModeloGuardado);
  return <ChatCaso
      key={`${persona.id}-${caseId}`}
      persona={persona}
      caseId={caseId}
      onNuevo={() => setCaseId(nuevoCaseId())}
      modelo={modelo}
      onModelo={setModelo}
    />;
}

interface PropsCaso {
  persona: Persona;
  caseId: string;
  onNuevo: () => void;
  modelo: string;
  onModelo: (alias: string) => void;
}

function ChatCaso({ persona, caseId, onNuevo, modelo, onModelo }: PropsCaso) {
  const transport = useMemo(
    () =>
      new DefaultChatTransport<MensajeCaso>({
        api: `${API_URL}/api/chat`,
        // El modelo se lee en cada envío desde la preferencia guardada: cambiarlo no reinicia la conversación.
        headers: () => {
          const elegido = leerModeloGuardado();
          return { "X-Ver-Como": persona.id, ...(elegido ? { "X-Modelo": elegido } : {}) };
        },
      }),
    [persona.id],
  );
  const { messages, sendMessage, status, error } = useChat<MensajeCaso>({ id: caseId, transport });
  const [texto, setTexto] = useState("");

  const etapa = ultimaParte(messages, "etapa")?.etapa ?? null;
  const caso = ultimaParte(messages, "caso");
  const lineas = lineasRevisando(messages);
  const ocupado = status === "submitted" || status === "streaming";
  const escalamiento = ultimaParte(messages, "escalamiento");
  const cierre = ultimaParte(messages, "cierre");
  const terminado = Boolean(escalamiento || cierre);
  const masivo = ultimaParte(messages, "masivo");
  // Solo la última acción ejecutada pide «¿ya te funciona?», y solo mientras el caso siga abierto.
  const ultimaEjecutada = terminado ? null : (idUltimaEjecutada(messages) ?? null);

  const enviar = (m: PromptInputMessage) => {
    const limpio = m.text.trim();
    if (!limpio || ocupado) return;
    void sendMessage({ text: limpio });
    setTexto("");
  };

  return (
    <div className="grid h-full gap-4 lg:grid-cols-[1fr_320px]">
      <section aria-label="Conversación con soporte" className="flex min-h-0 flex-col rounded-lg border bg-card">
        <header className="flex flex-wrap items-center justify-between gap-2 border-b p-3">
          <IndicadorEtapa etapa={etapa} />
          <div className="flex items-center gap-2">
            <SelectorModelo valor={modelo} onCambio={onModelo} />
          <Button variant="ghost" size="sm" onClick={onNuevo}>
            <MessageSquarePlus aria-hidden /> Nuevo caso
          </Button>
          </div>
        </header>

        <Conversation className="min-h-[50vh] flex-1">
          <ConversationContent>
            {messages.length === 0 ? (
              <ConversationEmptyState
                title={`Hola, ${persona.nombre.split(" ")[0]}`}
                description="Cuéntame qué te está pasando con Outlook, Teams, Excel, Word, OneDrive o la impresora."
              />
            ) : (
              messages.map((m) => (
                <Message key={m.id} from={m.role}>
                  <MessageContent className="space-y-3">
                    {m.parts.map((p, i) => {
                      // Texto plano escapado por React: nunca se interpreta HTML del backend.
                      if (p.type === "text")
                        return p.text ? (
                          <p key={i} className="whitespace-pre-wrap">
                            {p.text}
                          </p>
                        ) : null;
                      if (p.type === "data-accion")
                        return (
                          <TarjetaAccion
                            key={p.id ?? i}
                            accion={p.data}
                            ocupado={ocupado}
                            onConfirmar={
                              p.id && p.id === ultimaEjecutada ? (t: string) => void sendMessage({ text: t }) : undefined
                            }
                            onRevisar={() =>
                              void sendMessage({
                                text:
                                  p.data.estado === "esperando_n2"
                                    ? "¿Ya aprobaron la solicitud?"
                                    : "Ya respondí la ventana de autorización.",
                              })
                            }
                          />
                        );
                      if (p.type === "data-escalamiento") return <TarjetaEscalamiento key={p.id ?? i} datos={p.data} />;
                      if (p.type === "data-cierre") return <TarjetaCierre key={p.id ?? i} datos={p.data} />;
                      if (p.type === "data-fuentes") return <Fuentes key={p.id ?? i} datos={p.data} />;
                      if (p.type === "data-masivo") return <TarjetaMasivo key={p.id ?? i} datos={p.data} />;
                      return null;
                    })}
                  </MessageContent>
                </Message>
              ))
            )}
            {status === "submitted" && <Shimmer>Revisando…</Shimmer>}
          </ConversationContent>
          <ConversationScrollButton />
        </Conversation>

        {error && (
          <Alert variant="destructive" className="mx-3 mb-2 w-auto">
            <AlertDescription>No pude enviar tu mensaje. Revisa tu conexión e intenta de nuevo.</AlertDescription>
          </Alert>
        )}

        <div className="border-t p-3">
          <PromptInput onSubmit={enviar}>
            <PromptInputBody>
              <PromptInputTextarea
                aria-label="Describe tu problema"
                placeholder="Ej.: «el Outlook no me abre desde esta mañana»"
                value={texto}
                onChange={(e) => setTexto(e.currentTarget.value)}
                maxLength={4000}
              />
            </PromptInputBody>
            <PromptInputFooter className="justify-end">
              <PromptInputSubmit status={status} disabled={!texto.trim() || ocupado} aria-label="Enviar" />
            </PromptInputFooter>
          </PromptInput>
        </div>
      </section>

      <aside className="space-y-3" aria-label="Detalle del caso">
        <PanelRevisando lineas={lineas} />
        <SeguimientoMasivo
          caseId={caseId}
          verComo={persona.id}
          activo={Boolean(masivo?.incidente_id) && !terminado}
          ocupado={ocupado}
          onResponder={(t) => void sendMessage({ text: t })}
        />
        <PanelHipotesis datos={ultimaParte(messages, "hipotesis")} />
        <div className="rounded-lg border bg-card p-3 text-xs text-muted-foreground">
          <p>
            Caso: <code className="text-foreground">{caso?.case_id ?? caseId}</code>
          </p>
          {caso?.traza_url && (
            <a className="mt-1 inline-flex items-center gap-1 underline" href={caso.traza_url} target="_blank" rel="noreferrer">
              Ver traza en Langfuse <ExternalLink className="size-3" aria-hidden />
            </a>
          )}
        </div>
      </aside>

      {/* Botón fijo «Hablar con una persona»: escala de inmediato (el backend lo detecta antes de cualquier LLM). */}
      <Button
        className="fixed right-4 bottom-4 shadow-lg"
        disabled={ocupado || terminado}
        title={terminado ? "Tu caso ya está con soporte o quedó cerrado" : "Pasa tu caso a una persona de soporte"}
        onClick={() => void sendMessage({ text: "Quiero hablar con una persona" })}
      >
        <Headset aria-hidden /> Hablar con una persona
      </Button>
    </div>
  );
}
