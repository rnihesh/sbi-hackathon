import type { MetadataRoute } from "next"

/**
 * PWA manifest (installability - "Add to Home Screen"). Deliberately no
 * service worker / offline caching: Sarathi is an authed banking app, so
 * every screen must reflect live account/session state - caching API
 * responses (or even the app shell) risks showing stale balances or a
 * signed-out user their signed-in session after a device is shared. Being
 * installable (icon, standalone display, theme color) is worth having on its
 * own; offline support is not.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Sarathi",
    short_name: "Sarathi",
    description:
      "Sarathi is an agentic AI relationship manager for banking - acquisition, adoption, and engagement, all in one conversation.",
    start_url: "/app/home",
    display: "standalone",
    background_color: "#FAFAF9",
    theme_color: "#D97757",
    icons: [
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "maskable" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
    ],
  }
}
