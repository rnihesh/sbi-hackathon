import { ImageResponse } from "next/og"

// The image never varies per-request - render it once at build time and
// serve it as a static asset instead of regenerating it on every request.
export const dynamic = "force-static"

// A 512x512 raster icon for the PWA manifest, generated via `ImageResponse`
// so its geometry always matches `app/icon.svg` (same rounded-square tile,
// same chevron mark) instead of drifting as a hand-exported PNG would. Lives
// as a plain Route Handler rather than the `icon.tsx` metadata convention:
// that convention only ever produces a single `/icon` route, but the
// manifest also needs an explicit large PNG alongside the scalable SVG (some
// installability checks and Android's adaptive-icon pipeline expect a raster
// asset, not just SVG).
const SIZE = 512
// icon.svg's viewBox is 0 0 32 32 with rx="7" - keep the corner radius and
// chevron proportions identical, just scaled up.
const SCALE = SIZE / 32

export async function GET() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#D97757",
          borderRadius: 7 * SCALE,
        }}
      >
        <svg width={SIZE} height={SIZE} viewBox="0 0 32 32" fill="none">
          <path
            d="M9 8l8 8-8 8"
            stroke="#FFFFFF"
            strokeWidth={2.8}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M17 8l8 8-8 8"
            stroke="#FFFFFF"
            strokeWidth={2.8}
            strokeLinecap="round"
            strokeLinejoin="round"
            opacity={0.5}
          />
        </svg>
      </div>
    ),
    { width: SIZE, height: SIZE }
  )
}
