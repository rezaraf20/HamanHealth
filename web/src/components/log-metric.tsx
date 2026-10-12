import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { btnPrimary, input } from "@/components/account-ui";
import { StatCard } from "@/components/haman-ui";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api, localToday, type Observation } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Numbers the user enters by hand until a device reports them. One entry per day and
 * kind: saving the same day again corrects it rather than adding to it.
 */
export type LogKind = "sleep" | "weight" | "activity" | "medications";

type Field = { metric: string; label: string; unit: string; min: number; max: number; step: number };

const KINDS: Record<LogKind, { title: string; hint: string; fields: Field[] }> = {
  sleep: {
    title: "Log sleep",
    hint: "How long you slept. For a night, pick the day you woke up.",
    fields: [{ metric: "sleep.duration", label: "Hours slept", unit: "h", min: 0, max: 24, step: 0.25 }],
  },
  weight: {
    title: "Log weight",
    hint: "Your weight on that day.",
    fields: [{ metric: "body.weight", label: "Weight", unit: "kg", min: 20, max: 400, step: 0.1 }],
  },
  activity: {
    title: "Log activity",
    hint: "Your total steps for that day.",
    fields: [{ metric: "activity.steps", label: "Steps", unit: "steps", min: 0, max: 200000, step: 1 }],
  },
  medications: {
    title: "Log medications",
    hint: "How many of that day's planned doses you took.",
    fields: [
      { metric: "medication.taken", label: "Doses taken", unit: "taken", min: 0, max: 50, step: 1 },
      { metric: "medication.planned", label: "Doses planned", unit: "planned", min: 1, max: 50, step: 1 },
    ],
  },
};

const readingId = (kind: LogKind, date: string) => `manual-${kind}-${date}`;

/** Noon local time on that date, so the entry lands on the right day in any timezone. */
function noonOn(date: string): string {
  const [y, m, d] = date.split("-").map(Number);
  return new Date(y!, m! - 1, d!, 12).toISOString();
}

function validate(kind: LogKind, raw: Record<string, string>): { values: Record<string, number> } | { error: string } {
  const values: Record<string, number> = {};
  for (const f of KINDS[kind].fields) {
    const text = (raw[f.metric] ?? "").trim().replace(",", ".");
    const n = Number(text);
    if (!text || !Number.isFinite(n)) return { error: `Enter a number for ${f.label.toLowerCase()}.` };
    if (n < f.min || n > f.max) return { error: `${f.label} should be between ${f.min} and ${f.max.toLocaleString()}.` };
    if (f.step === 1 && !Number.isInteger(n)) return { error: `${f.label} should be a whole number.` };
    values[f.metric] = n;
  }
  if (kind === "medications" && values["medication.taken"]! > values["medication.planned"]!) {
    return { error: "Doses taken can't be more than doses planned." };
  }
  return { values };
}

type Entry = { id: string; date: string; values: Record<string, number> };

/** Groups stored values back into the entries the user made, newest day first. */
function toEntries(kind: LogKind, rows: Observation[]): Entry[] {
  const byId = new Map<string, Entry>();
  for (const o of rows) {
    if (!o.reading_id) continue;
    const entry = byId.get(o.reading_id) ?? { id: o.reading_id, date: o.local_date, values: {} };
    entry.values[o.metric] = o.value;
    byId.set(o.reading_id, entry);
  }
  const complete = [...byId.values()].filter((e) => KINDS[kind].fields.every((f) => f.metric in e.values));
  return complete.sort((a, b) => b.date.localeCompare(a.date));
}

function describe(kind: LogKind, e: Entry): string {
  if (kind === "medications") return `${e.values["medication.taken"]} of ${e.values["medication.planned"]} doses`;
  const f = KINDS[kind].fields[0]!;
  return `${e.values[f.metric]!.toLocaleString()} ${f.unit}`;
}

const formatDay = (date: string) =>
  new Date(`${date}T12:00:00`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });

