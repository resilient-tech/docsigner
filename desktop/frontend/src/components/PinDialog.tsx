import { useState } from 'react'
import { Eye, EyeOff, Lock } from 'lucide-react'

/** In-app token PIN prompt. Optional: enter the PIN here (it goes to the local
    backend and on to the host, never off the machine), or leave it blank and
    the host shows its own system PIN dialog. Shown only for token identities.

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
            placeholder="PIN (optional)"
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
          <button type="submit" className="btn primary">
            Sign
          </button>
        </div>
        <div className="pin-note">One PIN signs every file.</div>
      </form>
    </div>
  )
}
