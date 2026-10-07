import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FileText, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { AppShell } from "@/components/app-shell";
import { Skeleton } from "@/components/haman-ui";
import { api } from "@/lib/api";

export const Route = createFileRoute("/records/$recordId")({
  head: () => ({
    meta: [
      { title: "Record detail — Haman Health" },
      { name: "description", content: "Extracted information from your uploaded document. Not a medical interpretation." },
      { property: "og:title", content: "Record detail — Haman Health" },
      { property: "og:description", content: "Extracted information from your uploaded document. Not a medical interpretation." },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: RecordDetailPage,
});

function RecordDetailPage() {
  const { recordId } = Route.useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data, error } = useQuery({ queryKey: ["records", recordId], queryFn: () => api.records.get(recordId) });

  async function remove() {
    if (!confirm("Delete this record? This cannot be undone.")) return;
    await api.records.remove(recordId);
    await qc.invalidateQueries({ queryKey: ["records"] });
    toast.success("Record deleted");
    navigate({ to: "/records" });
  }

  return (
    <AppShell title="Record">
      <div className="px-5 pt-6 md:max-w-3xl md:px-8 md:pt-10">
        <Link to="/records" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-primary">
          <ArrowLeft className="size-4" /> Records
        </Link>

        {error && <p className="mt-6 text-sm text-muted-foreground">This record could not be found.</p>}
        {!data && !error && <Skeleton className="mt-6 h-64" />}

        {data && (
          <div className="mt-4 space-y-4">
            <div className="card-soft flex items-start gap-4 p-5">
              <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-primary-soft text-primary">
                <FileText className="size-5" />
              </span>
              <div className="min-w-0 flex-1">
                <h1 className="text-xl font-semibold tracking-tight">{data.title}</h1>
                <p className="mt-1 text-sm text-muted-foreground">
                  {data.fileName} · {data.pages} page{data.pages > 1 ? "s" : ""} · {data.sizeKb} KB
                </p>
                <p className="text-sm text-muted-foreground">Uploaded {new Date(data.date).toLocaleDateString()}</p>
              </div>
              <button onClick={remove} aria-label="Delete" className="rounded-full p-2 text-muted-foreground hover:bg-muted hover:text-destructive">
                <Trash2 className="size-4" />
              </button>
            </div>

            <section className="card-soft p-5">
              <h2 className="text-base font-semibold">Extracted information</h2>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Text found on the document, as written. This is not a medical interpretation — discuss results with your GP.
              </p>
              <dl className="mt-4 divide-y">
                {data.extracted.map((f) => (
                  <div key={f.label} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 py-3">
                    <div className="min-w-0">
                      <dt className="text-xs text-muted-foreground">{f.label}</dt>
                      <dd className="truncate text-sm font-medium">{f.value}</dd>
                    </div>
                    <span className="rounded-full bg-secondary px-2 py-0.5 text-[11px] text-secondary-foreground">
                      {Math.round(f.confidence * 100)}% match
                    </span>
                  </div>
                ))}
              </dl>
            </section>
          </div>
        )}
      </div>
    </AppShell>
  );
}
