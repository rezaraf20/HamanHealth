// Static SPA entry point — used when deploying to Apache/static hosting.
// This bypasses TanStack Start's SSR pipeline entirely and mounts React
// directly onto #root, just like create-react-app / Vite plain SPA.
import "./styles.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "@tanstack/react-router";
import { getRouter } from "./router";

const router = getRouter();

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("No #root element found");

createRoot(rootEl).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
