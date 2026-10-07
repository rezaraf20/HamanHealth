import { ArrowUp, MessageCircle, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, type SupportMessage } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const QUICK = ["How do I start a night session?", "How do I upload a record?", "Where can I export my data?"];

export function SupportChat() {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<SupportMessage[]>([{ role: "assistant", content: t("support_hint") }]);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, open]);

  async function send(text: string) {
    const content = text.trim();
    if (!content || busy) return;
    const next: SupportMessage[] = [...messages, { role: "user", content }];
    setMessages(next);
    setInput("");
    setBusy(true);
    try {
      const { reply } = await api.support.chat(next);
      setMessages([...next, { role: "assistant", content: reply }]);
    } catch {
      setMessages([...next, { role: "assistant", content: "Sorry, I couldn't reach support right now. Please try again in a moment." }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label={t("support_title")}
        className={cn(
          "fixed right-4 z-40 grid size-13 place-items-center rounded-full bg-foreground text-background shadow-float transition-transform hover:scale-105",
          "bottom-[calc(env(safe-area-inset-bottom)+5.25rem)] md:bottom-6",
        )}
      >
        {open ? <X className="size-5" /> : <MessageCircle className="size-5" />}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label={t("support_title")}
          className={cn(
            "fixed z-40 flex flex-col overflow-hidden card-soft text-card-foreground animate-in fade-in slide-in-from-bottom-4",
            "inset-x-3 bottom-[calc(env(safe-area-inset-bottom)+9rem)] max-h-[60vh] md:inset-x-auto md:right-6 md:bottom-24 md:h-[520px] md:max-h-[70vh] md:w-[380px]",
          )}
        >
          <div className="flex items-center gap-3 border-b px-4 py-3">
            <span className="size-8 rounded-full orb" />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-card-foreground">{t("support_title")}</p>
              <p className="truncate text-[11px] text-muted-foreground">App help only · no medical advice</p>
            </div>
          </div>

          <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
            {messages.map((m, i) => (
              <div key={i} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
                <p
                  className={cn(
                    "max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed",
                    m.role === "user" ? "rounded-br-md bg-primary text-primary-foreground" : "rounded-bl-md bg-muted text-foreground",
                  )}
                >
                  {m.content}
                </p>
              </div>
            ))}
            {busy && (
              <div className="flex justify-start">
                <p className="rounded-2xl rounded-bl-md bg-muted px-3.5 py-2.5 text-sm text-muted-foreground">…</p>
              </div>
            )}
            {messages.length === 1 && (
              <div className="flex flex-wrap gap-2 pt-1">
                {QUICK.map((q) => (
                  <button key={q} onClick={() => void send(q)} className="pill px-3 py-1.5 text-xs text-foreground hover:bg-muted">
                    {q}
                  </button>
                ))}
              </div>
            )}
            <div ref={endRef} />
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              void send(input);
            }}
            className="flex items-center gap-2 border-t p-3"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={t("support_placeholder")}
              className="h-11 flex-1 rounded-full border bg-background px-4 text-sm outline-none focus:ring-2 focus:ring-ring/40"
            />
            <button
              type="submit"
              disabled={busy || !input.trim()}
              aria-label="Send"
              className="grid size-11 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground disabled:opacity-40"
            >
              <ArrowUp className="size-4" />
            </button>
          </form>
        </div>
      )}
    </>
  );
}
