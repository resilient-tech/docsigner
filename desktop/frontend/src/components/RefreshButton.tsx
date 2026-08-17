import { useState } from 'react'
import { RefreshCw } from 'lucide-react'

// A folder rescan can finish in a few milliseconds. Spinning for only that long
// is invisible, so the click reads as though nothing happened — which is the
// complaint this button exists to answer. Hold the spin long enough to be seen.
const MIN_SPIN_MS = 450

/** A refresh button that spins until its work is done. */
export function RefreshButton({
  onRefresh,
  title,
  label,
  disabled,
}: {
  onRefresh: () => Promise<unknown>
  title: string
  label: string
  disabled?: boolean
}) {
  const [busy, setBusy] = useState(false)

  async function run() {
    setBusy(true)
    try {
      await Promise.all([onRefresh(), new Promise((r) => setTimeout(r, MIN_SPIN_MS))])
    } catch {
      /* the handler reports its own failures; here the spin only has to stop */
    } finally {
      setBusy(false)
    }
  }

  return (
    <button
      className="ic-btn"
      // Disabled while busy: a second click cannot make the first one finish sooner.
      disabled={disabled || busy}
      onClick={() => void run()}
      title={title}
      aria-label={label}
      aria-busy={busy}
    >
      <RefreshCw size={15} className={busy ? 'spinning' : undefined} />
    </button>
  )
}
