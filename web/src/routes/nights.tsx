import { Link, createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { AudioLines, Loader2, Moon, Pause, Play, Smartphone, Wind } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { AppShell } from "@/components/app-shell";
import { Disclaimer, PageHeader, Skeleton, StatCard } from "@/components/haman-ui";
import { api, type NightEvent, type NightListItem } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/nights")({
  head: () => ({
    meta: [
      { title: "Night sounds — Haman Health" },
      { name: "description", content: "Coughs, sneezes and snoring heard during each night, with the short clips you allowed." },
      { property: "og:title", content: "Night sounds — Haman Health" },
      { property: "og:description", content: "Coughs, sneezes and snoring heard during each night, with the short clips you allowed." },
    ],
  }),
  component: NightsPage,
});

const EVENT_LABEL: Record<string, string> = { cough: "Cough", sneeze: "Sneeze", snore: "Snore" };

const time = (iso: string, timeZone: string | null) =>
  new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", ...(timeZone ? { timeZone } : {}) });

const nightLabel = (n: NightListItem) =>
  new Date(`${n.date}T12:00:00`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });

/** Plays one clip at a time. Clips need the login token, so they are fetched, not linked. */
function useClipPlayer() {
  const audio = useRef<HTMLAudioElement | null>(null);
  const url = useRef<string | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const [loading, setLoading] = useState<string | null>(null);

  function stop() {
    audio.current?.pause();
    audio.current = null;
    if (url.current) URL.revokeObjectURL(url.current);
    url.current = null;
    setPlaying(null);
  }
  useEffect(() => stop, []);

  async function toggle(clipId: string) {
    if (playing === clipId) return stop();
    stop();
    setLoading(clipId);
    try {
      url.current = URL.createObjectURL(await api.clips.audio(clipId));
      const el = new Audio(url.current);
      el.onended = stop;
      audio.current = el;
      await el.play();
      setPlaying(clipId);
    } catch {
      stop();
      toast.error("That clip could not be played.");
    } finally {
      setLoading(null);
    }
  }

  return { playing, loading, toggle };
}

function EventRow({ event, timeZone, player }: { event: NightEvent; timeZone: string | null; player: ReturnType<typeof useClipPlayer> }) {
  const clipId = event.clipId;
  return (
    <li className={cn("flex items-center gap-3 py-3", !event.counted && "opacity-60")}>
      <span className="grid size-9 shrink-0 place-items-center rounded-full bg-primary-soft text-primary">
        <Wind className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">
          {EVENT_LABEL[event.type] ?? event.type}
          {!event.counted && <span className="ml-2 text-xs font-normal text-muted-foreground">not counted</span>}
        </p>
        <p className="text-xs text-muted-foreground tabular-nums">
          {time(event.at, timeZone)}
          {event.durationMs != null && ` · ${(event.durationMs / 1000).toFixed(1)} s`}
          {event.confidence != null && ` · ${Math.round(event.confidence * 100)}% sure`}
        </p>
      </div>
      {clipId ? (
        <button
          type="button"
          onClick={() => void player.toggle(clipId)}
          disabled={player.loading === clipId}
          aria-label={player.playing === clipId ? "Stop clip" : "Play clip"}
          className="pill grid size-10 shrink-0 place-items-center text-primary hover:bg-muted"
        >
          {player.loading === clipId ? (
            <Loader2 className="size-4 animate-spin" />
          ) : player.playing === clipId ? (
            <Pause className="size-4" />
          ) : (
            <Play className="size-4" />
          )}
        </button>
      ) : (
        <span className="shrink-0 text-xs text-muted-foreground">no clip</span>
      )}
    </li>
  );
}

function NightsPage() {
  const { t } = useI18n();
  const nights = useQuery({ queryKey: ["nights"], queryFn: api.nights.list });
  const [selected, setSelected] = useState<number | null>(null);
  const nightId = selected ?? nights.data?.[0]?.id ?? null;
  const detail = useQuery({
    queryKey: ["nights", nightId],
    queryFn: () => api.nights.get(nightId!),
    enabled: nightId != null,
  });
  const player = useClipPlayer();
  const night = detail.data;

  return (
    <AppShell title={t("nav_nights")}>
      <PageHeader eyebrow="What was heard" title={t("nav_nights")} />
      <div className="space-y-5 px-5 md:px-8">
        {nights.isLoading ? (
          <Skeleton className="h-64" />
        ) : !nights.data?.length ? (
          <div className="card-soft flex items-start gap-3 p-5">
            <Smartphone className="mt-0.5 size-5 shrink-0 text-primary" />
            <div>
              <p className="text-sm font-semibold">No nights yet</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Coughs, sneezes and snoring are detected by the Haman Health app on your phone. After a night with the app, it shows up here.
              </p>
            </div>
          </div>
        ) : (
          <>
            <div className="flex gap-2 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none]">
              {nights.data.map((n) => (
                <button
                  key={n.id}
                  onClick={() => setSelected(n.id)}
                  className={cn(
                    "pill shrink-0 px-4 py-2 text-sm font-medium transition",
                    n.id === nightId ? "border-primary bg-primary text-primary-foreground" : "text-foreground hover:bg-muted",
                  )}
                >
                  {nightLabel(n)}
                </button>
              ))}
            </div>

            {!night ? (
              <Skeleton className="h-64" />
            ) : (
              <>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                  <StatCard label="Coughs" value={night.coughs} icon={Wind} />
                  <StatCard label="Sneezes" value={night.sneezes} icon={Wind} />
                  <StatCard label="Snoring" value={night.snoreMinutes} unit="min" icon={Moon} />
                  <StatCard label="Audio clips" value={night.clips} icon={AudioLines} />
                </div>

                {night.source === "web" && (
                  <p className="text-xs text-muted-foreground">
                    This night was started from the web app, which cannot listen. Its numbers are not real detections.
                  </p>
                )}

                <section className="card-soft px-5 py-2">
                  <p className="pt-3 text-sm font-semibold">Coughs and sneezes</p>
                  {night.events.length === 0 ? (
                    <p className="py-4 text-sm text-muted-foreground">Nothing was detected this night.</p>
                  ) : (
                    <ul className="divide-y">
                      {night.events.map((e) => (
                        <EventRow key={e.id} event={e} timeZone={night.timezone} player={player} />
                      ))}
                    </ul>
                  )}
                </section>

                {night.snoreEpisodes.length > 0 && (
                  <section className="card-soft px-5 py-2">
                    <p className="pt-3 text-sm font-semibold">Snoring</p>
                    <ul className="divide-y">
                      {night.snoreEpisodes.map((ep) => (
                        <li key={ep.startedAt} className="flex items-center justify-between gap-3 py-3 text-sm">
                          <span className="tabular-nums">
                            {time(ep.startedAt, night.timezone)} – {time(ep.endedAt, night.timezone)}
                          </span>
                          <span className="text-muted-foreground">{ep.snoreCount.toLocaleString()} snores</span>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}

                <p className="text-xs text-muted-foreground">
                  Clips are short recordings of single events, kept for 90 days. You can switch them off or delete them under{" "}
                  <Link to="/account/privacy" className="text-primary underline-offset-2 hover:underline">
                    Privacy
                  </Link>
                  .
                </p>
              </>
            )}
          </>
        )}
      </div>
      <Disclaimer />
    </AppShell>
  );
}
