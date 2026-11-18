import { useEffect, useMemo, useRef, useState } from 'react'

function archiveDetailsUrl(identifier) {
  return identifier ? `https://archive.org/details/${identifier}` : null
}

function linkifyText(text) {
  const urlRegex = /(https?:\/\/[^\s]+)/g
  const parts = text.split(urlRegex)
  return parts.map((part, i) => {
    if (!urlRegex.test(part)) return part
    // L3: Validate URL before rendering as a link — guard against javascript:/data: schemes.
    try {
      const parsed = new URL(part)
      if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return part
    } catch {
      return part
    }
    return <a key={i} href={part} target="_blank" rel="noreferrer">{part}</a>
  })
}

function isIntString(s) {
  if (s === null || s === undefined) return false
  const t = String(s).trim()
  return /^-?\d+$/.test(t)
}

// ---------------------------------------------------------------------------
// AdminPanel
// ---------------------------------------------------------------------------

function describeSync(st) {
  if (!st) return ''
  if (st.state === 'running') {
    if (st.phase === 'titles') return st.total ? `Looking up film titles on archive.org… ${st.done} of ${st.total}` : 'Looking up film titles on archive.org…'
    if (st.phase === 'descriptions' && st.total) return `Fetching film descriptions… ${st.done} of ${st.total}`
    return st.done ? `Fetching film list from the Internet Archive… ${st.done} found` : 'Fetching film list from the Internet Archive…'
  }
  if (st.state === 'done' && st.kind === 'titles') return `Title lookup finished ${new Date(st.finished_at * 1000).toLocaleString()} — ${st.synced} titles found.`
  if (st.state === 'done') return `Last sync finished ${new Date(st.finished_at * 1000).toLocaleString()} — ${st.synced} films.`
  if (st.state === 'error') return `Last ${st.kind === 'titles' ? 'title lookup' : 'sync'} failed: ${st.error}`
  return ''
}

