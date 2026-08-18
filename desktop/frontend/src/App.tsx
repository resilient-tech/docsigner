import { useEffect, useMemo, useRef, useState } from 'react'
import { FolderOpen, FileText, CheckCircle2, AlertCircle, MinusCircle, X, Sun, Moon, Signature } from 'lucide-react'
import * as api from './api'
import type { AppConfig, FontOption, Identity, PdfFile, Placement, RenderResult, Settings, SignResult, TokenHint } from './types'
import { PlacementCanvas } from './components/PlacementCanvas'
import { SetupPanel } from './components/SetupPanel'
import { ProfileEditor } from './components/ProfileEditor'
import { PinDialog } from './components/PinDialog'
import { RefreshButton } from './components/RefreshButton'
import { StampPreview, fontFaceCss, stampTime } from './components/StampPreview'
import { SuggestInput } from './components/SuggestInput'

const DEFAULT_PLACEMENT: Placement = { page: -1, fx: 0.68, fy: 0.86, fw: 0.29, fh: 0.1 }

// Whole-window scale. The layout is in px, so growing the font alone would leave
// the panels and buttons behind — only a zoom takes everything with it.
const ZOOM_MIN = 0.8
const ZOOM_MAX = 2
const ZOOM_STEP = 0.1
const clampZoom = (z: number) => Math.round(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z)) * 10) / 10

/** Backend messages start lowercase ("no token is present"). Shown to a person,
 *  they should start like a sentence. */
const sentence = (s?: string | null): string | undefined =>
  s ? s.charAt(0).toUpperCase() + s.slice(1) : undefined

