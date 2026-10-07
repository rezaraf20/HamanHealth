import { Link, createFileRoute } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, FileImage, FileText, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { AppShell } from "@/components/app-shell";
import { Disclaimer, PageHeader, Skeleton } from "@/components/haman-ui";
import { api, type RecordType } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export const Route = createFileRoute("/records/")({
  head: () => ({
    meta: [
      { title: "Records — Haman Health" },
      { name: "description", content: "Upload letters, lab results and prescriptions. We extract the written information, not an interpretation." },
      { property: "og:title", content: "Records — Haman Health" },
      { property: "og:description", content: "Upload letters, lab results and prescriptions. We extract the written information, not an interpretation." },
    ],
  }),
  component: RecordsPage,
});

const RECORD_TYPES: { value: RecordType; label: string }[] = [
  { value: "lab", label: "Lab results" },
  { value: "letter", label: "Letter" },
  { value: "prescription", label: "Prescription" },
  { value: "imaging", label: "Imaging report" },
  { value: "other", label: "Other" },
];

function RecordsPage() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["records"], queryFn: api.records.list });
  const [type, setType] = useState<RecordType>("lab");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function onFile(file?: File) {
    if (!file) return;
    if (!/^(application\/pdf|image\/)/.test(file.type)) {
      toast.error("Please choose a PDF or an image.");
      return;
    }
    setBusy(true);
    try {
      await api.records.upload(file, type);
      await qc.invalidateQueries({ queryKey: ["records"] });
      toast.success("Uploaded. Extracted information is ready.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <AppShell title={t("nav_records")}>
      <PageHeader eyebrow="Documents" title={t("nav_records")} />
      <div className="space-y-5 px-5 md:max-w-3xl md:px-8">
        <section className="card-soft p-5">
          <p className="text-sm font-semibold">Upload a document</p>
          <p className="mt-0.5 text-xs text-muted-foreground">PDF or image. We show what's written on it as extracted information.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {RECORD_TYPES.map((rt) => (
              <button
                key={rt.value}
                onClick={() => setType(rt.value)}
                className={`pill px-3 py-1.5 text-xs font-medium ${type === rt.value ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted"}`}
              >
                {rt.label}
              </button>
            ))}
          </div>
          <input ref={fileRef} type="file" accept="application/pdf,image/*" className="hidden" onChange={(e) => void onFile(e.target.files?.[0])} />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={busy}
            className="mt-4 flex h-28 w-full flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed text-sm text-muted-foreground transition hover:border-primary hover:bg-primary-soft/40 hover:text-primary disabled:opacity-60"
          >
            <Upload className="size-5" />
            {busy ? "Processing…" : "Tap to choose a file"}
          </button>
        </section>

        <section>
          <h2 className="mb-3 text-base font-semibold">Your records</h2>
          {!data ? (
            <Skeleton className="h-40" />
          ) : (
            <ul className="space-y-2">
              {data.map((r) => (
                <li key={r.id}>
                  <Link to="/records/$recordId" params={{ recordId: r.id }} className="card-soft flex items-center gap-3 p-4 hover:bg-muted/40">
                    <span className="grid size-10 shrink-0 place-items-center rounded-full bg-primary-soft text-primary">
                      {r.mime.startsWith("image/") ? <FileImage className="size-4" /> : <FileText className="size-4" />}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{r.title}</p>
                      <p className="text-xs text-muted-foreground">
                        {RECORD_TYPES.find((x) => x.value === r.type)?.label} · {new Date(r.date).toLocaleDateString()} · {r.sizeKb} KB
                      </p>
                    </div>
                    <ChevronRight className="size-4 text-muted-foreground" />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
      <Disclaimer />
    </AppShell>
  );
}
