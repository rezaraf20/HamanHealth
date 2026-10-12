import { createFileRoute } from "@tanstack/react-router";

import { ProfilePage } from "@/components/profile-page";

export const Route = createFileRoute("/account/")({
  head: () => ({
    meta: [
      { title: "Profile — Haman Health" },
      { name: "description", content: "Manage your Haman Health profile, security, privacy and preferences." },
      { property: "og:title", content: "Profile — Haman Health" },
      { property: "og:description", content: "Manage your Haman Health profile, security, privacy and preferences." },
    ],
  }),
  component: ProfilePage,
});
