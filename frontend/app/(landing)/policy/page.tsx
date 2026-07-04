import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "Privacy Policy",
}

export default function PrivacyPage() {
  return (
    <div className="px-4 py-16 sm:px-6 sm:py-20">
      <div className="mx-auto max-w-[65ch]">
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Privacy Policy</h1>
        <p className="mt-2 text-sm text-muted-foreground">Last updated 5 July 2026</p>

        <div className="prose-sarathi prose mt-10 max-w-none dark:prose-invert">
          <h2>1. Overview</h2>
          <p>
            Sarathi is a hackathon prototype demonstrating agentic AI banking, built by Nihesh
            Rachakonda. This policy explains, specifically and honestly, what data the prototype
            collects, how it&apos;s used, and how you can have it deleted. Because Sarathi runs
            on synthetic financial data, most of what it shows about &quot;your finances&quot; is
            fabricated for the demo - this policy covers the real data it does collect: your
            identity, your chat messages, and the demo data you choose to generate.
          </p>

          <h2>2. Information we collect</h2>
          <ul>
            <li>
              <strong>Account identity.</strong> If you sign in with Google, we receive your
              name and email address from Google&apos;s OAuth flow. If you sign in by email
              code, we store the email address you verify. If you register a passkey, we store
              only its public key and metadata (device label, creation date) - never a private
              key or biometric data, which never leave your device.
            </li>
            <li>
              <strong>Chat content.</strong> Messages you send to Sarathi, and the responses it
              generates, are stored so your conversation history persists across sessions.
            </li>
            <li>
              <strong>Demo activity.</strong> If you load demo activity, a simulation engine
              generates synthetic accounts, transactions, and holdings tied to your profile,
              purely so the dashboard and nudges have something to show.
            </li>
            <li>
              <strong>Operational data.</strong> Standard request metadata (timestamps, session
              identifiers) needed to keep you signed in and the API functioning.
            </li>
          </ul>

          <h2>3. How your data is used, including by AI models</h2>
          <p>
            Chat messages are sent to third-party large language model providers (OpenAI and
            Google) so Sarathi can generate a response. Before any message leaves our backend, it
            passes through a redaction step that strips patterns matching common personally
            identifiable information - PAN numbers, Aadhaar-shaped numbers, phone numbers, and
            similar - so far less of what reaches those providers is directly identifying. We do
            not use your data to train our own models, and we ask that you avoid pasting
            sensitive real-world information into chat in the first place, since it was never
            necessary for this demo.
          </p>

          <h2>4. Cookies and tracking</h2>
          <p>
            Sarathi sets a single httpOnly session cookie so you stay signed in between page
            loads. That&apos;s the extent of it - no advertising cookies, no third-party
            analytics trackers, no cross-site tracking pixels. The cookie exists purely to
            authenticate your requests and is cleared when you sign out.
          </p>

          <h2>5. Email communications</h2>
          <p>
            We send transactional email only: your one-time sign-in code, a welcome email when
            your account is created, and nudge notifications about your (synthetic) account
            activity, all via Amazon SES. We never send marketing email, and we never sell or
            share your email address with advertisers.
          </p>

          <h2>6. Data sharing</h2>
          <p>We share data with the following processors, strictly to run the product:</p>
          <ul>
            <li>
              <strong>OpenAI and Google</strong> - process chat text, after redaction, to
              generate responses.
            </li>
            <li>
              <strong>Amazon Web Services</strong> - hosts the application and database, and
              sends transactional email via SES.
            </li>
          </ul>
          <p>We do not sell your data, and we do not share it with data brokers or advertisers.</p>

          <h2>7. Retention and security</h2>
          <p>
            Data is retained for as long as your account exists. Sessions are httpOnly, rotated
            on refresh, and never exposed to client-side JavaScript. Passwords are never used, so
            there is nothing to leak there - only passkey public keys and hashed one-time codes
            are stored.
          </p>

          <h2>8. Your rights and deleting your data</h2>
          <p>
            You can remove passkeys and sign out at any time from your profile. To delete your
            account and all associated data, including chat history and synthetic demo data,
            email <a href="mailto:sarathi@niheshr.com">sarathi@niheshr.com</a> and we will action
            the request promptly.
          </p>

          <h2>9. Children&apos;s privacy</h2>
          <p>
            Sarathi is a technology demo and isn&apos;t directed at children. We don&apos;t
            knowingly collect data from anyone under 18.
          </p>

          <h2>10. Changes to this policy</h2>
          <p>
            As an actively developed prototype, this policy may change as features change. The
            &quot;last updated&quot; date at the top will always reflect the latest version.
          </p>

          <h2>11. Contact</h2>
          <p>
            Questions about your data or this policy: write to{" "}
            <a href="mailto:sarathi@niheshr.com">sarathi@niheshr.com</a>.
          </p>
        </div>
      </div>
    </div>
  )
}
