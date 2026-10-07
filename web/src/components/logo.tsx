import logoDark from "@/assets/haman-logo.png.asset.json";
import logoWhite from "@/assets/haman-logo-white.png.asset.json";
import { cn } from "@/lib/utils";

/**
 * Haman Health wordmark. `variant="white"` is the light-on-dark version, used on
 * the night theme and other dark backgrounds.
 */
export function Logo({
  variant = "dark",
  className,
}: {
  variant?: "dark" | "white";
  className?: string;
}) {
  const src = variant === "white" ? logoWhite.url : logoDark.url;
  return <img src={src} alt="Haman Health" className={cn("h-8 w-auto select-none", className)} />;
}
