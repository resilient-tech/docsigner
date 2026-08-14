import { useState } from 'react'
import { RefreshCw, UsbIcon } from 'lucide-react'
import type { AppearanceProfile, Identity, TokenHint } from '../types'
import { STANDARDS } from '../types'
import { StampPreview } from './StampPreview'

/** An empty value sends nothing and lets the backend choose: DOCSIGNER_TSA_URL if
 *  it is set, DigiCert otherwise. So "Default" is not a synonym for DigiCert, and
 *  the label below names whatever it actually resolved to. */
//
// Only servers checked against this signer. Sectigo's public endpoint was listed
// here and removed: it serves its own code-signing customers and answers
// pyHanko's request with "Error in communication with timestamp server". A preset
// that does not work is worse than no preset, because the list implies it does.
const TSA_PRESETS = [
  { url: '', label: 'Default' },
  { url: 'http://timestamp.digicert.com', label: 'DigiCert' },
  { url: 'http://timestamp.identrust.com', label: 'IdenTrust' },
]
const CUSTOM = '__custom__'

/** `http://timestamp.digicert.com` -> `timestamp.digicert.com` */
const host = (url: string) => url.replace(/^https?:\/\//, '').replace(/\/$/, '')

// The card is a fixed shape, so the preview shows what the signature *contains*
// rather than jumping about as the box is resized on the canvas.
const CARD_W = 220
const CARD_H = 60

/**
 * The certificate's expiry as `4 June 2027`.
 *
 * Not the OS short-date format: Windows' "14-Aug-26" is a Control Panel setting
 * the webview never sees, so toLocaleDateString() only ever returned the
 * webview's own locale (8/9/2036) and looked wrong. Day-month-year with the month
 * spelled out cannot be misread in any locale, and the month name still
 * translates.
 */
function localDate(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return `${d.getDate()} ${d.toLocaleDateString(undefined, { month: 'long' })} ${d.getFullYear()}`
}

export function SetupPanel(props: {
  identities: Identity[]
  identityId: string | null
  onIdentity: (id: string) => void
  onRefreshIdentities: () => void
  tokenHint: TokenHint | null
  profiles: AppearanceProfile[]
  profileId: string | null
  profile: AppearanceProfile | null
  onProfile: (id: string) => void
  onEditProfiles: () => void
  signerName: string
  standard: string
  onStandard: (v: string) => void
  trustConfigured: boolean
  tsaUrl: string
  tsaDefault: string
  onTsaUrl: (v: string) => void
  reason: string
  location: string
  onReason: (v: string) => void
  onLocation: (v: string) => void
  suffix: string
  onSuffix: (v: string) => void
}) {
  const p = props.profile
  const std = STANDARDS.find((s) => s.value === props.standard)
  // A saved address that is not one of the presets means the user typed it.
  const [customTsa, setCustomTsa] = useState(
    props.tsaUrl !== '' && !TSA_PRESETS.some((t) => t.url === props.tsaUrl),
  )

  return (
    <aside className="setup">
      <div className="field">
        <label>Certificate</label>
        <div className="cert-row">
          <select className="control grow" value={props.identityId ?? ''} onChange={(e) => props.onIdentity(e.target.value)}>
            {props.identities.length === 0 && <option value="">No certificates found</option>}
            {props.identities.map((i) => (
              <option key={i.id} value={i.id}>
                {i.name} · {i.kind === 'token' ? 'Token' : 'Key'} · Valid till {localDate(i.notAfter)}
              </option>
            ))}
          </select>
          <button className="ic-btn" onClick={props.onRefreshIdentities} title="Refresh certificates from token" aria-label="Refresh certificates">
            <RefreshCw size={15} />
          </button>
        </div>
        {/*
          The single most common reason signing does not work on a fresh
          machine. Without this the menu just says "No certificates found",
          which reads as "your token is broken" rather than "install the
          driver". The host can tell the difference, so say which.
        */}
        {props.tokenHint && (
          <div className="token-hint" role="status">
            <UsbIcon size={15} aria-hidden />
            <div>
              <strong>{props.tokenHint.message}</strong>
              <p>{props.tokenHint.action}</p>
              {props.tokenHint.readers.length > 0 && (
                <p className="token-hint-detail">
                  Detected: {props.tokenHint.readers.join(', ')}
                </p>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="field">
        <label>Signature</label>
        {p && (
          <div className="sig-paper" style={{ aspectRatio: `${CARD_W} / ${CARD_H}` }}>
            <StampPreview
              profile={p}
              signerName={props.signerName}
              reason={props.reason}
              location={props.location}
              boxW={CARD_W}
              boxH={CARD_H}
            />
          </div>
        )}
        <div className="profile-row">
          <select className="control grow" value={props.profileId ?? ''} onChange={(e) => props.onProfile(e.target.value)}>
            {props.profiles.map((pr) => (
              <option key={pr.id} value={pr.id}>
                {pr.name}
              </option>
            ))}
          </select>
          <button className="btn ghost sm" onClick={props.onEditProfiles}>
            Edit
          </button>
        </div>
      </div>

      {(p?.show_reason || p?.show_location) && (
        <div className="field">
          {p?.show_reason && (
            <input className="control" placeholder="Reason (e.g. Approved for filing)" value={props.reason} onChange={(e) => props.onReason(e.target.value)} />
          )}
          {p?.show_location && (
            <input className="control" placeholder="Location (e.g. Ahmedabad)" value={props.location} onChange={(e) => props.onLocation(e.target.value)} />
          )}
        </div>
      )}

      <div className="field">
        <label>Standard</label>
        <select className="control" value={props.standard} onChange={(e) => props.onStandard(e.target.value)}>
          {STANDARDS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        {std?.needsConfig && !props.trustConfigured && <span className="hint-warn">Needs a trust directory (DOCSIGNER_TRUST_DIR).</span>}
      </div>

      {/* Only the standards that actually use a timestamp. A list, not a bare box:
          nobody knows these addresses by heart, and a typo only surfaces as a
          network error once signing has already started. */}
      {std?.needsTsa && (
        <div className="field">
          <label>Timestamp authority</label>
          <select
            className="control"
            value={customTsa ? CUSTOM : props.tsaUrl}
            onChange={(e) => {
              if (e.target.value === CUSTOM) {
                setCustomTsa(true)
                return
              }
              setCustomTsa(false)
              props.onTsaUrl(e.target.value)
            }}
          >
            {TSA_PRESETS.map((t) => (
              <option key={t.url || 'default'} value={t.url}>
                {t.url === '' && props.tsaDefault ? `Default (${host(props.tsaDefault)})` : t.label}
              </option>
            ))}
            <option value={CUSTOM}>Custom…</option>
          </select>
          {customTsa && (
            <input
              className="control"
              value={props.tsaUrl}
              placeholder="http://timestamp.example.com"
              onChange={(e) => props.onTsaUrl(e.target.value)}
            />
          )}
        </div>
      )}

      <div className="field">
        <label>Save as</label>
        <div className="control out-row">
          <span className="out-label">Filename suffix</span>
          <input
            className="suffix-input"
            value={props.suffix}
            title={props.suffix}
            onChange={(e) => props.onSuffix(e.target.value)}
          />
        </div>
      </div>
    </aside>
  )
}
