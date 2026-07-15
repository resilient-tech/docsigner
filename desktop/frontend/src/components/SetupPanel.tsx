import { RefreshCw } from 'lucide-react'
import { type ReactNode } from 'react'
import type { AppearanceProfile, Identity } from '../types'
import { STANDARDS } from '../types'

export function SetupPanel(props: {
  identities: Identity[]
  identityId: string | null
  onIdentity: (id: string) => void
  onRefreshIdentities: () => void
  profiles: AppearanceProfile[]
  profileId: string | null
  profile: AppearanceProfile | null
  onProfile: (id: string) => void
  onEditProfiles: () => void
  preview: ReactNode
  boxAspect: string
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

  return (
    <aside className="setup">
      <div className="field">
        <label>Certificate</label>
        <div className="cert-row">
          <select className="control grow" value={props.identityId ?? ''} onChange={(e) => props.onIdentity(e.target.value)}>
            {props.identities.length === 0 && <option value="">No certificates found</option>}
            {props.identities.map((i) => (
              <option key={i.id} value={i.id}>
                {i.name} · {i.kind === 'token' ? 'token' : 'key'} · to {i.notAfter}
              </option>
            ))}
          </select>
          <button className="ic-btn" onClick={props.onRefreshIdentities} title="Refresh certificates from token" aria-label="Refresh certificates">
            <RefreshCw size={15} />
          </button>
        </div>
      </div>

      <div className="field">
        <label>Signature</label>
        {p && (
          <div className="sig-paper" style={{ aspectRatio: props.boxAspect }}>
            {props.preview}
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
        {std?.needsConfig && !props.trustConfigured && <span className="hint-warn">Needs a trust directory (OPENSIGNER_TRUST_DIR).</span>}
      </div>

      {std?.needsConfig && (
        <div className="field">
          <label>Timestamp authority</label>
          <input
            className="control"
            value={props.tsaUrl}
            placeholder={props.tsaDefault || 'RFC 3161 TSA URL'}
            onChange={(e) => props.onTsaUrl(e.target.value)}
          />
        </div>
      )}

      <div className="field">
        <label>Save as</label>
        <div className="control out-row">
          <span className="grow">Filename suffix</span>
          <input className="suffix-input" value={props.suffix} onChange={(e) => props.onSuffix(e.target.value)} />
        </div>
      </div>
    </aside>
  )
}
