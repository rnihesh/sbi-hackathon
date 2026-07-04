/**
 * Vernacular chat languages - mirrors the backend's free-string vocabulary
 * (`app/agents/language.py`'s `SUPPORTED_LANGUAGES`). Kept as plain strings on
 * both sides so adding a language is a one-line change, no schema migration.
 */

export interface LanguageOption {
  /** `null` means "auto": Sarathi replies in whatever language the customer
   * writes in. Sent to the API as `preferred_language: null`. */
  value: string | null
  label: string
}

export const LANGUAGE_OPTIONS: LanguageOption[] = [
  { value: null, label: "Auto (match my language)" },
  { value: "english", label: "English" },
  { value: "hindi", label: "Hindi" },
  { value: "hinglish", label: "Hinglish" },
  { value: "telugu", label: "Telugu" },
  { value: "tamil", label: "Tamil" },
  { value: "kannada", label: "Kannada" },
  { value: "bengali", label: "Bengali" },
  { value: "marathi", label: "Marathi" },
]

export function languageLabel(value: string | null | undefined): string {
  const match = LANGUAGE_OPTIONS.find((option) => option.value === (value ?? null))
  return match?.label ?? "Auto (match my language)"
}

/** Native-script hint for "Ask Sarathi anything about your money", one per
 * non-English supported language (Hinglish stays Latin script, as written).
 * The chat composer rotates its placeholder through these when a customer has
 * set a language preference, so the vernacular support is visible at rest. */
export const CHAT_PLACEHOLDER_HINTS: Record<string, string> = {
  hindi: "सारथी से अपने पैसों के बारे में कुछ भी पूछें",
  hinglish: "Sarathi se apne paison ke baare mein kuch bhi poochho",
  telugu: "మీ డబ్బు గురించి సారథిని ఏదైనా అడగండి",
  tamil: "உங்கள் பணத்தைப் பற்றி சாரதியிடம் எதுவும் கேளுங்கள்",
  kannada: "ನಿಮ್ಮ ಹಣದ ಬಗ್ಗೆ ಸಾರಥಿಯನ್ನು ಏನಾದರೂ ಕೇಳಿ",
  bengali: "আপনার টাকা সম্পর্কে সারথীকে যা খুশি জিজ্ঞাসা করুন",
  marathi: "तुमच्या पैशांबद्दल सारथीला काहीही विचारा",
}
