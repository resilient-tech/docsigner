import { useEffect, useMemo, useRef, useState } from 'react'
import { FolderOpen, FileText, CheckCircle2, AlertCircle, MinusCircle, X, RefreshCw, Sun, Moon, Signature } from 'lucide-react'
import * as api from './api'
import type { AppConfig, FontOption, Identity, PdfFile, Placement, RenderResult, Settings, SignResult, TokenHint } from './types'
import { PlacementCanvas } from './components/PlacementCanvas'
import { SetupPanel } from './components/SetupPanel'
import { ProfileEditor } from './components/ProfileEditor'
import { PinDialog } from './components/PinDialog'
import { StampPreview, fontFaceCss } from './components/StampPreview'

const DEFAULT_PLACEMENT: Placement = { page: -1, fx: 0.68, fy: 0.86, fw: 0.29, fh: 0.1 }

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
  const [results, setResults] = useState<Record<string, SignResult>>({})
  const [editorOpen, setEditorOpen] = useState(false)
  const [pinOpen, setPinOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
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

  useEffect(() => {
    api.getSettings().then((s) => {
      setSettings(s)
      setFolderPath(s.last_folder ?? '')
      if (s.last_folder) loadFolder(s.last_folder)
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
      return
    }
    let live = true
    api
      .getPage(selected, pageForRender)
      .then((r) => live && setRender(r))
      .catch((e) => live && setError(String(e.message ?? e)))
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

  async function loadFolder(path: string) {
    setError(null)
    try {
      const res = await api.getFolder(path)
      applyFiles(res.folder, res.files)
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

  function loadIdentities() {
    api.getIdentities().then((r) => {
      setIdentities(r.identities)
      setTokenHint(r.tokenHint)
    })
  }

  function refreshIdentities() {
    loadIdentities()
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
      setResults((prev) => {
        const next: Record<string, SignResult> = {}
        for (const f of res.files) if (prev[f.path]) next[f.path] = prev[f.path]
        return next
      })
      setSelected((cur) => (cur && res.files.some((f) => f.path === cur) ? cur : (res.files[0]?.path ?? null)))
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function copyReport() {
    const failed = files.filter((f) => results[f.path] && !results[f.path].ok && !results[f.path].skipped)
    const lines = [
      'DocSigner Desktop — error report',
      `standard: ${settings?.standard}   certificate: ${signerName}${isToken ? ' (token)' : ' (key)'}`,
      ...(error ? [`error: ${error}`] : []),
      ...failed.map((f) => `- ${f.name}: ${results[f.path].error}`),
      ...(cfg?.logPath ? [`log: ${cfg.logPath}`] : []),
    ]
    try {
      await navigator.clipboard.writeText(lines.join('\n'))
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

  const isToken = identities.find((i) => i.id === settings?.identity_id)?.kind === 'token'

  function onSign() {
    if (isToken) setPinOpen(true)
    else void doSign()
  }

  async function doSign(pin?: string) {
    if (!settings || !currentProfile || !settings.identity_id || !filesToSign.length) return
    setPinOpen(false)
    setBusy(true)
    setError(null)
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

  const signedCount = Object.values(results).filter((r) => r.ok).length
  const skippedCount = Object.values(results).filter((r) => r.skipped).length
  const failedCount = Object.values(results).filter((r) => !r.ok && !r.skipped).length

  return (
    <div className="app">
      {/* Faces are served from signer-core's own files, and the list grows when
          the user uploads one, so the rules are built here rather than in a
          stylesheet that cannot know a new slug. */}
      <style>{fontFaceCss(fonts.map((f) => f.slug))}</style>
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">
            <Signature size={17} strokeWidth={2.25} />
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
        <input
          className="path-input"
          value={folderPath}
          placeholder="or paste a path…"
          onChange={(e) => setFolderPath(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && loadFolder(folderPath)}
        />
        <button
          className="ic-btn"
          onClick={refreshFolder}
          disabled={!folderPath}
          title="Rescan the folder"
          aria-label="Refresh files"
        >
          <RefreshCw size={15} />
        </button>
        <span className="count-pill">
          {files.length} PDF{files.length === 1 ? '' : 's'}
        </span>
      </div>

      {(error || failedCount > 0) && (
        <div className={`banner ${error ? 'error' : 'warn'}`}>
          <span className="banner-msg">
            {error ?? `${failedCount} file${failedCount === 1 ? '' : 's'} could not be signed — hover a file for the reason.`}
          </span>
          <button className="banner-btn" onClick={copyReport}>
            Copy details
          </button>
          {error && (
            <button className="banner-x" onClick={() => setError(null)} aria-label="Dismiss">
              ×
            </button>
          )}
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
                    <span className="qrow-name">{f.name}</span>
                    <span className="qrow-sub" title={r && !r.ok ? r.error : undefined}>
                      {r?.ok ? `→ ${r.name}` : r ? r.error : `${(f.size / 1024).toFixed(0)} KB`}
                    </span>
                  </span>
                  {r?.ok ? (
                    <CheckCircle2 size={15} className="s-ok" />
                  ) : r?.skipped ? (
                    <MinusCircle size={15} className="s-skip" />
                  ) : r ? (
                    <AlertCircle size={15} className="s-err" />
                  ) : null}
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
          {render && selected ? (
            <PlacementCanvas
              render={render}
              placement={placement}
              onChange={(p) => patch({ placement: p })}
              onPage={(index) => patch({ placement: { ...placement, page: index } })}
              preview={stamp}
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
          onRefreshIdentities={refreshIdentities}
          tokenHint={tokenHint}
          profiles={settings.profiles}
          profileId={settings.profile_id}
          profile={currentProfile}
          onProfile={(id) => patch({ profile_id: id })}
          onEditProfiles={() => setEditorOpen(true)}
          preview={stamp}
          boxAspect={`${boxW} / ${boxH}`}
          standard={settings.standard}
          onStandard={(v) => patch({ standard: v })}
          trustConfigured={cfg?.trustConfigured ?? false}
          tsaUrl={settings.tsa_url ?? ''}
          tsaDefault={cfg?.tsaUrl ?? ''}
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
