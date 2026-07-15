import type { AppConfig, Identity, PdfFile, RenderResult, Settings, SignRequest, SignResult } from './types'

const JSON_HEADERS = { 'Content-Type': 'application/json' }

async function jsonOrThrow(r: Response) {
  if (!r.ok) {
    let detail = r.statusText
    try {
      detail = (await r.json()).detail ?? detail
    } catch {
      /* keep statusText */
    }
    throw new Error(detail)
  }
  return r.json()
}

export const getSettings = (): Promise<Settings> => fetch('/api/settings').then(jsonOrThrow)

export const putSettings = (s: Settings): Promise<unknown> =>
  fetch('/api/settings', { method: 'PUT', headers: JSON_HEADERS, body: JSON.stringify(s) }).then(jsonOrThrow)

export const getIdentities = (): Promise<Identity[]> => fetch('/api/identities').then(jsonOrThrow)

export const getConfig = (): Promise<AppConfig> => fetch('/api/config').then(jsonOrThrow)

export const getFolder = (path: string): Promise<{ folder: string; files: PdfFile[] }> =>
  fetch(`/api/folder?path=${encodeURIComponent(path)}`).then(jsonOrThrow)

export const pickFolder = (): Promise<{ folder: string | null }> =>
  fetch('/api/pick-folder', { method: 'POST' }).then(jsonOrThrow)

export const pickFiles = (): Promise<{ folder: string | null; files: PdfFile[] }> =>
  fetch('/api/pick-files', { method: 'POST' }).then(jsonOrThrow)

export const getPage = (path: string, index: number): Promise<RenderResult> =>
  fetch(`/api/page?path=${encodeURIComponent(path)}&index=${index}&width=1000`).then(jsonOrThrow)

export const sign = (req: SignRequest): Promise<{ results: SignResult[] }> =>
  fetch('/api/sign', { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(req) }).then(jsonOrThrow)
