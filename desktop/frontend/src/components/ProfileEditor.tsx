import { useRef, useState } from 'react'
import { GripVertical, Plus, Trash2, Upload, X } from 'lucide-react'
import type { AppearanceProfile, FontOption } from '../types'
import { StampPreview } from './StampPreview'

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
  fonts,
  onSelect,
  onChange,
  onReorder,
  onAdd,
  onDelete,
  onUploadFont,
  onDeleteFont,
  onClose,
}: {
  profiles: AppearanceProfile[]
  selectedId: string
  signerName: string
  fonts: FontOption[]
  onSelect: (id: string) => void
  onChange: (p: AppearanceProfile) => void
  onReorder: (profiles: AppearanceProfile[]) => void
  onAdd: () => void
  onDelete: (id: string) => void
  onUploadFont: (filename: string, data: string) => Promise<string>
  onDeleteFont: (slug: string) => Promise<void>
  onClose: () => void
}) {
  const profile = profiles.find((p) => p.id === selectedId) ?? profiles[0]
  const set = (patch: Partial<AppearanceProfile>) => onChange({ ...profile, ...patch })
  const [fontError, setFontError] = useState<string | null>(null)
  const selectedFont = fonts.find((f) => f.slug === profile.font)
  const [dragFrom, setDragFrom] = useState<number | null>(null)
  const [dragOver, setDragOver] = useState<number | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  // Live drag state. A ref, not state, because pointermove fires far faster
  // than React can re-render and the handler needs the current value.
  const drag = useRef<{ from: number; y: number; moved: boolean } | null>(null)
  // Set on the pointerup that ended a real drag, so the click it also fires
  // does not then select the row the user was only dragging.
  const dragged = useRef(false)

  /** Which row the pointer is over, by measuring the rows themselves. */
  function rowAt(clientY: number): number {
    const rows = listRef.current?.querySelectorAll('.prof') ?? []
    for (let i = 0; i < rows.length; i++) {
      if (clientY < rows[i].getBoundingClientRect().bottom) return i
    }
    return Math.max(0, rows.length - 1)
  }

  // Pointer events rather than HTML5 drag-and-drop. WebKitGTK — the Linux
  // window — never starts an in-page drag, so `draggable` + onDragStart simply
  // did nothing there while working on Windows and macOS. PlacementCanvas
  // already moves its box this way, and it behaves the same on all three.
  function startDrag(i: number, e: React.PointerEvent<HTMLButtonElement>) {
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { from: i, y: e.clientY, moved: false }
  }

  function moveDrag(e: React.PointerEvent<HTMLButtonElement>) {
    const d = drag.current
    if (!d) return
    // A few pixels of slack, so a click with a shaky hand still selects.
    if (!d.moved && Math.abs(e.clientY - d.y) < 4) return
    d.moved = true
    setDragFrom(d.from)
    setDragOver(rowAt(e.clientY))
  }

  function endDrag() {
    const d = drag.current
    drag.current = null
    dragged.current = !!d?.moved
    if (d?.moved && dragOver !== null && dragOver !== d.from) {
      const next = [...profiles]
      next.splice(dragOver, 0, ...next.splice(d.from, 1))
      onReorder(next)
    }
    setDragFrom(null)
    setDragOver(null)
  }

  function onPickImage(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => set({ image: String(reader.result) }) // data: URL, stored as-is
    reader.readAsDataURL(file)
  }

  // Upload through a file input rather than a native dialog: the webview gives
  // us one for free on every platform, and the base64 body matches how the
  // signature image above is already posted.
  function onPickFont(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = '' // so picking the same file twice still fires
    setFontError(null)
    const reader = new FileReader()
    reader.onload = () => {
      onUploadFont(file.name, String(reader.result))
        .then((slug) => set({ font: slug })) // select what was just added
        .catch((err) => setFontError(err instanceof Error ? err.message : String(err)))
    }
    reader.readAsDataURL(file)
  }

  function removeFont(slug: string) {
    onDeleteFont(slug)
      .then(() => set({ font: 'great-vibes' }))
      .catch((err) => setFontError(err instanceof Error ? err.message : String(err)))
  }

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
          <div className="prof-list" ref={listRef}>
            {profiles.map((p, i) => (
              <button
                key={p.id}
                className={[
                  'prof',
                  p.id === selectedId ? 'active' : '',
                  dragFrom === i ? 'dragging' : '',
                  dragOver === i && dragFrom !== null && dragFrom !== i ? (i > dragFrom ? 'drop-below' : 'drop-above') : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
                onClick={() => {
                  if (dragged.current) {
                    dragged.current = false
                    return
                  }
                  onSelect(p.id)
                }}
                onPointerDown={(e) => startDrag(i, e)}
                onPointerMove={moveDrag}
                onPointerUp={endDrag}
                onPointerCancel={endDrag}
              >
                <GripVertical size={13} className="prof-grip" aria-hidden />
                <span className="prof-name">{p.name}</span>
              </button>
            ))}
            <button className="btn ghost sm" onClick={onAdd}>
              <Plus size={13} /> New profile
            </button>
          </div>

          <div className="prof-editor">
            <div className="preview-label">Live preview</div>
            {/* Drawn at twice the old size: the detail lines were too small to read. */}
            <div className="sig-paper" style={{ aspectRatio: '440 / 120' }}>
              <StampPreview profile={profile} signerName={signerName} reason="Approved for filing" location="Ahmedabad" boxW={440} boxH={120} />
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
                  <option value="image">Image</option>
                </select>
              </label>
              {profile.style === 'handwritten' && (
                <label className="ef">
                  <span>Font</span>
                  <div className="img-row">
                    <select className="control" value={profile.font} onChange={(e) => set({ font: e.target.value })}>
                      {fonts.map((f) => (
                        <option key={f.slug} value={f.slug} style={{ fontFamily: `'${f.slug}', cursive` }}>
                          {f.label}
                        </option>
                      ))}
                    </select>
                    {/* Extensions only. The font/* MIME types made Windows fall
                        back to showing every file. */}
                    <label className="btn ghost sm" title="A handwriting font file — not a picture of your signature">
                      <Upload size={13} /> Add your font
                      <input type="file" accept=".ttf,.otf" onChange={onPickFont} hidden />
                    </label>
                    {/* A native <select> cannot carry a button per option, so the
                        delete sits outside it — labelled, so it is clear what it
                        deletes. */}
                    {selectedFont?.custom && (
                      <button
                        className="btn ghost sm danger"
                        onClick={() => removeFont(selectedFont.slug)}
                        title={`Delete "${selectedFont.label}" — removes the font itself, not just this profile's choice`}
                      >
                        <Trash2 size={13} /> Delete
                      </button>
                    )}
                  </div>
                  {fontError && <span className="field-error">{fontError}</span>}
                </label>
              )}
              {profile.style === 'image' && (
                <label className="ef">
                  <span>Image</span>
                  {/* A styled label over a hidden input, matching the font row. A
                      bare file input drew its own button and kept saying "No file
                      chosen" even with an image loaded. */}
                  <div className="img-row">
                    {profile.image && <img src={profile.image} alt="signature" className="img-thumb" />}
                    <label className="btn ghost sm" title="A picture of your signature (PNG or JPEG)">
                      <Upload size={13} /> Choose image
                      <input type="file" accept=".png,.jpg,.jpeg" onChange={onPickImage} hidden />
                    </label>
                    {profile.image && (
                      <button className="btn ghost sm danger" onClick={() => set({ image: null })} title="Remove this image from the profile">
                        <Trash2 size={13} /> Delete
                      </button>
                    )}
                  </div>
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
