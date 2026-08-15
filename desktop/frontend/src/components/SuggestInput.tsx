import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ChevronDown, X } from 'lucide-react'

/**
 * A text box that also offers suggestions: type anything, or pick one.
 *
 * Not a native `<datalist>`. Its popup cannot be sized or styled, so long values
 * came out truncated, its arrow did not match the app's selects, and it would not
 * open on a click.
 */
export function SuggestInput({
  value,
  onChange,
  suggestions,
  placeholder,
  inputClassName = 'control',
  caretLabel = 'Suggestions',
  onPick,
  onEnter,
  onClear,
  clearLabel = 'Clear',
}: {
  value: string
  onChange: (v: string) => void
  suggestions: string[]
  placeholder?: string
  inputClassName?: string
  caretLabel?: string
  /** Picking one commits it. Defaults to onChange. */
  onPick?: (v: string) => void
  onEnter?: (v: string) => void
  onClear?: () => void
  clearLabel?: string
}) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLSpanElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const menuRef = useRef<HTMLUListElement>(null)

  // Narrow as you type. An exact match is dropped: offering what is already in
  // the box is noise, and it is how the menu gets out of the way.
  const typed = value.trim().toLowerCase()
  const matches = suggestions.filter((s) => s.toLowerCase() !== typed && (!typed || s.toLowerCase().includes(typed)))

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onDown)
    return () => document.removeEventListener('pointerdown', onDown)
  }, [open])

  function focusOption(index: number) {
    const items = menuRef.current?.querySelectorAll('button')
    if (!items?.length) return
    items[(index + items.length) % items.length].focus()
  }

  function pick(v: string) {
    setOpen(false)
    ;(onPick ?? onChange)(v)
  }

  return (
    <span className="suggest" ref={wrapRef}>
      <input
        ref={inputRef}
        className={`${inputClassName} suggest-input`}
        value={value}
        placeholder={placeholder}
        // Click opens it even when empty. Not onFocus: Escape hands focus back
        // here, which would reopen what you just closed.
        onClick={() => setOpen(true)}
        onChange={(e) => {
          onChange(e.target.value)
          setOpen(true)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onEnter?.(value)
          if (e.key === 'Escape') setOpen(false)
          if (e.key === 'ArrowDown') {
            e.preventDefault()
            setOpen(true)
            requestAnimationFrame(() => focusOption(0)) // a frame, so the list exists
          }
        }}
      />
      {matches.length > 0 && (
        <button
          className="suggest-caret"
          onClick={() => setOpen((o) => !o)}
          title={caretLabel}
          aria-label={caretLabel}
          aria-expanded={open}
        >
          <ChevronDown size={14} />
        </button>
      )}
      {onClear && value && (
        <button className="suggest-clear" onClick={onClear} title={clearLabel} aria-label={clearLabel}>
          <X size={13} />
        </button>
      )}
      {open && matches.length > 0 && (
        <ul
          className="suggest-menu"
          role="listbox"
          ref={menuRef}
          onKeyDown={(e) => {
            const items = Array.from(menuRef.current?.querySelectorAll('button') ?? [])
            const at = items.indexOf(document.activeElement as HTMLButtonElement)
            if (e.key === 'ArrowDown') {
              e.preventDefault()
              focusOption(at + 1)
            } else if (e.key === 'ArrowUp') {
              e.preventDefault()
              // Up from the first goes back to the box, not round to the end.
              at <= 0 ? inputRef.current?.focus() : focusOption(at - 1)
            } else if (e.key === 'Escape') {
              setOpen(false)
              inputRef.current?.focus()
            }
          }}
        >
          {matches.map((s) => (
            <li key={s}>
              <button role="option" aria-selected={s === value} onClick={() => pick(s)} title={s}>
                {s as ReactNode}
              </button>
            </li>
          ))}
        </ul>
      )}
    </span>
  )
}
