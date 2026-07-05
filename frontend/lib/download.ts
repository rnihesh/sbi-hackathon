/**
 * Downloads a same-origin-cookied file from the API (e.g. a console CSV export).
 *
 * The API lives on a different subdomain from the frontend in production, so a
 * plain `<a href="...">` cannot carry the httpOnly session cookie there - the
 * browser only attaches cookies to a cross-origin navigation if the request itself
 * is same-site, which a direct link to the API host is not. Instead this fetches
 * the file with `credentials: "include"` (same as `lib/api.ts`), then hands the
 * response blob to the browser via a throwaway `<a download>` + object URL.
 */

import { API_URL } from "@/lib/api"

export async function downloadFile(path: string, filename: string): Promise<void> {
  const res = await fetch(`${API_URL}${path}`, { credentials: "include" })
  if (!res.ok) {
    throw new Error(`Download failed: ${res.status} ${res.statusText}`)
  }

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  try {
    const link = document.createElement("a")
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
  } finally {
    URL.revokeObjectURL(url)
  }
}
