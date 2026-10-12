// Static SPA entry point — used when deploying to Apache/static hosting.
// This bypasses TanStack Start's SSR pipeline entirely and mounts React
// directly onto #root, just like create-react-app / Vite plain SPA.
import "./styles.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "@tanstack/react-router";
import { connectNativeLayer } from "./lib/cough-session";
import { getRouter } from "./router";

// Android app only (no-op in a browser). Tried again on load in case the native bridge
// was injected after this script started.
connectNativeLayer();
window.addEventListener("load", connectNativeLayer);

const router = getRouter();

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("No #root element found");

createRoot(rootEl).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
