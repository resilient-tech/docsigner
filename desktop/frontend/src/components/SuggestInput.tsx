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
  const [showAll, setShowAll] = useState(false)
  // Set when the keyboard asked for the list, cleared once focus has landed.
  const [reachFor, setReachFor] = useState(false)
  const wrapRef = useRef<HTMLSpanElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const menuRef = useRef<HTMLUListElement>(null)

  // Narrow as you type, but keep an exact match in the list. Dropping it hid the
  // caret whenever the box already held a known value — which is most of the
  // time, so nobody could tell the field had options at all.
  const typed = value.trim().toLowerCase()
  const matches = suggestions.filter((s) => !typed || s.toLowerCase().includes(typed))
  // The caret shows everything, typing narrows. Anything else and the caret is a
  // button that reveals only what you already typed.
  const list = showAll ? suggestions : matches

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onDown)
    return () => document.removeEventListener('pointerdown', onDown)
  }, [open])

  // An effect, not requestAnimationFrame. The frame fired before React had put
  // the <ul> in the DOM, so menuRef was still empty and focusOption returned
  // having done nothing: the list opened and then the arrow keys did nothing at
  // all. An effect runs after the commit, so the options are always there.
  useEffect(() => {
    if (!reachFor || !open) return
    focusOption(0)
    setReachFor(false)
  }, [reachFor, open, list.length])

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
        // Click opens it even when empty, showing everything: clicking the box to
        // look is the same intent as clicking the caret. Not onFocus, because
        // Escape hands focus back here and would reopen what you just closed.
        onClick={() => {
          setShowAll(true)
          setOpen(true)
        }}
        onChange={(e) => {
          onChange(e.target.value)
          setShowAll(false)
          // Typing a complete value closes the list, so it stops covering things
          // once there is nothing left to choose.
          setOpen(!suggestions.some((s) => s.toLowerCase() === e.target.value.trim().toLowerCase()))
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onEnter?.(value)
          if (e.key === 'Escape') setOpen(false)
          if (e.key === 'ArrowDown') {
            e.preventDefault()
            setShowAll(true)
            setOpen(true)
            setReachFor(true)
          }
        }}
      />
      {/* Keyed off the whole list, not the filtered one: the caret is what tells
          anyone the field has options, so it must not come and go. */}
      {suggestions.length > 0 && (
        <button
          className="suggest-caret"
          onClick={() => {
            setShowAll(true)
            setOpen((o) => !o)
          }}
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
      {open && list.length > 0 && (
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
          {list.map((s) => (
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
