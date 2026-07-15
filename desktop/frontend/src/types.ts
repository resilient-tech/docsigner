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
  identity_id: string | null
  profile_id: string | null
  standard: string
  suffix: string
  reason: string | null
  location: string | null
  placement: Placement | null
  apply_to_all: boolean
  profiles: AppearanceProfile[]
}

export interface Identity {
  id: string
  kind: 'token' | 'p12'
  name: string
  issuer: string
  notAfter: string
  selfSigned: boolean
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
  output?: string
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
  pin?: string | null
}

export const STANDARDS: { value: string; label: string; needsConfig?: boolean }[] = [
  { value: 'B-B', label: 'PAdES B-B (basic)' },
  { value: 'B-T', label: 'PAdES B-T (+ timestamp)', needsConfig: true },
  { value: 'B-LT', label: 'PAdES B-LT (+ LTV)', needsConfig: true },
  { value: 'CCA-LTV', label: 'CCA-LTV (India)', needsConfig: true },
]
