import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Smartphone } from "lucide-react";

import { AccountSection, Row, btnOutline } from "@/components/account-ui";
import { api } from "@/lib/api";

export const Route = createFileRoute("/account/devices")({
  head: () => ({
    meta: [
      { title: "Connected devices — Haman Health" },
      { name: "description", content: "See which devices share data with Haman Health." },
      { property: "og:title", content: "Connected devices — Haman Health" },
      { property: "og:description", content: "See which devices share data with Haman Health." },
    ],
  }),
  component: DevicesPage,
});

function DevicesPage() {
  const { data } = useQuery({ queryKey: ["devices"], queryFn: api.account.devices });
  return (
    <AccountSection title="Connected devices" description="Device integrations are coming soon. Cough detection always runs on this phone.">
      <div className="card-soft divide-y px-5">
        {data?.map((d) => (
          <Row key={d.id} title={d.name} hint={d.kind}>
            {d.status === "connected" ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-primary-soft px-3 py-1 text-xs font-medium text-primary">
                <Smartphone className="size-3.5" /> Connected
              </span>
            ) : (
              <button disabled className={`${btnOutline} h-9 px-3 text-xs`}>
                Coming soon
              </button>
            )}
          </Row>
        ))}
      </div>
    </AccountSection>
  );
}
