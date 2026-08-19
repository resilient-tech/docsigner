import type { AppearanceProfile } from '../types'

// Font slugs double as CSS family names: fontFaceCss() registers each face
// under its own slug, so a font the user just uploaded needs no name mapping.

/** docsigner-core's face for the detail lines under the signature. */
const DETAIL_FONT = 'poppins'

/**
 * The date exactly as core stamps it: `%Y-%m-%d %H:%M %z`. This used to be a
 * hardcoded sample, so the preview showed a date that was never the one signed.
 */
export function stampTime(now = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0')
  const mins = -now.getTimezoneOffset() // JS reports west-positive; strftime east-positive
  const abs = Math.abs(mins)
  const offset = `${mins < 0 ? '-' : '+'}${p(Math.floor(abs / 60))}${p(abs % 60)}`
  return `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())} ${p(now.getHours())}:${p(now.getMinutes())} ${offset}`
}

/**
 * `@font-face` rules for the detail font plus every listed hand, served by the
 * backend from the very files docsigner-core stamps into the PDF. Injected as one
 * <style> element rather than a stylesheet, because the list grows when the user
 * uploads a font and a static stylesheet cannot know the new slug.
 */
export function fontFaceCss(slugs: string[]): string {
  return [DETAIL_FONT, ...slugs]
    .map((s) => `@font-face{font-family:'${s}';src:url('/font-file/${s}');font-display:swap}`)
    .join('\n')
}

/**
 * The signature exactly as it lands: navy ink, transparent background, laid out
 * and scaled to the real box. Drawn in an SVG whose viewBox is the box in PDF
 * points, so it fills any container (the on-page box, or a preview card) at the
 * true aspect ratio and the size tracks the box. Proportions mirror core's
 * composed stamp (name in the top half, detail lines below).
 */
export function StampPreview({
  profile,
  signerName,
  reason,
  location,
  boxW,
  boxH,
}: {
  profile: AppearanceProfile
  signerName: string
  reason?: string | null
  location?: string | null
  boxW: number
  boxH: number
}) {
  // Nothing is drawn for an invisible signature, so the preview says so rather
  // than showing a stamp that will not be there. Handled here, not at each call
  // site, so the sidebar card, the editor and the page all say the same thing.
  if (profile.style === 'none') {
    return <span className="stamp-none">No stamp</span>
  }

  const lines: string[] = []
  if (profile.show_name) lines.push(`Digitally signed by ${signerName}`)
  if (profile.show_date) lines.push(`Date: ${stampTime()}`)
  if (profile.show_reason && reason) lines.push(`Reason: ${reason}`)
  if (profile.show_location && location) lines.push(`Location: ${location}`)

  const pad = boxH * 0.07
  const svgStyle = { width: '100%', height: '100%', display: 'block', overflow: 'hidden' } as const
  const view = `0 0 ${boxW} ${boxH}`

  if (profile.style === 'text') {
    const n = Math.max(lines.length, 1)
    const lh = (boxH - 2 * pad) / n
    const fs = Math.min(lh * 0.72, boxH * 0.2)
    return (
      <svg viewBox={view} style={svgStyle} preserveAspectRatio="xMidYMid meet">
        {lines.map((l, i) => (
          <text key={i} x={pad} y={pad + lh * i + fs} fontFamily={`'${DETAIL_FONT}', sans-serif`} fontSize={fs} fill="#2a2f38">
            {l}
          </text>
        ))}
      </svg>
    )
  }

  // handwritten and image share the layout: the mark fills the top area, detail
  // lines sit below. Mirrors core's composed stamp.
  const hasLines = lines.length > 0
  const topH = hasLines ? boxH * 0.52 : boxH * 0.88
  const lh = hasLines ? Math.min(boxH * 0.16, (boxH - topH - pad) / lines.length) : 0
  const lineFS = lh * 0.76
  const detail = lines.map((l, i) => (
    <text key={i} x={pad} y={topH + pad * 0.3 + lh * i + lineFS} fontFamily={`'${DETAIL_FONT}', sans-serif`} fontSize={lineFS} fill="#5f636c">
      {l}
    </text>
  ))

  if (profile.style === 'image') {
    return (
      <svg viewBox={view} style={svgStyle} preserveAspectRatio="xMidYMid meet">
        {profile.image && (
          <image href={profile.image} x={pad} y={pad} width={boxW - 2 * pad} height={topH - pad} preserveAspectRatio="xMinYMid meet" />
        )}
        {detail}
      </svg>
    )
  }

  const nameFS = Math.min(topH * 0.9, (boxW - 2 * pad) / (0.46 * Math.max(signerName.length, 3)))
  return (
    <svg viewBox={view} style={svgStyle} preserveAspectRatio="xMidYMid meet">
      <text x={pad} y={pad + nameFS * 0.82} fontFamily={`'${profile.font}', cursive`} fontSize={nameFS} fill="#14315d">
        {signerName}
      </text>
      {detail}
    </svg>
  )
}
