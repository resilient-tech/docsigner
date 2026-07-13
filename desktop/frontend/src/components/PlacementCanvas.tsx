import { useRef, useState, type PointerEvent, type ReactNode } from 'react'
import { ChevronLeft, ChevronRight, Minus, Plus } from 'lucide-react'
import type { Placement, RenderResult } from '../types'

const BASE_W = 660 // page width at 100%; zoom scales it, the box stays fractional

const MIN_W = 0.05
const MIN_H = 0.03
type Handle = 'move' | 'nw' | 'ne' | 'sw' | 'se'

const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v))
const round = (v: number) => Math.round(v * 1000) / 1000

/**
 * A rendered PDF page with the signature box overlaid. Drag the box to move it,
 * drag a corner to resize. Everything is in page fractions, so the box maps
 * straight to CSS percentages and stays correct at any zoom or page size.
 */
export function PlacementCanvas({
  render,
  placement,
  onChange,
  onPage,
  preview,
}: {
  render: RenderResult
  placement: Placement
  onChange: (p: Placement) => void
  onPage: (index: number) => void
  preview: ReactNode
}) {
  const boxRef = useRef<HTMLDivElement>(null)
  const areaRef = useRef<HTMLDivElement>(null)
  const drag = useRef<{ mode: Handle; sx: number; sy: number; start: Placement; w: number; h: number } | null>(null)
  const [zoom, setZoom] = useState(1)

  function begin(mode: Handle, e: PointerEvent) {
    e.preventDefault()
    e.stopPropagation()
    const rect = areaRef.current!.getBoundingClientRect()
    drag.current = { mode, sx: e.clientX, sy: e.clientY, start: { ...placement }, w: rect.width, h: rect.height }
    boxRef.current?.setPointerCapture(e.pointerId)
  }

  function move(e: PointerEvent) {
    const d = drag.current
    if (!d) return
    const dx = (e.clientX - d.sx) / d.w
    const dy = (e.clientY - d.sy) / d.h
    let { fx, fy, fw, fh } = d.start
    if (d.mode === 'move') {
      fx = clamp(d.start.fx + dx, 0, 1 - fw)
      fy = clamp(d.start.fy + dy, 0, 1 - fh)
    } else {
      if (d.mode.includes('e')) fw = clamp(d.start.fw + dx, MIN_W, 1 - d.start.fx)
      if (d.mode.includes('s')) fh = clamp(d.start.fh + dy, MIN_H, 1 - d.start.fy)
      if (d.mode.includes('w')) {
        const nfx = clamp(d.start.fx + dx, 0, d.start.fx + d.start.fw - MIN_W)
        fw = d.start.fw + (d.start.fx - nfx)
        fx = nfx
      }
      if (d.mode.includes('n')) {
        const nfy = clamp(d.start.fy + dy, 0, d.start.fy + d.start.fh - MIN_H)
        fh = d.start.fh + (d.start.fy - nfy)
        fy = nfy
      }
    }
    onChange({ ...placement, fx: round(fx), fy: round(fy), fw: round(fw), fh: round(fh) })
  }

  function end(e: PointerEvent) {
    drag.current = null
    boxRef.current?.releasePointerCapture(e.pointerId)
  }

  const pageIndex = render.page
  const pct = (v: number) => `${v * 100}%`

  return (
    <div className="canvas">
      <div className="canvas-toolbar">
        <div className="pager">
          <button className="ic-btn" disabled={pageIndex <= 0} onClick={() => onPage(pageIndex - 1)} aria-label="Previous page">
            <ChevronLeft size={16} />
          </button>
          <span className="page-ind">
            {pageIndex + 1} / {render.pages}
          </span>
          <button className="ic-btn" disabled={pageIndex >= render.pages - 1} onClick={() => onPage(pageIndex + 1)} aria-label="Next page">
            <ChevronRight size={16} />
          </button>
        </div>
        <button
          className={`chip ${placement.page < 0 ? 'active' : ''}`}
          onClick={() => onPage(placement.page < 0 ? render.page : -1)}
          title={placement.page < 0 ? 'On the last page — click to pin this page' : 'Always sign the last page'}
        >
          Last page
        </button>
        <div className="zoom">
          <button className="ic-btn" onClick={() => setZoom((z) => Math.max(0.5, Math.round((z - 0.25) * 100) / 100))} aria-label="Zoom out">
            <Minus size={15} />
          </button>
          <button className="zoom-pct" onClick={() => setZoom(1)} title="Reset zoom">
            {Math.round(zoom * 100)}%
          </button>
          <button className="ic-btn" onClick={() => setZoom((z) => Math.min(3, Math.round((z + 0.25) * 100) / 100))} aria-label="Zoom in">
            <Plus size={15} />
          </button>
        </div>
      </div>

      <div className="canvas-scroll">
        <div className="page-area" ref={areaRef} style={{ width: Math.round(BASE_W * zoom) }}>
          <img src={render.image} className="page-img" draggable={false} alt="PDF page" />
          <div
            ref={boxRef}
            className="sig-box"
            style={{ left: pct(placement.fx), top: pct(placement.fy), width: pct(placement.fw), height: pct(placement.fh) }}
            onPointerDown={(e) => begin('move', e)}
            onPointerMove={move}
            onPointerUp={end}
            onPointerCancel={end}
          >
            <div className="sig-preview">{preview}</div>
            <span className="rh nw" onPointerDown={(e) => begin('nw', e)} />
            <span className="rh ne" onPointerDown={(e) => begin('ne', e)} />
            <span className="rh sw" onPointerDown={(e) => begin('sw', e)} />
            <span className="rh se" onPointerDown={(e) => begin('se', e)} />
          </div>
        </div>
      </div>
    </div>
  )
}
