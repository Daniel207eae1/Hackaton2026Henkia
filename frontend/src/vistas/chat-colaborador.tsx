import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import { ExternalLink, Fingerprint, Headset, MessageSquarePlus } from "lucide-react";
import { useMemo, useState } from "react";

import isotipo from "@/assets/isotipo.svg";
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
import { IndicadorEtapa } from "@/components/caso/indicador-etapa";
import { IndicadorProgreso } from "@/components/caso/indicador-progreso";
import { Fuentes, PanelHipotesis } from "@/components/caso/panel-hipotesis";
import { PanelRevisando } from "@/components/caso/panel-revisando";
import { TarjetaAccion } from "@/components/caso/tarjeta-accion";
import {
  BotonAdjuntar,
  ListaAdjuntos,
  MAX_CAPTURA_BYTES,
  MAX_CAPTURAS,
  TarjetaCaptura,
  TIPOS_CAPTURA,
} from "@/components/caso/capturas";
import { SeguimientoMasivo, TarjetaMasivo } from "@/components/caso/tarjeta-masivo";
import { TarjetaCierre, TarjetaEscalamiento } from "@/components/caso/tarjeta-resultado";
import { Valoracion } from "@/components/caso/valoracion";
import { leerModeloGuardado, SelectorModelo } from "@/components/selector-modelo";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { API_URL, type Persona } from "@/lib/api";
import { idUltimaEjecutada, lineasRevisando, ultimaParte, type MensajeCaso } from "@/lib/mensajes";

