export interface Placement {
  page: number // -1 = last page
  fx: number
  fy: number
  fw: number
  fh: number
}

export interface AppearanceProfile {
  id: string
  name: string
  style: 'handwritten' | 'text' | 'image'
  font: string
  image?: string | null // base64 / data: URL, used when style === 'image'
  show_name: boolean
  show_date: boolean
  show_reason: boolean
  show_location: boolean
}

export interface Settings {
  last_folder: string | null
  recent_folders: string[]
  identity_id: string | null
  profile_id: string | null
  standard: string
  suffix: string
  reason: string | null
  location: string | null
  placement: Placement | null
  theme: 'system' | 'light' | 'dark'
  tsa_url: string | null
  profiles: AppearanceProfile[]
}

/** A selectable handwriting face. The slug is both the stored value and the
 *  CSS family name; `custom` marks the ones the user uploaded and may remove. */
export interface FontOption {
  slug: string
  label: string
  custom: boolean
}

export interface Identity {
  id: string
  kind: 'token' | 'p12'
  name: string
  issuer: string
  notAfter: string
  selfSigned: boolean
  /** The token collects the PIN itself (pinpad, or a driver with its own
      dialog). We must not ask for one — see PinDialog. */
  protectedAuthPath?: boolean
}

/**
 * Why the certificate list is empty, when the reason is fixable.
 *
 * The host sees smart-card readers even with no vendor driver installed, so
 * "nothing plugged in" and "plugged in but unusable" stop looking identical.
 */
export interface TokenHint {
  token: string | null
  readers: string[]
  message: string
  action: string
}

export interface IdentitiesResult {
  identities: Identity[]
  tokenHint: TokenHint | null
}

export interface AppConfig {
  tsaUrl: string
  trustConfigured: boolean
  logPath: string
}

export interface PdfFile {
  path: string
  name: string
  size: number
}

export interface RenderResult {
  image: string
  widthPt: number
  heightPt: number
  pages: number
  page: number
}

export interface SignResult {
  path: string
  ok: boolean
  skipped?: boolean
  name?: string
  error?: string
}

export interface SignRequest {
  files: string[]
  identity_id: string
  profile: AppearanceProfile
  standard: string
  reason: string | null
  location: string | null
  suffix: string
  placement: Placement
  tsa_url?: string | null
  pin?: string | null
}

// All six of core's profiles (docsigner_core.profiles.Profile). The two archive
// ones were missing here, so they were unreachable from the app.
//
// needsConfig = wants trust anchors. needsTsa = wants a timestamp authority. They
// are not the same set: CCA-LTV needs anchors but no clock, and the timestamp box
// used to key off needsConfig, so it appeared for CCA-LTV and did nothing.
// Mirrors Profile.needs_timestamp in core/docsigner_core/profiles.py.
export const STANDARDS: { value: string; label: string; needsConfig?: boolean; needsTsa?: boolean }[] = [
  { value: 'B-B', label: 'PAdES B-B (basic)' },
  { value: 'B-T', label: 'PAdES B-T (+ timestamp)', needsConfig: true, needsTsa: true },
  { value: 'B-LT', label: 'PAdES B-LT (+ LTV)', needsConfig: true, needsTsa: true },
  { value: 'B-LTA', label: 'PAdES B-LTA (+ archive timestamp)', needsConfig: true, needsTsa: true },
  { value: 'CCA-LTV', label: 'CCA-LTV (India)', needsConfig: true },
  { value: 'CCA-LTA', label: 'CCA-LTA (India, + timestamp)', needsConfig: true, needsTsa: true },
]