// onDataChanged: called after a sync finishes or the DB is emptied, so the
// rating view can reload.
function AdminPanel({ apiJson, onDataChanged }) {
  const [tab, setTab] = useState('actions')

  // Sync state (status comes from the server, so it survives a page reload)
  const [syncStatus, setSyncStatus] = useState(null)   // { state, phase, done, total, synced, error, film_count, ... }
  const [syncMsg, setSyncMsg] = useState('')
  const prevSyncState = useRef(null)

  // Spreadsheet (CSV) import state
  const [impFile, setImpFile] = useState('')          // file name, for display
  const [impCsv, setImpCsv] = useState('')            // CSV text
  const [impPreview, setImpPreview] = useState(null)  // { headers, row_count, sample_rows, collection }
  const [impMap, setImpMap] = useState({ link: null, title: null, description: null, extra: [] })
  const [impPlan, setImpPlan] = useState(null)        // dry-run result
  const [impOnExisting, setImpOnExisting] = useState('')  // '' | 'skip' | 'update' — admin must choose if any exist
  const [impLookup, setImpLookup] = useState(true)
  const [impBusy, setImpBusy] = useState(false)
  const [impMsg, setImpMsg] = useState('')
  const [impResult, setImpResult] = useState(null)

  // Empty-database state
  const [emptyOpen, setEmptyOpen] = useState(false)
  const [emptyConfirmText, setEmptyConfirmText] = useState('')
  const [emptying, setEmptying] = useState(false)
  const [emptyMsg, setEmptyMsg] = useState('')

  // Criteria state
  const [criteria, setCriteria] = useState(null)
  const [criteriaLoading, setCriteriaLoading] = useState(false)
  const [criteriaError, setCriteriaError] = useState('')
  const [editingCriterion, setEditingCriterion] = useState(null)   // { id?, key, label, min_score, max_score, sort_order, active }
  const [criteriaMsg, setCriteriaMsg] = useState('')

  // Backup/restore state
  const [backupStatus, setBackupStatus] = useState('')
  const [restoreStatus, setRestoreStatus] = useState('')
  const [restorePending, setRestorePending] = useState(null)  // parsed JSON waiting for confirm
  const [restoring, setRestoring] = useState(false)

  // DB browser state
  const [tables, setTables] = useState(null)   // { tableName: rowCount }
  const [selTable, setSelTable] = useState('')
  const [rows, setRows] = useState(null)
  const [orderBy, setOrderBy] = useState('')
  const [limit, setLimit] = useState('100')
  const [dbError, setDbError] = useState('')
  const [dbLoading, setDbLoading] = useState(false)

  // Users state
  const [users, setUsers] = useState(null)
  const [usersLoading, setUsersLoading] = useState(false)
  const [usersError, setUsersError] = useState('')
  const [actionMsg, setActionMsg] = useState('')

  async function loadTables() {
    setDbLoading(true)
    setDbError('')
    const { ok, data } = await apiJson('/api/admin/db/tables')
    setDbLoading(false)
    if (ok) setTables(data)
    else setDbError(data?.error || 'Failed to load tables')
  }

  async function loadRows(table, opts = {}) {
    const t = table || selTable
    if (!t) return
    setDbLoading(true)
    setDbError('')
    setRows(null)
    const params = new URLSearchParams()
    const o = opts.orderBy !== undefined ? opts.orderBy : orderBy
    const l = opts.limit   !== undefined ? opts.limit   : limit
    if (o) params.set('order_by', o)
    if (l) params.set('limit',    l)
    const { ok, data } = await apiJson(`/api/admin/db/${t}?${params}`)
    setDbLoading(false)
    if (ok) setRows(data)
    else setDbError(data?.error || 'Failed to load rows')
  }

  async function loadUsers() {
    setUsersLoading(true)
    setUsersError('')
    setActionMsg('')
    const { ok, data } = await apiJson('/api/admin/db/users?order_by=id')
    setUsersLoading(false)
    if (ok) setUsers(data)
    else setUsersError(data?.error || 'Failed to load users')
  }

  async function setAdmin(userId, makeAdmin) {
    setActionMsg('')
    const action = makeAdmin ? 'make-admin' : 'revoke-admin'
    const { ok, data } = await apiJson(`/api/admin/users/${userId}/${action}`, { method: 'POST' })
    if (ok) {
      setActionMsg(`User ${userId} ${makeAdmin ? 'promoted to' : 'removed from'} admin.`)
      loadUsers()
    } else {
      setActionMsg(data?.error || 'Action failed')
    }
  }

  async function loadCriteriaAdmin() {
    setCriteriaLoading(true)
    setCriteriaError('')
    const { ok, data } = await apiJson('/api/admin/criteria')
    setCriteriaLoading(false)
    if (ok) setCriteria(data)
    else setCriteriaError(data?.error || 'Failed to load criteria')
  }

  function blankCriterion() {
    return { key: '', label: '', min_score: 1, max_score: 5, sort_order: 0, active: true }
  }

  async function saveCriterion() {
    if (!editingCriterion) return
    setCriteriaMsg('')
    const isNew = !editingCriterion.id
    const path = isNew ? '/api/admin/criteria' : `/api/admin/criteria/${editingCriterion.id}`
    const method = isNew ? 'POST' : 'PUT'
    const body = {
      key:        editingCriterion.key,
      label:      editingCriterion.label,
      min_score:  Number(editingCriterion.min_score),
      max_score:  Number(editingCriterion.max_score),
      sort_order: Number(editingCriterion.sort_order),
      active:     editingCriterion.active,
    }
    const { ok, data } = await apiJson(path, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (ok) {
      setCriteriaMsg(isNew ? 'Criterion created.' : 'Criterion updated.')
      setEditingCriterion(null)
      loadCriteriaAdmin()
    } else {
      setCriteriaMsg(`Error: ${data?.error || 'Save failed'}`)
    }
  }

  async function downloadBackup() {
    setBackupStatus('Preparing backup…')
    try {
      const res = await fetch('/api/admin/db/backup', { credentials: 'include' })
      if (!res.ok) {
        const d = await res.json().catch(() => ({}))
        setBackupStatus(`Error: ${d.error || res.statusText}`)
        return
      }
      const blob = await res.blob()
      const disposition = res.headers.get('Content-Disposition') || ''
      const match = disposition.match(/filename="([^"]+)"/)
      const filename = match ? match[1] : 'ia_ratings_backup.json'
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = filename; a.click()
      URL.revokeObjectURL(url)
      setBackupStatus(`Downloaded ${filename}`)
    } catch (e) {
      setBackupStatus(`Error: ${e.message}`)
    }
  }

  function handleRestoreFile(e) {
    setRestoreStatus('')
    setRestorePending(null)
    const file = e.target.files[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => {
      try {
        const parsed = JSON.parse(ev.target.result)
        if (parsed.app !== 'ia_ratings') {
          setRestoreStatus('Error: not an ia_ratings backup file')
          return
        }
        setRestorePending(parsed)
        setRestoreStatus('')
      } catch {
        setRestoreStatus('Error: could not parse JSON')
      }
    }
    reader.readAsText(file)
    e.target.value = ''  // reset so same file can be re-selected
  }

  async function confirmRestore() {
    if (!restorePending) return
    setRestoring(true)
    setRestoreStatus('Restoring…')
    const { ok, data } = await apiJson('/api/admin/db/restore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(restorePending),
    })
    setRestoring(false)
    setRestorePending(null)
    if (ok) {
      const counts = Object.entries(data.restored || {}).map(([t, n]) => `${t}: ${n}`).join(', ')
      setRestoreStatus(`Restored from ${data.exported_at} — ${counts}`)
      // Invalidate cached DB browser data
      setTables(null); setRows(null); setUsers(null)
    } else {
      setRestoreStatus(`Error: ${data?.error || 'Restore failed'}`)
    }
  }

  function resetImport() {
    setImpFile(''); setImpCsv(''); setImpPreview(null); setImpPlan(null)
    setImpMap({ link: null, title: null, description: null, extra: [] })
    setImpOnExisting('')
  }

  function handleImportFile(e) {
    const file = e.target.files[0]
    e.target.value = ''   // allow re-selecting the same file
    if (!file) return
    setImpMsg(''); setImpResult(null); resetImport()
    const reader = new FileReader()
    reader.onload = async (ev) => {
      const text = String(ev.target.result || '')
      const { ok, data } = await apiJson('/api/admin/import/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ csv_text: text }),
      })
      if (!ok) { setImpMsg(`Error: ${data?.error || 'Could not read that file'}`); return }
      setImpFile(file.name)
      setImpCsv(text)
      setImpPreview(data)
      setImpMap({ ...data.suggested_mapping, extra: [] })
    }
    reader.onerror = () => setImpMsg('Error: could not read that file')
    reader.readAsText(file)
  }

  function importBody(extra = {}) {
    return JSON.stringify({ csv_text: impCsv, mapping: impMap, ...extra })
  }

  async function runImport() {
    setImpBusy(true); setImpMsg('')
    const { ok, data } = await apiJson('/api/admin/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: importBody({ on_existing: impOnExisting || 'skip', lookup_titles: impLookup }),
    })
    setImpBusy(false)
    if (!ok) { setImpMsg(`Error: ${data?.error || 'Import failed'}`); return }
    setImpResult({ result: data.result, skipped: data.skipped, file: impFile })
    resetImport()
    setTables(null); setRows(null)
    await loadSyncStatus()   // starts progress polling if a title lookup was started
    onDataChanged()
  }

  async function loadSyncStatus() {
    const { ok, data } = await apiJson('/api/admin/sync/status')
    if (ok) setSyncStatus(data)
  }

  async function startSync() {
    setSyncMsg('')
    setEmptyMsg('')
    const { ok, status, data } = await apiJson('/api/admin/sync', { method: 'POST' })
    if (ok || status === 409) {
      setSyncStatus(data.status)   // 409 = already running; just show its progress
    } else {
      setSyncMsg(`Error: ${data?.error || 'Could not start sync'}`)
    }
  }

  async function emptyDatabase() {
    setEmptying(true)
    setEmptyMsg('')
    const { ok, data } = await apiJson('/api/admin/db/empty', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm: 'EMPTY' }),
    })
    setEmptying(false)
    if (ok) {
      const d = data.deleted || {}
      setEmptyMsg(`Emptied: ${d.films ?? 0} films and ${d.ratings ?? 0} ratings deleted.`)
      setEmptyOpen(false)
      setEmptyConfirmText('')
      setTables(null); setRows(null)   // invalidate cached DB browser data
      await loadSyncStatus()
      onDataChanged()
    } else {
      setEmptyMsg(`Error: ${data?.error || 'Could not empty the database'}`)
    }
  }

  // Re-check the import (dry run) whenever the file or the column mapping changes.
  useEffect(() => {
    if (!impCsv || impMap.link === null) { setImpPlan(null); return }
    let cancelled = false
    const t = setTimeout(async () => {
      const { ok, data } = await apiJson('/api/admin/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: importBody({ dry_run: true }),
      })
      if (cancelled) return
      if (ok) { setImpPlan(data); setImpMsg('') } else { setImpPlan(null); setImpMsg(`Error: ${data?.error || 'Could not check the import'}`) }
    }, 250)
    return () => { cancelled = true; clearTimeout(t) }
  }, [impCsv, impMap])

  // Load sync status once, then poll while a sync is running.
  useEffect(() => { loadSyncStatus() }, [])
  useEffect(() => {
    if (syncStatus?.state !== 'running') return
    const id = setInterval(loadSyncStatus, 1500)
    return () => clearInterval(id)
  }, [syncStatus?.state])
  // When a sync we were watching completes, refresh the rating view.
  useEffect(() => {
    const cur = syncStatus?.state
    if (prevSyncState.current === 'running' && cur && cur !== 'running') onDataChanged()
    prevSyncState.current = cur
  }, [syncStatus?.state])

  useEffect(() => {
    if (tab === 'db'       && tables   === null) loadTables()
    if (tab === 'users'    && users    === null) loadUsers()
    if (tab === 'criteria' && criteria === null) loadCriteriaAdmin()
  }, [tab])

  const tabStyle = (t) => ({
    padding: '6px 14px',
    cursor: 'pointer',
    border: '1px solid #ccc',
    borderBottom: tab === t ? '1px solid #fff' : '1px solid #ccc',
    background: tab === t ? '#fff' : '#f5f5f5',
    marginBottom: -1,
    fontWeight: tab === t ? 600 : 400,
    borderRadius: '6px 6px 0 0',
  })

  const cols = rows && rows.length > 0 ? Object.keys(rows[0]) : []

  return (
    <div style={{ marginTop: 12, border: '1px solid #ddd', borderRadius: 10, overflow: 'hidden' }}>
      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 4, padding: '10px 12px 0', background: '#f9f9f9', borderBottom: '1px solid #ddd' }}>
        <span style={{ fontWeight: 700, alignSelf: 'center', marginRight: 8 }}>Admin</span>
        {['actions', 'import', 'criteria', 'users', 'db', 'backup'].map(t => (
          <button key={t} style={tabStyle(t)} onClick={() => setTab(t)}>
            {{ actions: 'Actions', import: 'Import', criteria: 'Criteria', users: 'Users', db: 'DB Browser', backup: 'Backup' }[t]}
          </button>
        ))}
      </div>

      <div style={{ padding: 14 }}>

        {/* ── Actions ── */}
        {tab === 'actions' && (() => {
          const running = syncStatus?.state === 'running'
          const pct = running && syncStatus.phase === 'descriptions' && syncStatus.total
            ? Math.round((100 * syncStatus.done) / syncStatus.total) : null
          return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div style={{ fontSize: 14 }}>
                Films in database: <strong>{syncStatus ? syncStatus.film_count : '…'}</strong>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div>
                  <button onClick={startSync} disabled={running}>
                    {running ? (syncStatus.kind === 'titles' ? 'Busy (title lookup)…' : 'Syncing…') : 'Sync Collection'}
                  </button>
                </div>
                {running && (
                  <progress
                    style={{ width: 320 }}
                    {...(pct !== null ? { value: pct, max: 100 } : {})}
                    aria-label="Sync progress"
                  />
                )}
                {syncStatus && syncStatus.state !== 'idle' && (
                  <div
                    role="status"
                    style={{ fontSize: 13, color: syncStatus.state === 'error' ? '#a00' : running ? '#666' : '#060' }}
                  >
                    {describeSync(syncStatus)}
                  </div>
                )}
                {syncMsg && <div style={{ fontSize: 13, color: '#a00' }}>{syncMsg}</div>}
              </div>

              <div>
                <a href="/api/admin/ratings.csv" style={{ fontSize: 14 }}>⬇ Download ratings.csv</a>
              </div>

              <div style={{ borderTop: '1px solid #eee', paddingTop: 12 }}>
                <div style={{ fontWeight: 600, marginBottom: 6 }}>Danger zone</div>
                {!emptyOpen ? (
                  <button onClick={() => { setEmptyOpen(true); setEmptyMsg('') }} disabled={running} style={{ color: '#a00' }}>
                    Empty film database…
                  </button>
                ) : (
                  <div style={{ border: '1px solid #e0b4b4', background: '#fff6f6', borderRadius: 8, padding: 12, maxWidth: 520 }}>
                    <p style={{ margin: '0 0 8px', fontSize: 13 }}>
                      This permanently deletes <strong>all films and all ratings</strong>. User accounts and
                      criteria are kept. Download a backup first (Backup tab) if you might want the data back.
                      Raters will see "film database hasn't been set up" until you sync again.
                    </p>
                    <label style={{ fontSize: 13 }}>
                      Type <code>EMPTY</code> to confirm:{' '}
                      <input
                        value={emptyConfirmText}
                        onChange={e => setEmptyConfirmText(e.target.value)}
                        style={{ width: 90 }}
                        autoComplete="off"
                      />
                    </label>
                    <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                      <button
                        onClick={emptyDatabase}
                        disabled={emptyConfirmText !== 'EMPTY' || emptying || running}
                        style={{ color: '#a00' }}
                      >
                        {emptying ? 'Emptying…' : 'Empty database'}
                      </button>
                      <button onClick={() => { setEmptyOpen(false); setEmptyConfirmText('') }} disabled={emptying}>Cancel</button>
                    </div>
                  </div>
                )}
                {emptyMsg && (
                  <div style={{ marginTop: 8, fontSize: 13, color: emptyMsg.startsWith('Error') ? '#a00' : '#060' }}>{emptyMsg}</div>
                )}
              </div>
            </div>
          )
        })()}

        {/* ── Import from spreadsheet ── */}
        {tab === 'import' && (() => {
          const running = syncStatus?.state === 'running'
          const headers = impPreview?.headers || []
          const colLabel = (i) => `${i + 1}. ${(headers[i] || '(no header)').slice(0, 60)}`
          const setCol = (key) => (e) => setImpMap({ ...impMap, [key]: e.target.value === '' ? null : Number(e.target.value) })
          const toggleExtra = (i) => setImpMap({
            ...impMap,
            extra: impMap.extra.includes(i) ? impMap.extra.filter(x => x !== i) : [...impMap.extra, i],
          })
          const sum = impPlan?.summary
          const needChoice = sum && sum.existing > 0 && !impOnExisting
          const canImport = !!sum && sum.new + sum.existing > 0 && !needChoice && !impBusy && !running
          const select = (key, optional) => (
            <select value={impMap[key] ?? ''} onChange={setCol(key)}>
              <option value="">{optional ? '— none —' : '— choose a column —'}</option>
              {headers.map((_, i) => <option key={i} value={i}>{colLabel(i)}</option>)}
            </select>
          )
          return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14, maxWidth: 760 }}>
              <p style={{ margin: 0, fontSize: 13, color: '#555' }}>
                Add films from a spreadsheet exported as <strong>CSV</strong> instead of syncing from the Internet Archive.
                Only rows with an <strong>archive.org</strong> link are imported; other rows (YouTube links, free text, blanks) are skipped.
              </p>

              {running && <div role="status" style={{ fontSize: 13, color: '#666' }}>{describeSync(syncStatus)}</div>}

              <div>
                <input type="file" accept=".csv,text/csv" onChange={handleImportFile} disabled={impBusy} />
                {impFile && <span style={{ marginLeft: 8, fontSize: 13 }}>{impFile} — {impPreview.row_count} rows</span>}
              </div>
              {impMsg && <div style={{ fontSize: 13, color: impMsg.startsWith('Error') ? '#a00' : '#060' }}>{impMsg}</div>}

              {impPreview && (
                <>
                  <div style={{ border: '1px solid #ddd', borderRadius: 8, padding: 12 }}>
                    <div style={{ fontWeight: 600, marginBottom: 8 }}>Which column is which?</div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '8px 12px', alignItems: 'center', fontSize: 14 }}>
                      <label>Archive.org link <span style={{ color: '#a00' }}>*</span></label>{select('link', false)}
                      <label>Title</label>{select('title', true)}
                      <label>Description</label>{select('description', true)}
                    </div>
                    <div style={{ marginTop: 10, fontSize: 13 }}>
                      <div style={{ color: '#555', marginBottom: 4 }}>
                        Also keep these columns (admin-only, never shown to raters; leave empty to keep none):
                      </div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 14px' }}>
                        {headers.map((_, i) => (
                          i !== impMap.link && i !== impMap.title && i !== impMap.description && (
                            <label key={i} style={{ whiteSpace: 'nowrap' }}>
                              <input type="checkbox" checked={impMap.extra.includes(i)} onChange={() => toggleExtra(i)} /> {colLabel(i)}
                            </label>
                          )
                        ))}
                      </div>
                    </div>
                  </div>

                  <div style={{ overflowX: 'auto' }}>
                    <div style={{ fontSize: 13, color: '#555', marginBottom: 4 }}>First rows of your file:</div>
                    <table className="grid-table" style={{ tableLayout: 'auto', fontSize: 12 }}>
                      <thead><tr>{headers.map((h, i) => <th key={i}>{colLabel(i)}</th>)}</tr></thead>
                      <tbody>
                        {impPreview.sample_rows.map((r, ri) => (
                          <tr key={ri}>{r.map((c, ci) => (
                            <td key={ci} style={{ maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c}</td>
                          ))}</tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {sum && (
                    <div style={{ border: '1px solid #cfd8e3', background: '#f4f8fc', borderRadius: 8, padding: 12, fontSize: 14 }}>
                      <div>
                        Of <strong>{sum.rows}</strong> rows: <strong>{sum.new}</strong> new film{sum.new === 1 ? '' : 's'}
                        {sum.existing > 0 && <>, <strong>{sum.existing}</strong> already in the database</>}
                        , <strong>{sum.skipped}</strong> skipped.
                      </div>
                      <div style={{ fontSize: 12, color: '#555', marginTop: 2 }}>
                        Films are added to the collection <code>{impPlan.collection}</code>.
                      </div>

                      {impPlan.samples.length > 0 && (
                        <ul style={{ margin: '8px 0 0', paddingLeft: 18, fontSize: 13 }}>
                          {impPlan.samples.map(f => (
                            <li key={f.row}>
                              <strong>{f.title || <em>(title will be looked up)</em>}</strong> — {f.identifier}
                              {f.exists && <span style={{ color: '#a60' }}> (already exists)</span>}
                            </li>
                          ))}
                        </ul>
                      )}

                      {impPlan.skipped.length > 0 && (
                        <details style={{ marginTop: 8, fontSize: 13 }}>
                          <summary>{sum.skipped} skipped row{sum.skipped === 1 ? '' : 's'}</summary>
                          <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                            {impPlan.skipped.map(r => <li key={r.row}>Row {r.row}: {r.reason}</li>)}
                            {sum.skipped > impPlan.skipped.length && <li>…and {sum.skipped - impPlan.skipped.length} more</li>}
                          </ul>
                        </details>
                      )}

                      {sum.existing > 0 && (
                        <fieldset style={{ marginTop: 10, border: '1px solid #e0cfa8', background: '#fffaf0', borderRadius: 6 }}>
                          <legend style={{ fontSize: 13 }}>{sum.existing} film{sum.existing === 1 ? ' is' : 's are'} already in the database — what should happen to {sum.existing === 1 ? 'it' : 'them'}?</legend>
                          <label style={{ display: 'block', fontSize: 13 }}>
                            <input type="radio" name="on-existing" checked={impOnExisting === 'skip'} onChange={() => setImpOnExisting('skip')} />
                            {' '}Skip them (keep what is stored)
                          </label>
                          <label style={{ display: 'block', fontSize: 13 }}>
                            <input type="radio" name="on-existing" checked={impOnExisting === 'update'} onChange={() => setImpOnExisting('update')} />
                            {' '}Update them from the spreadsheet (blank cells never erase stored data)
                          </label>
                        </fieldset>
                      )}

                      <label style={{ display: 'block', marginTop: 10, fontSize: 13 }}>
                        <input type="checkbox" checked={impLookup} onChange={e => setImpLookup(e.target.checked)} />
                        {' '}Look up missing titles on archive.org (runs in the background; otherwise the identifier is used as the title)
                      </label>

                      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                        <button className="btn-primary" onClick={runImport} disabled={!canImport}>
                          {impBusy ? 'Importing…' : `Import ${sum.new + (impOnExisting === 'update' ? sum.existing : 0)} film${sum.new + (impOnExisting === 'update' ? sum.existing : 0) === 1 ? '' : 's'}`}
                        </button>
                        <button onClick={() => { resetImport(); setImpMsg('') }} disabled={impBusy}>Cancel</button>
                      </div>
                      {needChoice && <div style={{ fontSize: 12, color: '#a60', marginTop: 6 }}>Choose what to do with the existing films to continue.</div>}
                    </div>
                  )}
                </>
              )}

              {impResult && (
                <div role="status" style={{ border: '1px solid #b9d9b9', background: '#f3faf3', borderRadius: 8, padding: 12, fontSize: 14 }}>
                  Imported from <strong>{impResult.file}</strong>: {impResult.result.added} added
                  {impResult.result.updated > 0 && `, ${impResult.result.updated} updated`}
                  {impResult.result.skipped_existing > 0 && `, ${impResult.result.skipped_existing} existing left as they were`}
                  {`, ${impResult.result.skipped_invalid} skipped (no archive.org link).`}
                  {impResult.result.title_lookup_started && ' Looking up titles in the background — progress shows above and under Actions.'}
                </div>
              )}
            </div>
          )
        })()}

        {/* ── Criteria ── */}
        {tab === 'criteria' && (
          <div>
            {criteriaError && <div style={{ color: '#a00', marginBottom: 8 }}>{criteriaError}</div>}
            {criteriaMsg && (
              <div style={{ marginBottom: 8, fontSize: 13, color: criteriaMsg.startsWith('Error') ? '#a00' : '#060' }}>
                {criteriaMsg}
              </div>
            )}

            <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
              <button onClick={loadCriteriaAdmin} disabled={criteriaLoading} style={{ fontSize: 12 }}>
                {criteriaLoading ? 'Loading…' : '↻ Refresh'}
              </button>
              <button onClick={() => { setCriteriaMsg(''); setEditingCriterion(blankCriterion()) }}>
                + New criterion
              </button>
            </div>

            {/* Inline editor */}
            {editingCriterion && (
              <div style={{ marginBottom: 16, padding: 14, border: '1px solid #aac', borderRadius: 8, background: '#f5f8ff' }}>
                <div style={{ fontWeight: 600, marginBottom: 10 }}>
                  {editingCriterion.id ? `Edit criterion #${editingCriterion.id}` : 'New criterion'}
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: '8px 12px', alignItems: 'center', maxWidth: 480 }}>
                  <label style={{ fontSize: 13 }}>Key</label>
                  <input
                    value={editingCriterion.key}
                    onChange={e => setEditingCriterion({ ...editingCriterion, key: e.target.value })}
                    placeholder="snake_case identifier"
                    disabled={!!editingCriterion.id}
                    style={{ fontFamily: 'monospace', fontSize: 13 }}
                  />
                  <label style={{ fontSize: 13 }}>Label</label>
                  <input
                    value={editingCriterion.label}
                    onChange={e => setEditingCriterion({ ...editingCriterion, label: e.target.value })}
                    placeholder="Display name"
                  />
                  <label style={{ fontSize: 13 }}>Min score</label>
                  <input
                    type="number"
                    value={editingCriterion.min_score}
                    onChange={e => setEditingCriterion({ ...editingCriterion, min_score: e.target.value })}
                    style={{ width: 80 }}
                  />
                  <label style={{ fontSize: 13 }}>Max score</label>
                  <input
                    type="number"
                    value={editingCriterion.max_score}
                    onChange={e => setEditingCriterion({ ...editingCriterion, max_score: e.target.value })}
                    style={{ width: 80 }}
                  />
                  <label style={{ fontSize: 13 }}>Sort order</label>
                  <input
                    type="number"
                    value={editingCriterion.sort_order}
                    onChange={e => setEditingCriterion({ ...editingCriterion, sort_order: e.target.value })}
                    style={{ width: 80 }}
                  />
                  <label style={{ fontSize: 13 }}>Active</label>
                  <label style={{ fontSize: 13 }}>
                    <input
                      type="checkbox"
                      checked={!!editingCriterion.active}
                      onChange={e => setEditingCriterion({ ...editingCriterion, active: e.target.checked })}
                      style={{ marginRight: 6 }}
                    />
                    Shown to raters
                  </label>
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                  <button onClick={saveCriterion}>Save</button>
                  <button onClick={() => { setEditingCriterion(null); setCriteriaMsg('') }}>Cancel</button>
                </div>
              </div>
            )}

            {/* Criteria table */}
            {criteria && (
              criteria.length === 0
                ? <p style={{ color: '#666' }}>(no criteria)</p>
                : (
                  <table className="grid-table" style={{ tableLayout: 'auto', fontSize: 13 }}>
                    <thead>
                      <tr>
                        <th>id</th>
                        <th>key</th>
                        <th>label</th>
                        <th>range</th>
                        <th>sort</th>
                        <th>active</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {criteria.map(c => (
                        <tr key={c.id} style={{ opacity: c.active ? 1 : 0.5 }}>
                          <td>{c.id}</td>
                          <td style={{ fontFamily: 'monospace' }}>{c.key}</td>
                          <td>{c.label}</td>
                          <td>{c.min_score}–{c.max_score}</td>
                          <td>{c.sort_order}</td>
                          <td>{c.active ? '✓' : '—'}</td>
                          <td>
                            <button
                              style={{ fontSize: 12 }}
                              onClick={() => { setCriteriaMsg(''); setEditingCriterion({ ...c, active: !!c.active }) }}
                            >
                              Edit
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )
            )}
          </div>
        )}

        {/* ── DB Browser ── */}
        {tab === 'db' && (
          <div>
            {dbError && <div style={{ color: '#a00', marginBottom: 8 }}>{dbError}</div>}

            {/* Table list */}
            {tables && (
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
                {Object.entries(tables).map(([t, count]) => (
                  <button
                    key={t}
                    onClick={() => { setSelTable(t); setOrderBy(''); setLimit('100'); loadRows(t, { orderBy: '', limit: '100' }) }}
                    style={{ fontWeight: selTable === t ? 700 : 400, background: selTable === t ? '#e8f0fe' : '' }}
                  >
                    {t} <span style={{ fontSize: 12, color: '#666' }}>({count})</span>
                  </button>
                ))}
                <button onClick={loadTables} style={{ marginLeft: 4, fontSize: 12 }}>↻ Refresh</button>
              </div>
            )}

            {/* Filter bar */}
            {selTable && (
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10, alignItems: 'center' }}>
                <input
                  placeholder="ORDER BY column [ASC|DESC]"
                  value={orderBy}
                  onChange={e => setOrderBy(e.target.value)}
                  style={{ width: 220, fontFamily: 'monospace', fontSize: 13 }}
                />
                <input
                  placeholder="LIMIT"
                  value={limit}
                  onChange={e => setLimit(e.target.value)}
                  style={{ width: 70, fontFamily: 'monospace', fontSize: 13 }}
                />
                <button onClick={() => loadRows()} disabled={dbLoading}>
                  {dbLoading ? 'Loading…' : 'Run'}
                </button>
              </div>
            )}

            {/* Results table */}
            {rows && (
              rows.length === 0
                ? <p style={{ color: '#666' }}>(no rows)</p>
                : (
                  <div style={{ overflowX: 'auto' }}>
                    <table className="grid-table" style={{ tableLayout: 'auto', fontSize: 13 }}>
                      <thead>
                        <tr>{cols.map(c => <th key={c} style={{ whiteSpace: 'nowrap' }}>{c}</th>)}</tr>
                      </thead>
                      <tbody>
                        {rows.map((row, i) => (
                          <tr key={i}>
                            {cols.map(c => (
                              <td key={c} style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxWidth: 400 }}>
                                {row[c] === null ? <span style={{ color: '#aaa' }}>NULL</span> : String(row[c])}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div style={{ fontSize: 12, color: '#666', marginTop: 6 }}>{rows.length} row{rows.length !== 1 ? 's' : ''}</div>
                  </div>
                )
            )}

            {dbLoading && !rows && <p style={{ color: '#666' }}>Loading…</p>}
          </div>
        )}

        {/* ── Users ── */}
        {tab === 'users' && (
          <div>
            {actionMsg && <div style={{ marginBottom: 8, color: actionMsg.includes('failed') || actionMsg.includes('error') ? '#a00' : '#060', fontSize: 13 }}>{actionMsg}</div>}
            {usersError && <div style={{ color: '#a00', marginBottom: 8 }}>{usersError}</div>}
            <button onClick={loadUsers} disabled={usersLoading} style={{ marginBottom: 10, fontSize: 12 }}>
              {usersLoading ? 'Loading…' : '↻ Refresh'}
            </button>
            {users && (
              <div style={{ overflowX: 'auto' }}>
                <table className="grid-table" style={{ tableLayout: 'auto', fontSize: 13 }}>
                  <thead>
                    <tr>
                      <th>id</th>
                      <th>email</th>
                      <th>ia_username</th>
                      <th>github_username</th>
                      <th>is_admin</th>
                      <th>created_at</th>
                      <th>actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.map(u => (
                      <tr key={u.id}>
                        <td>{u.id}</td>
                        <td style={{ wordBreak: 'break-all' }}>{u.email}</td>
                        <td>{u.ia_username ?? <span style={{ color: '#aaa' }}>—</span>}</td>
                        <td>{u.github_username ?? <span style={{ color: '#aaa' }}>—</span>}</td>
                        <td>{u.is_admin ? '✓' : ''}</td>
                        <td style={{ whiteSpace: 'nowrap' }}>{u.created_at}</td>
                        <td style={{ whiteSpace: 'nowrap' }}>
                          {u.is_admin
                            ? <button onClick={() => setAdmin(u.id, false)} style={{ fontSize: 12 }}>Revoke admin</button>
                            : <button onClick={() => setAdmin(u.id, true)}  style={{ fontSize: 12 }}>Make admin</button>
                          }
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div style={{ fontSize: 12, color: '#666', marginTop: 6 }}>{users.length} user{users.length !== 1 ? 's' : ''}</div>
              </div>
            )}
          </div>
        )}

        {/* ── Backup / Restore ── */}
        {tab === 'backup' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

            {/* Download */}
            <div>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>Download backup</div>
              <p style={{ margin: '0 0 8px', fontSize: 13, color: '#555' }}>
                Exports all tables (users, films, ratings, criteria, etc.) as a single
                versioned JSON file. The filename includes the UTC timestamp.
              </p>
              <button onClick={downloadBackup}>⬇ Download backup</button>
              {backupStatus && (
                <div style={{ marginTop: 8, fontSize: 13, color: backupStatus.startsWith('Error') ? '#a00' : '#060' }}>
                  {backupStatus}
                </div>
              )}
            </div>

            <hr style={{ border: 0, borderTop: '1px solid #eee' }} />

            {/* Restore */}
            <div>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>Restore from backup</div>
              <p style={{ margin: '0 0 8px', fontSize: 13, color: '#555' }}>
                Select a <code>.json</code> backup file. You'll be asked to confirm before
                any data is overwritten.
              </p>
              <input type="file" accept=".json,application/json" onChange={handleRestoreFile} />

              {restorePending && (
                <div style={{ marginTop: 12, padding: 12, border: '1px solid #f0a030', borderRadius: 8, background: '#fffbf0' }}>
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>⚠ Confirm restore</div>
                  <div style={{ fontSize: 13, marginBottom: 8 }}>
                    <div>Exported: <strong>{restorePending.exported_at}</strong></div>
                    <div>Schema version: <strong>{restorePending.schema_version}</strong></div>
                    <div style={{ marginTop: 4 }}>
                      Tables:{' '}
                      {Object.entries(restorePending.tables || {}).map(([t, rows]) => (
                        <span key={t} style={{ marginRight: 8 }}>{t} ({rows.length})</span>
                      ))}
                    </div>
                  </div>
                  <p style={{ fontSize: 13, color: '#a00', margin: '0 0 10px' }}>
                    This will <strong>permanently replace</strong> all existing rows in every
                    table included in the backup. This cannot be undone.
                  </p>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button
                      onClick={confirmRestore}
                      disabled={restoring}
                      style={{ background: '#c00', color: '#fff', border: 'none', padding: '6px 14px', borderRadius: 4, cursor: 'pointer' }}
                    >
                      {restoring ? 'Restoring…' : 'Yes, restore now'}
                    </button>
                    <button onClick={() => { setRestorePending(null); setRestoreStatus('') }}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {restoreStatus && (
                <div style={{ marginTop: 8, fontSize: 13, color: restoreStatus.startsWith('Error') ? '#a00' : '#060' }}>
                  {restoreStatus}
                </div>
              )}
            </div>

          </div>
        )}

      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// OAuth sign-in helpers
// ---------------------------------------------------------------------------

// Server redirects to /?auth_error=<code>; map codes to messages here so the
// URL can never inject arbitrary text into the page.
const OAUTH_ERRORS = {
  github_denied: 'GitHub sign-in was cancelled.',
  github_state: 'GitHub sign-in expired or was invalid. Please try again.',
  github_failed: 'Could not sign in with GitHub. Please try again.',
}

// ---------------------------------------------------------------------------
// Main App
// ---------------------------------------------------------------------------

export default function App() {
  const [me, setMe] = useState(null)
  const [authScheme, setAuthScheme] = useState('ia') // default matches server default
  const [oauthProviders, setOauthProviders] = useState([]) // e.g. ['github']
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  const [film, setFilm] = useState(null)
  const [criteria, setCriteria] = useState([])
  const [scores, setScores] = useState({}) // key -> string (user input)

  // Shown instead of a film when there is nothing to rate (e.g. DB not synced yet).
  const [notice, setNotice] = useState(null) // { code, text }

  const [loading, setLoading] = useState(false)

  const [error, setError] = useState('')
  const [submitError, setSubmitError] = useState('')

  async function apiJson(path, opts = {}) {
    const res = await fetch(path, { credentials: 'include', ...opts })
    let data = null
    const ct = res.headers.get('content-type') || ''
    if (ct.includes('application/json')) {
      data = await res.json()
    } else {
      // best-effort text for error messages
      const t = await res.text().catch(() => '')
      data = t ? { message: t } : null
    }
    return { ok: res.ok, status: res.status, data }
  }

  async function loadMe() {
    const { ok, data } = await apiJson('/api/me')
    if (ok) setMe(data)
    else setMe(null)
  }

  async function login(isRegister) {
    setError('')
    const path = isRegister ? '/api/auth/register' : '/api/auth/login'
    const body = authScheme === 'ia'
      ? { username: email, password }
      : { email, password }
    const { ok, data } = await apiJson(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
    if (ok) {
      await loadMe()
    } else {
      setError(data?.error || 'Authentication failed')
    }
  }

  async function logout() {
    await apiJson('/api/auth/logout', { method: 'POST' })
    setMe(null)
    setFilm(null)
    setCriteria([])
    setScores({})
  }

  async function loadCriteria() {
    const { ok, data } = await apiJson('/api/criteria')
    if (ok) {
      const arr = Array.isArray(data) ? data : []
      arr.sort((a, b) => (a.sortOrder ?? 0) - (b.sortOrder ?? 0))
      setCriteria(arr)
    } else {
      setCriteria([])
    }
  }

  async function loadNextFilm() {
    setError('')
    setNotice(null)
    setSubmitError('')
    const { ok, data } = await apiJson('/api/films/next')
    if (ok) {
      setFilm(data)
      setScores({})
    } else {
      setFilm(null)
      if (data?.code === 'no_films' || data?.code === 'all_rated') {
        // Not errors: either nobody has synced the film list yet, or this user is done.
        setNotice({ code: data.code, text: data.error })
      } else {
        setError(data?.error || 'Could not load the next film')
      }
    }
  }

  async function submit() {
    if (!film?.identifier) return
    setSubmitError('')
    const payloadScores = {}
    for (const c of criteria) {
      const v = scores[c.key]
      payloadScores[c.key] = Number.parseInt(String(v), 10)
    }

    const { ok, data } = await apiJson(`/api/films/${film.identifier}/ratings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scores: payloadScores })
    })

    if (!ok) {
      setSubmitError(data?.error || 'Submit failed')
      return
    }

    // advance
    await loadNextFilm()
  }

  useEffect(() => {
    apiJson('/api/config').then(({ ok, data }) => {
      setAuthScheme(ok ? (data?.auth_scheme ?? 'ia') : 'ia')
      setOauthProviders(ok && Array.isArray(data?.oauth_providers) ? data.oauth_providers : [])
    })
    // The OAuth callback redirects back here as /?auth_error=<code> on failure.
    const params = new URLSearchParams(window.location.search)
    const authError = params.get('auth_error')
    if (authError) {
      setError(OAUTH_ERRORS[authError] || 'Sign-in failed')
      window.history.replaceState({}, '', window.location.pathname)
    }
    loadMe()
  }, [])

  useEffect(() => {
    if (me) {
      setLoading(true)
      Promise.all([loadCriteria(), loadNextFilm()]).finally(() => setLoading(false))
    }
  }, [me])

  const validation = useMemo(() => {
    const perKey = {}
    let allOk = !!film?.identifier && criteria.length > 0

    for (const c of criteria) {
      const raw = scores[c.key]
      const present = raw !== undefined && String(raw).trim() !== ''
      const isInt = present && isIntString(raw)
      const n = isInt ? Number.parseInt(String(raw), 10) : null
      const inRange = isInt && n >= c.min && n <= c.max
      const ok = present && inRange

      perKey[c.key] = {
        ok,
        hint: !present ? 'Required' : !isInt ? 'Must be an integer' : !inRange ? `Must be ${c.min}–${c.max}` : ''
      }
      if (!ok) allOk = false
    }

    return { allOk, perKey }
  }, [criteria, scores, film])

  const archiveUrl = archiveDetailsUrl(film?.identifier)

  if (!me) {
    const isIA = authScheme === 'ia'
    return (
      <div style={{ padding: 20, maxWidth: 520 }}>
        <h2>IA Film Rater</h2>
        <p style={{ marginTop: 0 }}>
          {isIA
            ? 'Log in with your archive.org account to start rating films.'
            : 'Login or create an account to start rating films.'}
        </p>

        {error ? <div style={{ margin: '12px 0', color: '#a00' }}>{error}</div> : null}

        <div style={{ display: 'grid', gap: 8 }}>
          <input
            placeholder={isIA ? 'archive.org username' : 'email'}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete={isIA ? 'username' : 'email'}
          />
          <input
            type="password"
            placeholder="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => login(false)}>Login</button>
            {!isIA && <button onClick={() => login(true)}>Register</button>}
          </div>
          {oauthProviders.includes('github') && (
            <>
              <div style={{ textAlign: 'center', color: '#888', fontSize: 13 }}>or</div>
              {/* Full-page navigation: the server redirects to GitHub and back. */}
              <button
                type="button"
                onClick={() => { window.location.href = '/api/auth/github/login' }}
              >
                Continue with GitHub
              </button>
            </>
          )}
        </div>
      </div>
    )
  }

  return (
    <div style={{ padding: 20, maxWidth: 980 }}>
      <style>{`
        .grid-table { width: 100%; border-collapse: collapse; table-layout: fixed; }
        .grid-table th { text-align: left; font-weight: 600; border-bottom: 2px solid #ddd; padding: 10px 8px; }
        .grid-table td { border-bottom: 1px solid #eee; padding: 10px 8px; vertical-align: middle; }
        .grid-table .col-crit { width: 40%; }
        .grid-table .col-range { width: 15%; }
        .grid-table .col-score { width: 20%; }
        .grid-table .col-quick { width: 25%; }
        .score-input { width: 5em; text-align: center; padding: 6px 8px; }
        .row-invalid { background: #fff5f5; }
        .hint { font-size: 12px; color: #a00; margin-top: 4px; }
        .quick { display: flex; flex-wrap: wrap; gap: 6px; }
        .quick button { padding: 4px 8px; }
        .btn-primary { padding: 10px 14px; }
        .btn-primary[disabled] { opacity: 0.5; cursor: not-allowed; }
        .topbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
        .film-description {
  margin: 12px 0;
  padding: 12px 14px;
  background: #fafafa;
  border: 1px solid #e5e5e5;
  border-radius: 8px;
  color: #333;
  white-space: pre-wrap;
}

.film-panel { margin-top: 14px; }
        .film-meta { display: flex; flex-wrap: wrap; gap: 10px; font-size: 14px; color: #444; }
        .film-desc { margin: 10px 0 8px; padding: 10px 12px; border: 1px solid #eee; border-radius: 10px; background: #fafafa; color: #333; white-space: pre-wrap; word-break: break-word; overflow-wrap: break-word; }
        .player { width: 100%; max-width: 900px; aspect-ratio: 16/9; border: 0; margin: 12px 0 16px; }
        @media (max-width: 768px) {
          .grid-table, .grid-table thead, .grid-table tbody, .grid-table th, .grid-table td, .grid-table tr { display: block; }
          .grid-table thead { display: none; }
          .grid-table tr { border: 1px solid #eee; border-radius: 10px; margin-bottom: 10px; padding: 10px; }
          .grid-table td { border: 0; padding: 6px 0; }
        }
      `}</style>

      <div className="topbar">
        <h2 style={{ margin: 0 }}>IA Film Rater</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 14, color: '#444' }}>{me.email}</span>
          <button onClick={logout}>Logout</button>
        </div>
      </div>

      {me?.is_admin ? (
        <AdminPanel apiJson={apiJson} onDataChanged={loadNextFilm} />
      ) : null}

      {loading ? <p>Loading…</p> : null}
      {error ? <div style={{ marginTop: 12, color: '#a00' }}>{error}</div> : null}
      {notice ? (
        <div role="status" style={{ marginTop: 12, padding: '12px 14px', border: '1px solid #cfd8e3', background: '#f4f8fc', borderRadius: 8, maxWidth: 620 }}>
          {notice.text}
          {me?.is_admin && notice.code === 'no_films' ? <div style={{ marginTop: 6, fontSize: 13, color: '#555' }}>As an admin, use Admin → Actions → Sync Collection.</div> : null}
        </div>
      ) : null}

      {film ? (
        <div className="film-panel">
          <h3 style={{ marginBottom: 6 }}>{film.title || film.identifier}</h3>
          <div className="film-meta">
            <div><strong>Identifier:</strong> {film.identifier}</div>
            {archiveUrl ? (
              <div>
                <a href={archiveUrl} target="_blank" rel="noreferrer">View on archive.org</a>
              </div>
            ) : null}
          </div>

          {film.description ? (
            <div className="film-desc">{linkifyText(film.description)}</div>
          ) : null}


          {film.embedUrl ? (
            <iframe className="player" src={film.embedUrl} allowFullScreen title={film.title || film.identifier} />
          ) : null}

          <table className="grid-table">
            <thead>
              <tr>
                <th scope="col" className="col-crit">Criterion</th>
                <th scope="col" className="col-range">Range</th>
                <th scope="col" className="col-score">Score</th>
                <th scope="col" className="col-quick">Quick</th>
              </tr>
            </thead>
            <tbody>
              {criteria.map((c) => {
                const v = scores[c.key] ?? ''
                const vInfo = validation.perKey[c.key] || { ok: true, hint: '' }
                const rangeSize = (c.max - c.min)
                const showQuick = rangeSize >= 1 && rangeSize <= 6
                const buttons = []
                if (showQuick) {
                  for (let n = c.min; n <= c.max; n++) buttons.push(n)
                }

                return (
                  <tr key={c.key} className={vInfo.ok ? '' : 'row-invalid'}>
                    <td>
                      <div>{c.label}</div>
                    </td>
                    <td>{c.min}–{c.max}</td>
                    <td>
                      <input
                        className="score-input"
                        type="number"
                        min={c.min}
                        max={c.max}
                        value={v}
                        aria-label={`Score for ${c.label}`}
                        onChange={(e) => setScores({ ...scores, [c.key]: e.target.value })}
                      />
                      {!vInfo.ok && vInfo.hint ? <div className="hint">{vInfo.hint}</div> : null}
                    </td>
                    <td>
                      {showQuick ? (
                        <div className="quick">
                          {buttons.map((n) => (
                            <button
                              key={n}
                              type="button"
                              onClick={() => setScores({ ...scores, [c.key]: String(n) })}
                              aria-label={`Set ${c.label} score to ${n}`}
                            >
                              {n}
                            </button>
                          ))}
                        </div>
                      ) : (
                        <span style={{ color: '#777' }}>—</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>

          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 14 }}>
            <button className="btn-primary" onClick={submit} disabled={!validation.allOk}>
              Submit & Next
            </button>
          </div>

          {submitError ? <div style={{ marginTop: 10, color: '#a00' }}>{submitError}</div> : null}
        </div>
      ) : notice || error || loading ? null : (
        <p style={{ marginTop: 14 }}>No films left.</p>
      )}
    </div>
  )
}