/** Ejemplos que solo rellenan la caja de texto (no se envían solos). */
const EJEMPLOS = [
  "El Outlook no me abre desde esta mañana",
  "Teams no me deja entrar a las reuniones",
  "La impresora no imprime nada",
];

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
        // Solo el último mensaje: el historial oficial vive en el backend y así no se reenvían capturas viejas.
        prepareSendMessagesRequest: ({ id, messages, trigger, messageId }) => ({
          body: { id, messages: messages.slice(-1), trigger, messageId },
        }),
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
  // La guía de la KB más reciente pregunta «¿ya te funciona?» mientras el caso siga en la etapa Guia.
  const ultimoMensaje = messages.at(-1);
  // Último hallazgo del turno en curso (para que el indicador diga qué se acaba de revisar).
  const detalleTurno =
    ultimoMensaje?.role === "assistant"
      ? (ultimoMensaje.parts.filter((p) => p.type === "data-revisando").at(-1)?.data.texto ?? null)
      : null;
  const ultimaGuia =
    terminado || ultimoMensaje?.role !== "assistant"
      ? null
      : (ultimoMensaje.parts.filter((p) => p.type === "data-fuentes").at(-1)?.id ?? null);
  // Solo la última acción ejecutada pide «¿ya te funciona?», y solo mientras el caso siga abierto.
  const ultimaEjecutada = terminado ? null : (idUltimaEjecutada(messages) ?? null);

  const [errorAdjunto, setErrorAdjunto] = useState<string | null>(null);
  const enviar = (m: PromptInputMessage) => {
    const limpio = m.text.trim();
    if ((!limpio && m.files.length === 0) || ocupado) return;
    setErrorAdjunto(null);
    void sendMessage(m.files.length ? { text: limpio, files: m.files } : { text: limpio });
    setTexto("");
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
      {/* El chat nunca supera la altura de la pantalla: la conversación hace scroll por dentro.
          `--alto-barra` lo publica la barra superior; en móvil queda espacio abajo para «Hablar con una persona». */}
      <section
        aria-label="Conversación con soporte"
        className="flex h-[calc(100dvh-var(--alto-barra,4rem)-6rem)] min-h-[420px] flex-col overflow-hidden rounded-2xl border bg-card shadow-sm lg:h-[calc(100dvh-var(--alto-barra,4rem)-2rem)]"
      >
        <header className="space-y-2 border-b bg-muted/40 px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <h1 className="font-display text-xl leading-none font-semibold">Asistente de soporte</h1>
              <p className="hidden text-xs text-muted-foreground sm:block">Outlook · Teams · Excel · Word · OneDrive · Impresión</p>
            </div>
            <div className="flex w-full items-center gap-2 sm:w-auto">
              <SelectorModelo valor={modelo} onCambio={onModelo} />
              <Button variant="outline" size="sm" onClick={onNuevo}>
                <MessageSquarePlus aria-hidden /> Nuevo caso
              </Button>
            </div>
          </div>
          <IndicadorEtapa etapa={etapa} />
        </header>

        <Conversation className="min-h-0 flex-1">
          <ConversationContent>
            {messages.length === 0 ? (
              <ConversationEmptyState>
                <img src={isotipo} alt="" className="size-10 opacity-90 sm:size-14" />
                <div className="space-y-1">
                  <h2 className="font-display text-2xl sm:text-3xl leading-none font-semibold">Hola, {persona.nombre.split(" ")[0]}</h2>
                  <p className="max-w-md text-sm text-muted-foreground">
                    Cuéntame qué te está pasando con Outlook, Teams, Excel, Word, OneDrive o la impresora. Reviso tu
                    equipo antes de preguntarte y nada se cambia sin tu autorización.
                  </p>
                </div>
                <ul aria-label="Ejemplos para empezar" className="flex max-w-lg flex-wrap justify-center gap-2">
                  {EJEMPLOS.map((e) => (
                    <li key={e}>
                      <button
                        type="button"
                        onClick={() => setTexto(e)}
                        className="rounded-full border bg-background px-3 py-1 text-xs text-foreground transition-colors hover:border-primary hover:bg-accent"
                      >
                        {e}
                      </button>
                    </li>
                  ))}
                </ul>
              </ConversationEmptyState>
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
                      if (p.type === "data-fuentes")
                        return (
                          <Fuentes
                            key={p.id ?? i}
                            datos={p.data}
                            onConfirmar={
                              p.id === ultimaGuia && etapa === "Guia" && !ocupado
                                ? (t: string) => void sendMessage({ text: t })
                                : undefined
                            }
                          />
                        );
                      // Solo la imagen que adjuntó el propio usuario (data URL local): nunca una URL remota.
                      if (p.type === "file" && m.role === "user" && p.url.startsWith("data:image/"))
                        return (
                          <img
                            key={i}
                            src={p.url}
                            alt={`Captura adjunta: ${p.filename ?? "imagen"}`}
                            className="max-h-40 rounded-md border"
                          />
                        );
                      if (p.type === "data-captura") return <TarjetaCaptura key={p.id ?? i} datos={p.data} />;
                      if (p.type === "data-masivo") return <TarjetaMasivo key={p.id ?? i} datos={p.data} />;
                      return null;
                    })}
                  </MessageContent>
                </Message>
              ))
            )}
            {ocupado && (
              <IndicadorProgreso
                etapa={status === "submitted" ? "Recepcion" : etapa}
                detalle={status === "streaming" ? detalleTurno : null}
              />
            )}
            {terminado && !ocupado && <Valoracion caseId={caseId} verComo={persona.id} />}
          </ConversationContent>
          <ConversationScrollButton />
        </Conversation>

        {error && (
          <Alert variant="destructive" className="mx-4 mb-2 w-auto bg-danger-soft">
            <AlertDescription>No pude enviar tu mensaje. Revisa tu conexión e intenta de nuevo.</AlertDescription>
          </Alert>
        )}

        <div className="border-t bg-muted/30 p-3">
          {errorAdjunto && (
            <p role="alert" className="mb-2 text-sm text-destructive">
              {errorAdjunto}
            </p>
          )}
          <PromptInput
            className="rounded-xl bg-card shadow-xs"
            onSubmit={enviar}
            accept={TIPOS_CAPTURA}
            multiple
            maxFiles={MAX_CAPTURAS}
            maxFileSize={MAX_CAPTURA_BYTES}
            onError={(e) =>
              setErrorAdjunto(
                e.code === "max_files"
                  ? `Máximo ${MAX_CAPTURAS} capturas por mensaje.`
                  : e.code === "max_file_size"
                    ? "Cada captura debe pesar menos de 5 MB."
                    : "Solo se aceptan imágenes PNG, JPEG o WebP.",
              )
            }
          >
            <ListaAdjuntos />
            <PromptInputBody>
              <PromptInputTextarea
                aria-label="Describe tu problema"
                placeholder="Ej.: «el Outlook no me abre desde esta mañana»"
                value={texto}
                onChange={(e) => setTexto(e.currentTarget.value)}
                maxLength={4000}
              />
            </PromptInputBody>
            <PromptInputFooter className="justify-between">
              <BotonAdjuntar disabled={ocupado} />
              <PromptInputSubmit status={status} disabled={ocupado} aria-label="Enviar" />
            </PromptInputFooter>
          </PromptInput>
        </div>
      </section>

      <aside
        className="space-y-3 pb-16 lg:max-h-[calc(100dvh-var(--alto-barra,4rem)-2rem)] lg:overflow-y-auto lg:pb-16"
        aria-label="Detalle del caso"
      >
        <PanelRevisando lineas={lineas} />
        <SeguimientoMasivo
          caseId={caseId}
          verComo={persona.id}
          activo={Boolean(masivo?.incidente_id) && !terminado}
          ocupado={ocupado}
          onResponder={(t) => void sendMessage({ text: t })}
        />
        <PanelHipotesis datos={ultimaParte(messages, "hipotesis")} />
        <div className="rounded-xl border bg-card p-3 text-xs text-muted-foreground shadow-xs">
          <p className="flex items-center gap-1.5">
            <Fingerprint className="size-3.5" aria-hidden /> Caso:{" "}
            <code className="truncate rounded bg-muted px-1.5 py-0.5 font-mono text-foreground">{caso?.case_id ?? caseId}</code>
          </p>
          {caso?.traza_url && (
            <a
              className="mt-2 inline-flex items-center gap-1 font-medium text-primary underline-offset-4 hover:underline"
              href={caso.traza_url}
              target="_blank"
              rel="noreferrer"
            >
              Ver traza en Langfuse <ExternalLink className="size-3" aria-hidden />
            </a>
          )}
        </div>
      </aside>

      {/* Botón fijo «Hablar con una persona»: escala de inmediato (el backend lo detecta antes de cualquier LLM). */}
      <Button
        size="lg"
        className="fixed right-4 bottom-4 z-30 h-11 rounded-full bg-brand-dark-2 px-5 text-white shadow-lg ring-1 ring-white/10 hover:bg-brand-dark dark:bg-brand-green-bright dark:text-brand-dark dark:hover:bg-brand-green"
        disabled={ocupado || terminado}
        title={terminado ? "Tu caso ya está con soporte o quedó cerrado" : "Pasa tu caso a una persona de soporte"}
        onClick={() => void sendMessage({ text: "Quiero hablar con una persona" })}
      >
        <Headset aria-hidden /> Hablar con una persona
      </Button>
    </div>
  );
}
