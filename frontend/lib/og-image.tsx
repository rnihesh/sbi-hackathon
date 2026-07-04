import { ImageResponse } from "next/og"

/**
 * Shared 1200x630 social-preview renderer for `app/opengraph-image.tsx` and
 * `app/twitter-image.tsx` - same brand tile, same copy, one place to edit.
 * Kept in `lib/` (not a special Next.js filename) so both routes can import
 * and re-export the pieces Next reads statically (`size`, `contentType`, `alt`).
 */

export const OG_IMAGE_SIZE = { width: 1200, height: 630 }
export const OG_IMAGE_ALT = "Sarathi - A banker in every pocket"
export const OG_IMAGE_CONTENT_TYPE = "image/png"

export function renderOgImage(): ImageResponse {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "88px 96px",
          background: "#FAFAF9",
        }}
      >
        <svg
          width={88}
          height={88}
          viewBox="0 0 32 32"
          fill="none"
          style={{ marginBottom: 36 }}
        >
          <path
            d="M9 8l8 8-8 8"
            stroke="#D97757"
            strokeWidth={2.6}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M17 8l8 8-8 8"
            stroke="#D97757"
            strokeWidth={2.6}
            strokeLinecap="round"
            strokeLinejoin="round"
            opacity={0.5}
          />
        </svg>
        <div
          style={{
            display: "flex",
            fontSize: 96,
            fontWeight: 700,
            color: "#1C1917",
            letterSpacing: "-0.03em",
          }}
        >
          Sarathi
        </div>
        <div
          style={{
            display: "flex",
            fontSize: 34,
            color: "#78716C",
            marginTop: 16,
          }}
        >
          A banker in every pocket.
        </div>
        <div
          style={{
            display: "flex",
            fontSize: 22,
            color: "#A8A29E",
            marginTop: 64,
            fontFamily: "monospace",
          }}
        >
          sarathi.niheshr.com
        </div>
      </div>
    ),
    OG_IMAGE_SIZE
  )
}
