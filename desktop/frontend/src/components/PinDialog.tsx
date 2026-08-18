import { useState } from 'react'
import { Eye, EyeOff, Lock } from 'lucide-react'

/** In-app token PIN prompt. The PIN goes to the local backend and on to the
    host, never off the machine. Shown only for token identities.

    A PIN is required here. Leaving it blank used to hand the job to the host's
    own PIN window — two boxes for one signature, and no way to guess that an
    empty field was what summoned the second one.

    Not shown at all for a token that collects the PIN itself — a pinpad reader,
    or a driver with its own dialog. App.tsx skips it on `protectedAuthPath`. */
export function PinDialog({
  signerName,
  onCancel,
  onSubmit,
}: {
  signerName: string
  onCancel: () => void
  onSubmit: (pin: string) => void
}) {
  const [pin, setPin] = useState('')
  const [reveal, setReveal] = useState(false)
  return (
    <div className="modal-overlay centred" onClick={onCancel}>
      <form
        className="pin-modal"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault()
          if (!pin) return // Enter with an empty field would submit past the button
          onSubmit(pin)
        }}
      >
        <div className="pin-lock">
          <Lock size={20} />
        </div>
        <div className="pin-title">Enter token PIN</div>
        <div className="pin-sub">{signerName}</div>
        {/* Our own reveal button, not the engine's: WebView2 draws one on Windows
            and WebKitGTK draws none, so without this Linux had no way to check a
            typo. The CSS hides the Windows one so only ours shows. */}
        <div className="pin-input-wrap">
          <input
            className="pin-field"
            type={reveal ? 'text' : 'password'}
            autoFocus
            value={pin}
            onChange={(e) => setPin(e.target.value)}
            placeholder="PIN"
          />
          <button
            type="button"
            className="pin-eye"
            onClick={() => setReveal((r) => !r)}
            aria-label={reveal ? 'Hide PIN' : 'Show PIN'}
            title={reveal ? 'Hide PIN' : 'Show PIN'}
            tabIndex={-1}
          >
            {reveal ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
        </div>
        <div className="pin-actions">
          <button type="button" className="btn ghost" onClick={onCancel}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={!pin}>
            Sign
          </button>
        </div>
        <div className="pin-note">One PIN signs every file.</div>
      </form>
    </div>
  )
}
