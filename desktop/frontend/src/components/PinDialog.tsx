import { useState } from 'react'
import { Lock } from 'lucide-react'

/** In-app token PIN prompt. Optional: enter the PIN here (it goes to the local
    backend and on to the host, never off the machine), or leave it blank and
    the host shows its own system PIN dialog. Shown only for token identities. */
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
  return (
    <div className="modal-overlay" onClick={onCancel}>
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
        <input
          className="pin-field"
          type="password"
          autoFocus
          value={pin}
          onChange={(e) => setPin(e.target.value)}
          placeholder="PIN (optional)"
        />
        <div className="pin-actions">
          <button type="button" className="btn ghost" onClick={onCancel}>
            Cancel
          </button>
          <button type="submit" className="btn primary">
            Sign
          </button>
        </div>
        <div className="pin-note">Leave blank to use the system prompt. One PIN signs the whole batch.</div>
      </form>
    </div>
  )
}
