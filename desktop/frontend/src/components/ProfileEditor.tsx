import { Plus, Trash2, X } from 'lucide-react'
import type { AppearanceProfile } from '../types'
import { StampPreview } from './StampPreview'

const FONTS = [
  'great-vibes',
  'dancing-script',
  'caveat',
  'sacramento',
  'allura',
  'alex-brush',
  'nanum-pen-script',
  'cedarville-cursive',
  'cookie',
  'bad-script',
]

const TOGGLES: { key: keyof AppearanceProfile; label: string }[] = [
  { key: 'show_name', label: 'Digitally signed by (name line)' },
  { key: 'show_date', label: 'Date & time' },
  { key: 'show_reason', label: 'Reason' },
  { key: 'show_location', label: 'Location' },
]

export function ProfileEditor({
  profiles,
  selectedId,
  signerName,
  onSelect,
  onChange,
  onAdd,
  onDelete,
  onClose,
}: {
  profiles: AppearanceProfile[]
  selectedId: string
  signerName: string
  onSelect: (id: string) => void
  onChange: (p: AppearanceProfile) => void
  onAdd: () => void
  onDelete: (id: string) => void
  onClose: () => void
}) {
  const profile = profiles.find((p) => p.id === selectedId) ?? profiles[0]
  const set = (patch: Partial<AppearanceProfile>) => onChange({ ...profile, ...patch })

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>Appearance profiles</h2>
          <button className="ic-btn" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>
        <div className="modal-body">
          <div className="prof-list">
            {profiles.map((p) => (
              <button key={p.id} className={`prof ${p.id === selectedId ? 'active' : ''}`} onClick={() => onSelect(p.id)}>
                {p.name}
              </button>
            ))}
            <button className="btn ghost sm" onClick={onAdd}>
              <Plus size={13} /> New profile
            </button>
          </div>

          <div className="prof-editor">
            <div className="preview-label">Live preview</div>
            <div className="sig-paper" style={{ aspectRatio: '220 / 60' }}>
              <StampPreview profile={profile} signerName={signerName} reason="Approved for filing" location="Ahmedabad" boxW={220} boxH={60} />
            </div>

            <div className="editor-fields">
              <label className="ef">
                <span>Name</span>
                <input className="control" value={profile.name} onChange={(e) => set({ name: e.target.value })} />
              </label>
              <label className="ef">
                <span>Style</span>
                <select className="control" value={profile.style} onChange={(e) => set({ style: e.target.value as AppearanceProfile['style'] })}>
                  <option value="handwritten">Handwritten</option>
                  <option value="text">Text</option>
                </select>
              </label>
              {profile.style === 'handwritten' && (
                <label className="ef">
                  <span>Font</span>
                  <select className="control" value={profile.font} onChange={(e) => set({ font: e.target.value })}>
                    {FONTS.map((f) => (
                      <option key={f} value={f}>
                        {f}
                      </option>
                    ))}
                  </select>
                </label>
              )}

              <div className="toggles">
                {TOGGLES.map((t) => (
                  <label key={t.key} className="tog">
                    <input
                      type="checkbox"
                      checked={Boolean(profile[t.key])}
                      onChange={(e) => set({ [t.key]: e.target.checked } as Partial<AppearanceProfile>)}
                    />
                    {t.label}
                  </label>
                ))}
              </div>

              <button className="btn ghost sm danger" disabled={profiles.length <= 1} onClick={() => onDelete(profile.id)}>
                <Trash2 size={13} /> Delete profile
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
