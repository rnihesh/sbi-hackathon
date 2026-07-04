import { permanentRedirect } from "next/navigation"

// Canonical URL is /policy (registered on the OAuth consent screen).
export default function PrivacyRedirect() {
  permanentRedirect("/policy")
}