export function LogMetricDialog({ kind, open, onOpenChange }: { kind: LogKind; open: boolean; onOpenChange: (open: boolean) => void }) {
  const cfg = KINDS[kind];
  const queryClient = useQueryClient();
  const [date, setDate] = useState(localToday);
  const [raw, setRaw] = useState<Record<string, string>>({});

  const recent = useQuery({
    queryKey: ["observations", kind],
    queryFn: () => api.observations.list(cfg.fields.map((f) => f.metric)),
    enabled: open,
  });
  const entries = toEntries(kind, recent.data ?? []);

  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["observations", kind] }),
      queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
    ]);

  const save = useMutation({
    mutationFn: (values: Record<string, number>) =>
      api.observations.add({
        reading_id: readingId(kind, date),
        measured_at: noonOn(date),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        values: Object.entries(values).map(([metric, value]) => ({ metric, value })),
      }),
    onSuccess: async () => {
      await refresh();
      toast.success(`Saved for ${formatDay(date)}`);
      setRaw({});
      onOpenChange(false);
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Could not save. Please try again."),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.observations.remove(id),
    onSuccess: async () => {
      await refresh();
      toast.success("Entry deleted");
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Could not delete that entry."),
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!date || date > localToday()) return void toast.error("Pick today or an earlier day.");
    const result = validate(kind, raw);
    if ("error" in result) return void toast.error(result.error);
    save.mutate(result.values);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{cfg.title}</DialogTitle>
          <DialogDescription>{cfg.hint}</DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="space-y-4">
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium">Day</span>
            <input type="date" className={input} value={date} max={localToday()} onChange={(e) => setDate(e.target.value)} required />
          </label>
          {cfg.fields.map((f, i) => (
            <label key={f.metric} className="block">
              <span className="mb-1.5 block text-sm font-medium">{f.label}</span>
              <input
                className={input}
                inputMode={f.step === 1 ? "numeric" : "decimal"}
                autoFocus={i === 0}
                placeholder={f.unit}
                value={raw[f.metric] ?? ""}
                onChange={(e) => setRaw((r) => ({ ...r, [f.metric]: e.target.value }))}
              />
            </label>
          ))}
          {entries.some((e) => e.id === readingId(kind, date)) && (
            <p className="text-xs text-muted-foreground">You already have an entry for this day. Saving replaces it.</p>
          )}
          <button className={`${btnPrimary} w-full`} disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save"}
          </button>
        </form>

        {entries.length > 0 && (
          <div>
            <p className="mb-1 text-sm font-medium">Recent entries</p>
            <ul className="divide-y">
              {entries.slice(0, 7).map((e) => (
                <li key={e.id} className="flex items-center gap-3 py-2 text-sm">
                  <span className="w-28 shrink-0 text-muted-foreground">{formatDay(e.date)}</span>
                  <span className="min-w-0 flex-1 truncate font-medium">{describe(kind, e)}</span>
                  <button
                    type="button"
                    aria-label={`Delete entry for ${formatDay(e.date)}`}
                    className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-destructive disabled:opacity-50"
                    disabled={remove.isPending}
                    onClick={() => remove.mutate(e.id)}
                  >
                    <Trash2 className="size-4" />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** A stat card the user can tap to enter that number themselves. */
export function LogStatCard({
  kind,
  label,
  value,
  unit,
  icon,
  className,
}: {
  kind: LogKind;
  label: string;
  value: string | number;
  unit: string;
  icon: LucideIcon;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className={cn("block h-full w-full text-left", className)} aria-label={`${label}: ${KINDS[kind].title}`}>
        <StatCard label={label} value={value} unit={unit} icon={icon} className="h-full transition hover:bg-muted/50">
          <p className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary">
            <Plus className="size-3.5" /> Add entry
          </p>
        </StatCard>
      </button>
      {open && <LogMetricDialog kind={kind} open={open} onOpenChange={setOpen} />}
    </>
  );
}