export function App() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [identities, setIdentities] = useState<Identity[]>([])
  const [tokenHint, setTokenHint] = useState<TokenHint | null>(null)
  const [cfg, setCfg] = useState<AppConfig | null>(null)
  const [fonts, setFonts] = useState<FontOption[]>([])
  const [folderPath, setFolderPath] = useState('')
  const [files, setFiles] = useState<PdfFile[]>([])
  const [included, setIncluded] = useState<Set<string>>(new Set())
  const [selected, setSelected] = useState<string | null>(null)
  const [render, setRender] = useState<RenderResult | null>(null)
  const [renderError, setRenderError] = useState<string | null>(null)
  const [results, setResults] = useState<Record<string, SignResult>>({})
  const [editorOpen, setEditorOpen] = useState(false)
  const [pinOpen, setPinOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [warnHidden, setWarnHidden] = useState(false)
  const persistReady = useRef(false)

  const [systemDark, setSystemDark] = useState(() => matchMedia('(prefers-color-scheme: dark)').matches)
  useEffect(() => {
    const mq = matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => setSystemDark(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  // "system" follows the OS; a toggle pins light/dark. Theme rides Settings so it
  // restores on next launch (localStorage isn't reliable across webview rebuilds).
  const resolvedTheme = settings?.theme === 'system' || !settings ? (systemDark ? 'dark' : 'light') : settings.theme
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', resolvedTheme)
  }, [resolvedTheme])

  // On the root element: every engine treats a zoom there as the whole page, and
  // the height:100% chain still fills the window because the containing block is
  // divided by the same factor. A transform would not reflow.
  const zoom = settings?.zoom ?? 1
  useEffect(() => {
    document.documentElement.style.zoom = String(zoom)
  }, [zoom])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Cmd on macOS, Ctrl on Windows and Linux. Nothing is OS-gated: whichever
      // the person pressed is the one they meant.
      if (!(e.ctrlKey || e.metaKey) || e.altKey) return
      // '=' is the unshifted key on most layouts; '+' comes from Shift and the
      // numpad. Both mean zoom in, as they do in a browser or an editor.
      const step = ['+', '='].includes(e.key) ? ZOOM_STEP : ['-', '_'].includes(e.key) ? -ZOOM_STEP : e.key === '0' ? 0 : null
      if (step === null) return
      e.preventDefault()
      setSettings((s) => (s ? { ...s, zoom: step === 0 ? 1 : clampZoom((s.zoom ?? 1) + step) } : s))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    api.getSettings().then(async (s) => {
      setSettings(s)
      // Opened with files beats reopening last time's folder.
      const opened = await api.getOpened().catch(() => ({ folder: null, files: [], ignored: [] }))
      if (opened.files.length) {
        applyFiles(opened.folder ?? 'Selected files', opened.files)
        return
      }
      setFolderPath(s.last_folder ?? '')
      if (s.last_folder) await loadFolder(s.last_folder)
      // "Open with" can be pointed at any file type. Say so, rather than opening
      // on the last folder as though nothing had been asked for. After the load,
      // which clears the banner.
      if (opened.ignored?.length) {
        setError(`DocSigner only opens PDFs. Ignored: ${opened.ignored.join(', ')}`)
      }
    })
    loadIdentities()
    api.getConfig().then(setCfg)
    api.getFonts().then(setFonts)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (settings && !settings.identity_id && identities.length) patch({ identity_id: identities[0].id })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identities, settings])

  useEffect(() => {
    if (!settings) return
    if (!persistReady.current) {
      persistReady.current = true
      return
    }
    const t = setTimeout(() => void api.putSettings(settings), 400)
    return () => clearTimeout(t)
  }, [settings])

  const placement = settings?.placement ?? DEFAULT_PLACEMENT
  const pageForRender = placement.page

  useEffect(() => {
    if (!selected) {
      setRender(null)
      setRenderError(null)
      return
    }
    let live = true
    api
      .getPage(selected, pageForRender)
      .then((r) => {
        if (!live) return
        setRender(r)
        setRenderError(null)
      })
      .catch((e) => {
        if (!live) return
        // Drop the page as well. The last file's preview left standing beside an
        // error reads as though this file had opened, which is worse than blank.
        setRender(null)
        setRenderError(String(e.message ?? e))
      })
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, pageForRender])

  function patch(p: Partial<Settings>) {
    setSettings((s) => (s ? { ...s, ...p } : s))
  }

  function applyFiles(folder: string, list: PdfFile[]) {
    setFiles(list)
    setFolderPath(folder)
    setResults({})
    setIncluded(new Set(list.map((f) => f.path)))
    setSelected(list[0]?.path ?? null)
    setSettings((cur) => (cur ? { ...cur, last_folder: folder } : cur))
  }

  // Most recent first, five kept. Feeds the path box's dropdown.
  function remember(folder: string) {
    setSettings((cur) =>
      cur ? { ...cur, recent_folders: [folder, ...(cur.recent_folders ?? []).filter((f) => f !== folder)].slice(0, 5) } : cur,
    )
  }

  async function loadFolder(path: string) {
    setError(null)
    try {
      const res = await api.getFolder(path)
      applyFiles(res.folder, res.files)
      remember(res.folder)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setFiles([])
      setSelected(null)
    }
  }

  async function chooseFolder() {
    const r = await api.pickFolder()
    if (r.folder) loadFolder(r.folder)
  }

  async function chooseFiles() {
    const r = await api.pickFiles()
    if (r.files.length) applyFiles(r.folder ?? 'Selected files', r.files)
  }

  function toggleInclude(path: string) {
    setIncluded((s) => {
      const n = new Set(s)
      n.has(path) ? n.delete(path) : n.add(path)
      return n
    })
  }

  function removeFile(path: string) {
    setFiles((fs) => fs.filter((f) => f.path !== path))
    setIncluded((s) => {
      const n = new Set(s)
      n.delete(path)
      return n
    })
    setResults((r) => {
      const next = { ...r }
      delete next[path]
      return next
    })
    if (selected === path) setSelected(files.find((f) => f.path !== path)?.path ?? null)
  }

  function clearFiles() {
    setFiles([])
    setIncluded(new Set())
    setResults({})
    setSelected(null)
    setFolderPath('') // full reset to the empty state, not a half-cleared toolbar
  }

  // Returns the promise: the refresh button spins until it settles.
  function loadIdentities() {
    return api
      .getIdentities()
      .then((r) => {
        setIdentities(r.identities)
        setTokenHint(r.tokenHint)
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }

  async function refreshFolder() {
    if (!folderPath) return
    try {
      const res = await api.getFolder(folderPath)
      const existing = new Set(files.map((f) => f.path))
      setFiles(res.files)
      // new files default to included; existing files keep their state.
      setIncluded((prev) => {
        const next = new Set<string>()
        for (const f of res.files) if (!existing.has(f.path) || prev.has(f.path)) next.add(f.path)
        return next
      })
      // Drop a "signed" mark whose output file has since been deleted, so the
      // original stops claiming a signed copy that is no longer there.
      const present = new Set(res.files.map((f) => f.name))
      setResults((prev) => {
        const next: Record<string, SignResult> = {}
        for (const f of res.files) {
          const r = prev[f.path]
          if (r && (!r.ok || (r.name && present.has(r.name)))) next[f.path] = r
        }
        return next
      })
      setSelected((cur) => (cur && res.files.some((f) => f.path === cur) ? cur : (res.files[0]?.path ?? null)))
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  // Pasted into a ticket or a chat, so it has to read on its own: when, what was
  // being attempted, what went wrong, and where to look next.
  async function copyReport() {
    const failed = files.filter((f) => results[f.path] && !results[f.path].ok && !results[f.path].skipped)
    const lines = [
      'DocSigner Desktop — error report',
      `Generated:        ${stampTime()}`,
      '',
      `Signing standard: ${settings?.standard}`,
      `Certificate:      ${signerName} (${isToken ? 'token' : 'key file'})`,
      ...(error ? ['', `Error: ${sentence(error)}`] : []),
      ...(failed.length
        ? [
            '',
            `Files that could not be signed (${failed.length} of ${filesToSign.length} selected):`,
            ...failed.map((f) => `  - ${f.name} — ${sentence(results[f.path].error)}`),
          ]
        : []),
      ...(cfg?.logPath ? ['', 'Full detail is in the log file:', `  ${cfg.logPath}`] : []),
    ]
    try {
      await navigator.clipboard.writeText(lines.join('\n'))
      setCopied(true)
      // Confirm first, then clear: once it is on the clipboard the banner has
      // done its job.
      setTimeout(() => {
        setCopied(false)
        setError(null)
        setWarnHidden(true)
      }, 1500)
    } catch {
      /* clipboard blocked; the log file still holds the detail */
    }
  }

  const allIncluded = files.length > 0 && files.every((f) => included.has(f.path))
  const toggleAll = () => setIncluded(allIncluded ? new Set() : new Set(files.map((f) => f.path)))

  const currentProfile = useMemo(
    () => settings?.profiles.find((p) => p.id === settings.profile_id) ?? settings?.profiles[0] ?? null,
    [settings],
  )
  const signerName = identities.find((i) => i.id === settings?.identity_id)?.name ?? 'Your Name'

  const filesToSign = files.filter((f) => included.has(f.path))

  const identity = identities.find((i) => i.id === settings?.identity_id)
  const isToken = identity?.kind === 'token'
  // Some tokens collect the PIN themselves — a pinpad reader, or a driver with
  // its own dialog. Asking here as well is two prompts for one signature, and
  // PKCS#11 says not to, so let the token do it.
  const tokenAsksForPin = isToken && identity?.protectedAuthPath === true

  function onSign() {
    if (isToken && !tokenAsksForPin) setPinOpen(true)
    else void doSign()
  }

  async function doSign(pin?: string) {
    if (!settings || !currentProfile || !settings.identity_id || !filesToSign.length) return
    setPinOpen(false)
    setBusy(true)
    setError(null)
    setWarnHidden(false) // a dismissed warning must not hide the next run's
    try {
      const { results: res } = await api.sign({
        files: filesToSign.map((f) => f.path),
        identity_id: settings.identity_id,
        profile: currentProfile,
        standard: settings.standard,
        reason: settings.reason,
        location: settings.location,
        suffix: settings.suffix,
        placement,
        tsa_url: settings.tsa_url,
        pin: pin ?? null,
      })
      setResults((cur) => {
        const map = { ...cur }
        res.forEach((r) => (map[r.path] = r))
        return map
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (!settings) return <div className="loading">Loading…</div>

  const pageW = render?.widthPt ?? 595
  const pageH = render?.heightPt ?? 842
  const boxW = pageW * placement.fw
  const boxH = pageH * placement.fh
  const stamp = currentProfile ? (
    <StampPreview profile={currentProfile} signerName={signerName} reason={settings.reason} location={settings.location} boxW={boxW} boxH={boxH} />
  ) : null

  const recent = settings.recent_folders ?? []
  const signedCount = Object.values(results).filter((r) => r.ok).length
  const skippedCount = Object.values(results).filter((r) => r.skipped).length
  const failedCount = Object.values(results).filter((r) => !r.ok && !r.skipped).length

  return (
    <div className="app">
      {/* Faces are served from docsigner-core's own files, and the list grows when
          the user uploads one, so the rules are built here rather than in a
          stylesheet that cannot know a new slug. */}
      <style>{fontFaceCss(fonts.map((f) => f.slug))}</style>
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">
            {/* base.css sizes it and sets the stroke weight. */}
            <Signature />
          </span>
          DocSigner
        </div>
        <div className="topbar-spacer" />
        <button
          className="ic-btn"
          onClick={() => patch({ theme: resolvedTheme === 'dark' ? 'light' : 'dark' })}
          title="Toggle light / dark"
          aria-label="Toggle theme"
        >
          {resolvedTheme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
        </button>
        <button
          className="btn primary sign-btn"
          disabled={busy || filesToSign.length === 0 || !settings.identity_id}
          onClick={onSign}
          title={isToken ? 'Signs with your token — one PIN for the batch' : undefined}
        >
          {busy ? 'Signing…' : `Sign ${filesToSign.length} PDF${filesToSign.length === 1 ? '' : 's'}`}
        </button>
      </header>

      <div className="toolbar">
        <button className="btn default sm" onClick={chooseFolder}>
          <FolderOpen size={15} /> Choose folder
        </button>
        <button className="btn ghost sm" onClick={chooseFiles}>
          Files…
        </button>
        <SuggestInput
          value={folderPath}
          onChange={setFolderPath}
          suggestions={recent}
          placeholder="or paste a path…"
          inputClassName="path-input"
          caretLabel="Recent folders"
          onPick={loadFolder}
          onEnter={loadFolder}
          onClear={clearFiles}
          clearLabel="Clear the path"
        />
        <RefreshButton
          onRefresh={refreshFolder}
          disabled={!folderPath}
          title="Rescan the folder"
          label="Refresh files"
        />
      </div>

      {(error || (failedCount > 0 && !warnHidden)) && (
        <div className={`banner ${error ? 'error' : 'warn'}`}>
          <span className="banner-msg">
            {sentence(error) ?? `${failedCount} file${failedCount === 1 ? '' : 's'} could not be signed.`}
          </span>
          <button className="banner-btn" onClick={copyReport}>
            {copied ? 'Copied' : 'Copy details'}
          </button>
          <button
            className="banner-x"
            onClick={() => (error ? setError(null) : setWarnHidden(true))}
            aria-label="Dismiss"
          >
            <X size={15} />
          </button>
        </div>
      )}

      <div className="workspace">
        <section className="queue">
          <div className="queue-head">
            <label className="q-all">
              <input type="checkbox" checked={allIncluded} onChange={toggleAll} disabled={!files.length} />
              <span>
                {included.size} of {files.length}
              </span>
            </label>
            <div className="queue-head-right">
              {(signedCount > 0 || skippedCount > 0 || failedCount > 0) && (
                <span className="queue-summary">
                  {[
                    signedCount && `${signedCount} signed`,
                    skippedCount && `${skippedCount} skipped`,
                    failedCount && `${failedCount} failed`,
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </span>
              )}
              {files.length > 0 && (
                <button className="q-clear" onClick={clearFiles} title="Remove all from the list">
                  Clear
                </button>
              )}
            </div>
          </div>
          <div className="queue-list">
            {files.length === 0 && <div className="empty">Choose a folder to begin.</div>}
            {files.map((f) => {
              const r = results[f.path]
              return (
                <div key={f.path} className={`qrow ${selected === f.path ? 'sel' : ''}`} onClick={() => setSelected(f.path)}>
                  <input
                    type="checkbox"
                    className="qrow-check"
                    checked={included.has(f.path)}
                    onChange={() => toggleInclude(f.path)}
                    onClick={(e) => e.stopPropagation()}
                  />
                  <FileText size={15} className="qrow-ic" />
                  <span className="qrow-main">
                    <span className="qrow-name" title={f.name}>
                      {f.name}
                    </span>
                    <span className="qrow-sub">
                      {r && !r.ok ? sentence(r.error) : `${(f.size / 1024).toFixed(0)} KB`}
                    </span>
                  </span>
                  {/* The reason hangs off the status icon, which is where people
                      point when a row has gone red. */}
                  {r && (
                    <span className="qrow-status" title={r.ok ? `Signed as ${r.name}` : sentence(r.error)}>
                      {r.ok ? (
                        <CheckCircle2 size={15} className="s-ok" />
                      ) : r.skipped ? (
                        <MinusCircle size={15} className="s-skip" />
                      ) : (
                        <AlertCircle size={15} className="s-err" />
                      )}
                    </span>
                  )}
                  <button
                    className="qrow-remove"
                    onClick={(e) => {
                      e.stopPropagation()
                      removeFile(f.path)
                    }}
                    aria-label={`Remove ${f.name}`}
                    title="Remove from list"
                  >
                    <X size={14} />
                  </button>
                </div>
              )
            })}
          </div>
        </section>

        <section className="stage">
          {/* The message belongs here rather than in the banner at the top: it is
              about the selected file, so it should go when another is picked. */}
          {renderError ? (
            <div className="stage-empty failed">
              <AlertCircle size={32} className="s-err" />
              <p>{sentence(renderError)}</p>
              <p className="stage-sub">Signing it will fail for the same reason.</p>
            </div>
          ) : render && selected ? (
            <PlacementCanvas
              render={render}
              placement={placement}
              onChange={(p) => patch({ placement: p })}
              onPage={(index) => patch({ placement: { ...placement, page: index } })}
              preview={stamp}
              included={included.has(selected)}
              onInclude={() => toggleInclude(selected)}
              appliesTo={filesToSign.length}
            />
          ) : (
            <div className="stage-empty">
              <FolderOpen size={32} />
              <p>Choose a folder to place your signature.</p>
            </div>
          )}
        </section>

        <SetupPanel
          identities={identities}
          identityId={settings.identity_id}
          onIdentity={(id) => patch({ identity_id: id })}
          onRefreshIdentities={loadIdentities}
          tokenHint={tokenHint}
          profiles={settings.profiles}
          profileId={settings.profile_id}
          profile={currentProfile}
          onProfile={(id) => patch({ profile_id: id })}
          onEditProfiles={() => setEditorOpen(true)}
          signerName={signerName}
          standard={settings.standard}
          onStandard={(v) => patch({ standard: v })}
          trustConfigured={cfg?.trustConfigured ?? false}
          tsaUrl={settings.tsa_url ?? ''}
          onTsaUrl={(v) => patch({ tsa_url: v || null })}
          reason={settings.reason ?? ''}
          location={settings.location ?? ''}
          onReason={(v) => patch({ reason: v })}
          onLocation={(v) => patch({ location: v })}
          suffix={settings.suffix}
          onSuffix={(v) => patch({ suffix: v })}
        />
      </div>

      {editorOpen && currentProfile && (
        <ProfileEditor
          profiles={settings.profiles}
          selectedId={currentProfile.id}
          signerName={signerName}
          fonts={fonts}
          onUploadFont={(filename, data) => api.addFont(filename, data).then((r) => (setFonts(r.fonts), r.slug))}
          onDeleteFont={(slug) => api.deleteFont(slug).then((r) => setFonts(r.fonts))}
          onSelect={(id) => patch({ profile_id: id })}
          onChange={(p) => patch({ profiles: settings.profiles.map((x) => (x.id === p.id ? p : x)) })}
          onReorder={(profiles) => patch({ profiles })}
          onAdd={() => {
            const id = `profile-${Date.now()}`
            patch({
              profiles: [
                ...settings.profiles,
                { id, name: 'New profile', style: 'handwritten', font: 'great-vibes', show_name: true, show_date: true, show_reason: false, show_location: false },
              ],
              profile_id: id,
            })
          }}
          onDelete={(id) => {
            const rest = settings.profiles.filter((p) => p.id !== id)
            patch({ profiles: rest, profile_id: rest[0]?.id })
          }}
          onClose={() => setEditorOpen(false)}
        />
      )}

      {pinOpen && (
        <PinDialog signerName={signerName} onCancel={() => setPinOpen(false)} onSubmit={(pin) => void doSign(pin || undefined)} />
      )}
    </div>
  )
}
