import { ImageResponse } from "next/og"

// iOS applies its own rounding mask to apple-touch-icons, so this stays a
// full-bleed square tile (unlike app/icon.svg, which needs its own rx since
// browser tabs don't mask favicons).
export const size = { width: 180, height: 180 }
export const contentType = "image/png"

export default function AppleIcon() {
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
        }}
      >
        <svg width={126} height={126} viewBox="0 0 32 32" fill="none">
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
    size
  )
}
