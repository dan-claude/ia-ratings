import { Fragment, useEffect, useRef, useState } from 'react'

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

// The spreadsheet columns an import can use (key, label, required).
const IMPORT_FIELDS = [
  ['link', 'Archive.org link', true],
  ['title', 'Title', false],
  ['creator', 'Creator (the “by” credit)', false],
  ['description', 'Description', false],
  ['public_domain_works', 'Public domain works used', false],
  ['ai_disclosure', 'AI disclosure', false],
  ['eligible', 'Eligible (yes/no)', false],
]

function blankMapping() {
  return Object.fromEntries(IMPORT_FIELDS.map(([key]) => [key, null]))
}

// A date input value (YYYY-MM-DD, local) `days` from now.
function dateInDays(days) {
  const d = new Date(Date.now() + days * 86400000)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

// Sign-in links are built from the address the admin is using; the server only knows the path.
function fullLinkUrl(link) {
  return `${window.location.origin}${link.path}`
}

function describeLink(link) {
  if (!link) return 'no link'
  const when = new Date(link.expires_at).toLocaleDateString()
  return link.state === 'expired' ? `expired ${when}` : `active until ${when}`
}

// ---------------------------------------------------------------------------
// AdminPanel
// ---------------------------------------------------------------------------

function describeJob(st) {
  if (!st) return ''
  if (st.state === 'running') {
    return st.total ? `Looking up film titles on archive.org… ${st.done} of ${st.total}` : 'Looking up film titles on archive.org…'
  }
  if (st.state === 'done') return `Title lookup finished ${new Date(st.finished_at * 1000).toLocaleString()} — ${st.processed} titles found.`
  if (st.state === 'error') return `Last title lookup failed: ${st.error}`
  return ''
}

// ---------------------------------------------------------------------------
// Reviews: handing films out to reviewers, and how far reviewing has got
// ---------------------------------------------------------------------------

const STATUS_STYLE = {
  assigned: { background: '#eee', color: '#444' },
  seen: { background: '#fff3cd', color: '#6b5300' },
  rated: { background: '#d9f2d9', color: '#14561a' },
}

function StatusChip({ status }) {
  return <span style={{ ...STATUS_STYLE[status], borderRadius: 10, padding: '1px 8px', fontSize: 12 }}>{status}</span>
}

function ReviewsTab({ apiJson, onDataChanged }) {
  const [data, setData] = useState(null)   // { overall, people, films }
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmDistribute, setConfirmDistribute] = useState(false)
  const [resetOpen, setResetOpen] = useState(false)
  const [resetText, setResetText] = useState('')
  const [openPerson, setOpenPerson] = useState(null)   // person id whose films are shown
  const [onlyNeeding, setOnlyNeeding] = useState(false)
  const [addChoice, setAddChoice] = useState({})       // film identifier -> user id chosen in its "add" select

  async function load() {
    setError('')
    const { ok, data: d } = await apiJson('/api/admin/progress')
    if (ok) setData(d)
    else setError(d?.error || 'Could not load progress')
  }
  useEffect(() => { load() }, [])

  async function distribute() {
    setBusy(true); setMsg('')
    const { ok, data: d } = await apiJson('/api/admin/distribute', { method: 'POST' })
    setBusy(false); setConfirmDistribute(false)
    if (!ok) { setMsg(`Error: ${d?.error || 'Could not hand out the films'}`); return }
    setMsg(`Handed out ${d.films} films to ${d.reviewers} reviewers (${d.assignments} reviews; each reviewer has ${d.per_reviewer.min === d.per_reviewer.max ? d.per_reviewer.min : `${d.per_reviewer.min}–${d.per_reviewer.max}`} films).`)
    await load(); onDataChanged()
  }

  async function reset() {
    setBusy(true); setMsg('')
    const { ok, data: d } = await apiJson('/api/admin/distribute/reset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm: 'RESET' }),
    })
    setBusy(false)
    if (!ok) { setMsg(`Error: ${d?.error || 'Could not reset'}`); return }
    setMsg(`Reset: ${d.deleted.assignments} assignments and ${d.deleted.ratings} ratings deleted.`)
    setResetOpen(false); setResetText(''); setOpenPerson(null)
    await load(); onDataChanged()
  }

  async function addAssignment(film) {
    const uid = Number(addChoice[film.identifier])
    if (!uid) return
    setMsg('')
    const { ok, data: d } = await apiJson('/api/admin/assignments', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: uid, identifier: film.identifier }),
    })
    if (!ok) { setMsg(`Error: ${d?.error || 'Could not assign'}`); return }
    setAddChoice({ ...addChoice, [film.identifier]: '' })
    await load()
  }

  async function removeAssignment(film, a) {
    setMsg('')
    const { ok, data: d } = await apiJson(`/api/admin/assignments/${a.user_id}/${encodeURIComponent(film.identifier)}`, { method: 'DELETE' })
    if (!ok) { setMsg(`Error: ${d?.error || 'Could not remove'}`); return }
    await load()
  }

  if (!data) return error ? <div style={{ color: '#a00' }}>{error}</div> : <p style={{ color: '#666' }}>Loading…</p>

  const o = data.overall
  const raters = data.people.filter((p) => p.roles.includes('reviewer') || p.roles.includes('judge'))
  const person = data.people.find((p) => p.id === openPerson)
  const personFilms = person
    ? data.films.map((f) => ({ f, a: f.assignees.find((x) => x.user_id === person.id) })).filter((x) => x.a)
    : []
  const films = onlyNeeding ? data.films.filter((f) => !f.fully_reviewed) : data.films

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div role="status" style={{ border: '1px solid #cfd8e3', background: '#f4f8fc', borderRadius: 8, padding: '10px 14px', maxWidth: 700 }}>
        <div style={{ fontSize: 15 }}>
          <strong>{o.fully_reviewed}</strong> of <strong>{o.films}</strong> films fully reviewed; <strong>{o.needing_reviews}</strong> still need at least one review.
        </div>
        <div style={{ fontSize: 12, color: '#555', marginTop: 4 }}>
          A film is fully reviewed when {o.reviews_per_film} reviewers have submitted. Reviews handed out: {o.assignments.assigned + o.assignments.seen + o.assignments.rated}
          {' '}({o.assignments.assigned} not opened, {o.assignments.seen} opened, {o.assignments.rated} submitted).
        </div>
        <button onClick={load} style={{ fontSize: 12, marginTop: 6 }}>↻ Update</button>
      </div>

      {msg && <div style={{ fontSize: 13, color: msg.startsWith('Error') ? '#a00' : '#060' }}>{msg}</div>}

      {!o.distributed ? (
        <div style={{ border: '1px solid #ddd', borderRadius: 8, padding: 12, maxWidth: 700 }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Hand out the films</div>
          <div style={{ fontSize: 13, color: '#555', marginBottom: 8 }}>
            Gives every film to {o.reviews_per_film} different reviewers, chosen at random and spread evenly. It runs once; to run it again you must reset first.
          </div>
          {!confirmDistribute ? (
            <button className="btn-primary" onClick={() => setConfirmDistribute(true)} disabled={o.films === 0}>Distribute films to reviewers…</button>
          ) : (
            <div>
              <div style={{ fontSize: 13, marginBottom: 6 }}>Hand out {o.films} films to the {raters.filter((p) => p.roles.includes('reviewer')).length} reviewers now?</div>
              <button className="btn-primary" onClick={distribute} disabled={busy}>{busy ? 'Working…' : 'Yes, hand them out'}</button>{' '}
              <button onClick={() => setConfirmDistribute(false)} disabled={busy}>Cancel</button>
            </div>
          )}
        </div>
      ) : (
        <div style={{ border: '1px solid #ddd', borderRadius: 8, padding: 12, maxWidth: 700 }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Films have been handed out</div>
          {!resetOpen ? (
            <button onClick={() => { setResetOpen(true); setMsg('') }} style={{ color: '#a00' }}>Reset distribution…</button>
          ) : (
            <div style={{ border: '1px solid #e0b4b4', background: '#fff6f6', borderRadius: 8, padding: 12 }}>
              <p style={{ margin: '0 0 8px', fontSize: 13 }}>
                This deletes <strong>every assignment and every rating</strong> ({o.assignments.rated} submitted so far) and empties the judges' pool, so the films can be
                handed out again. Download a backup first (Backup tab).
              </p>
              <label style={{ fontSize: 13 }}>Type <code>RESET</code> to confirm:{' '}
                <input value={resetText} onChange={(e) => setResetText(e.target.value)} style={{ width: 90 }} autoComplete="off" />
              </label>
              <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                <button onClick={reset} disabled={resetText !== 'RESET' || busy} style={{ color: '#a00' }}>{busy ? 'Resetting…' : 'Reset distribution'}</button>
                <button onClick={() => { setResetOpen(false); setResetText('') }} disabled={busy}>Cancel</button>
              </div>
            </div>
          )}
        </div>
      )}

      <div>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>People</div>
        {raters.length === 0 ? <p style={{ color: '#666', margin: 0 }}>No reviewers or judges yet (Users tab).</p> : (
          <table className="grid-table" style={{ tableLayout: 'auto', fontSize: 13 }}>
            <thead><tr><th>person</th><th>roles</th><th>not opened</th><th>opened</th><th>submitted</th><th>total</th><th></th></tr></thead>
            <tbody>
              {data.people.map((p) => (
                <tr key={p.id}>
                  <td style={{ wordBreak: 'break-all' }}>{p.email}</td>
                  <td>{p.roles.join(', ') || '—'}</td>
                  <td>{p.assigned}</td><td>{p.seen}</td><td>{p.rated}</td><td>{p.total}</td>
                  <td>{p.total > 0 && <button style={{ fontSize: 12 }} onClick={() => setOpenPerson(openPerson === p.id ? null : p.id)}>{openPerson === p.id ? 'Hide films' : 'Show films'}</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {person && (
          <div style={{ marginTop: 10, border: '1px solid #ddd', borderRadius: 8, padding: 10, maxWidth: 700 }}>
            <div style={{ fontWeight: 600, marginBottom: 6 }}>Films for {person.email}</div>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>
              {personFilms.map(({ f, a }) => <li key={f.identifier}>{f.title} <StatusChip status={a.status} /></li>)}
            </ul>
          </div>
        )}
      </div>

      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 6 }}>
          <span style={{ fontWeight: 600 }}>Films</span>
          <label style={{ fontSize: 13 }}><input type="checkbox" checked={onlyNeeding} onChange={(e) => setOnlyNeeding(e.target.checked)} /> Only films that still need reviews ({o.needing_reviews})</label>
        </div>
        {films.length === 0 ? <p style={{ color: '#666', margin: 0 }}>{o.films === 0 ? 'No films yet (Import tab).' : 'Every film is fully reviewed.'}</p> : (
          <div style={{ overflowX: 'auto' }}>
            <table className="grid-table" style={{ tableLayout: 'auto', fontSize: 13 }}>
              <thead><tr><th>film</th><th>reviews</th><th>reviewers</th><th>add by hand</th></tr></thead>
              <tbody>
                {films.map((f) => {
                  const free = raters.filter((p) => !f.assignees.some((a) => a.user_id === p.id))
                  return (
                    <tr key={f.identifier}>
                      <td>{f.title}{f.creator && <span style={{ color: '#666' }}> by {f.creator}</span>}</td>
                      <td style={{ whiteSpace: 'nowrap' }}>{f.rated} / {o.reviews_per_film}{f.fully_reviewed ? ' ✓' : ''}</td>
                      <td>
                        {f.assignees.length === 0 ? <span style={{ color: '#aaa' }}>—</span> : f.assignees.map((a) => (
                          <div key={a.user_id} style={{ whiteSpace: 'nowrap' }}>
                            {a.email} <StatusChip status={a.status} />
                            {a.status !== 'rated' && <button style={{ fontSize: 11, marginLeft: 4 }} title="Take this film off their list" aria-label={`Remove ${f.title} from ${a.email}`} onClick={() => removeAssignment(f, a)}>✕</button>}
                          </div>
                        ))}
                      </td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        <select value={addChoice[f.identifier] || ''} onChange={(e) => setAddChoice({ ...addChoice, [f.identifier]: e.target.value })} aria-label={`Person to give ${f.title} to`} style={{ maxWidth: 170 }}>
                          <option value="">— person —</option>
                          {free.map((p) => <option key={p.id} value={p.id}>{p.email} ({p.roles.filter((r) => r !== 'admin').join('/')})</option>)}
                        </select>{' '}
                        <button style={{ fontSize: 12 }} disabled={!addChoice[f.identifier]} onClick={() => addAssignment(f)}>Add</button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// onDataChanged: called after an import or when the DB is emptied, so the
// rating view can reload.
function AdminPanel({ apiJson, onDataChanged, meId }) {
  const [tab, setTab] = useState('actions')

  // Background job state (the title lookup after an import; status comes from the server, so it survives a page reload)
  const [jobStatus, setJobStatus] = useState(null)   // { state, kind, phase, done, total, processed, error, film_count, ... }
  const prevJobState = useRef(null)

  // Spreadsheet (CSV) import state
  const [impFile, setImpFile] = useState('')          // file name, for display
  const [impCsv, setImpCsv] = useState('')            // CSV text
  const [impPreview, setImpPreview] = useState(null)  // { headers, row_count, sample_rows }
  const [impMap, setImpMap] = useState(blankMapping())
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
  const [invEmail, setInvEmail] = useState('')
  const [invRoles, setInvRoles] = useState({ admin: false, reviewer: true, judge: false })
  const [invExpiry, setInvExpiry] = useState(dateInDays(30))
  const [invBusy, setInvBusy] = useState(false)
  const [newLink, setNewLink] = useState(null)      // { email, url, expires_at } — shown once, never stored
  const [rowExpiry, setRowExpiry] = useState({})    // user id -> date text for that row's link controls
  const [copied, setCopied] = useState(false)

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
    const { ok, data } = await apiJson('/api/admin/users')
    setUsersLoading(false)
    if (ok) setUsers(data)
    else setUsersError(data?.error || 'Failed to load users')
  }

  async function setRole(user, role, on) {
    setActionMsg('')
    const current = [user.is_admin ? 'admin' : null, user.is_reviewer ? 'reviewer' : null, user.is_judge ? 'judge' : null].filter(Boolean)
    const roles = on ? [...new Set([...current, role])] : current.filter((r) => r !== role)
    const { ok, data } = await apiJson(`/api/admin/users/${user.id}/roles`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ roles }),
    })
    if (ok) {
      setActionMsg(`Roles for user ${user.id} updated: ${data.roles.length ? data.roles.join(', ') : 'none'}.`)
    } else {
      setActionMsg(data?.error || 'Action failed')
    }
    loadUsers()
  }

  async function sendInvite(e) {
    e.preventDefault()
    setInvBusy(true); setActionMsg(''); setNewLink(null); setCopied(false)
    const roles = Object.keys(invRoles).filter((r) => invRoles[r])
    const { ok, data } = await apiJson('/api/admin/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: invEmail, roles, expires_at: invExpiry || null }),
    })
    setInvBusy(false)
    if (!ok) { setActionMsg(`Error: ${data?.error || 'Could not invite that person'}`); return }
    setNewLink({ email: data.user.email, url: fullLinkUrl(data.link), expires_at: data.link.expires_at })
    setInvEmail('')
    loadUsers()
  }

  function expiryFor(u) { return rowExpiry[u.id] ?? dateInDays(30) }

  async function issueLink(u) {
    setActionMsg(''); setNewLink(null); setCopied(false)
    const { ok, data } = await apiJson(`/api/admin/users/${u.id}/login-link`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expires_at: expiryFor(u) }),
    })
    if (!ok) { setActionMsg(`Error: ${data?.error || 'Could not create a link'}`); return }
    setNewLink({ email: u.email, url: fullLinkUrl(data.link), expires_at: data.link.expires_at })
    loadUsers()
  }

  async function cancelLink(u) {
    setActionMsg(''); setNewLink(null)
    const { ok, data } = await apiJson(`/api/admin/users/${u.id}/login-link`, { method: 'DELETE' })
    if (!ok) { setActionMsg(`Error: ${data?.error || 'Could not cancel the link'}`); return }
    setActionMsg(`Link cancelled for ${u.email}; they are logged out.`)
    loadUsers()
  }

  async function changeExpiry(u) {
    setActionMsg('')
    const { ok, data } = await apiJson(`/api/admin/users/${u.id}/login-link`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expires_at: expiryFor(u) }),
    })
    if (!ok) { setActionMsg(`Error: ${data?.error || 'Could not change the expiry'}`); return }
    setActionMsg(`Link for ${u.email} now expires ${new Date(data.expires_at).toLocaleDateString()}.`)
    loadUsers()
  }

  async function copyLink() {
    try { await navigator.clipboard.writeText(newLink.url); setCopied(true) } catch { setCopied(false) }
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
    setImpMap(blankMapping())
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
      setImpMap({ ...data.suggested_mapping })
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
      body: importBody({
        on_existing: impOnExisting || 'skip',
        lookup_titles: impLookup,
      }),
    })
    setImpBusy(false)
    if (!ok) { setImpMsg(`Error: ${data?.error || 'Import failed'}`); return }
    setImpResult({ result: data.result, skipped: data.skipped, file: impFile })
    resetImport()
    setTables(null); setRows(null)
    await loadJobStatus()    // starts progress polling if a title lookup was started
    onDataChanged()
  }

  async function loadJobStatus() {
    const { ok, data } = await apiJson('/api/admin/jobs/status')
    if (ok) setJobStatus(data)
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
      setEmptyMsg(`Emptied: ${d.films ?? 0} films, ${d.assignments ?? 0} assignments and ${d.ratings ?? 0} ratings deleted.`)
      setEmptyOpen(false)
      setEmptyConfirmText('')
      setTables(null); setRows(null)   // invalidate cached DB browser data
      await loadJobStatus()
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

  // Load the job status once, then poll while a job is running.
  useEffect(() => { loadJobStatus() }, [])
  useEffect(() => {
    if (jobStatus?.state !== 'running') return
    const id = setInterval(loadJobStatus, 1500)
    return () => clearInterval(id)
  }, [jobStatus?.state])
  // When a job we were watching completes, refresh the rating view.
  useEffect(() => {
    const cur = jobStatus?.state
    if (prevJobState.current === 'running' && cur && cur !== 'running') onDataChanged()
    prevJobState.current = cur
  }, [jobStatus?.state])

  useEffect(() => {
    if (tab === 'db'       && tables   === null) loadTables()
    if (tab === 'users'    && users    === null) loadUsers()
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
        {['actions', 'import', 'users', 'reviews', 'db', 'backup'].map(t => (
          <button key={t} style={tabStyle(t)} onClick={() => setTab(t)}>
            {{ actions: 'Actions', import: 'Import', users: 'Users', reviews: 'Reviews', db: 'DB Browser', backup: 'Backup' }[t]}
          </button>
        ))}
      </div>

      <div style={{ padding: 14 }}>

        {/* ── Reviews ── */}
        {tab === 'reviews' && <ReviewsTab apiJson={apiJson} onDataChanged={onDataChanged} />}

        {/* ── Actions ── */}
        {tab === 'actions' && (() => {
          const running = jobStatus?.state === 'running'
          return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div style={{ fontSize: 14 }}>
                Films in the database: <strong>{jobStatus ? jobStatus.film_count : '…'}</strong>
              </div>

              {jobStatus && jobStatus.state !== 'idle' && (
                <div role="status" style={{ fontSize: 13, color: jobStatus.state === 'error' ? '#a00' : running ? '#666' : '#060' }}>
                  {running && <progress style={{ width: 320, display: 'block', marginBottom: 6 }} {...(jobStatus.total ? { value: jobStatus.done, max: jobStatus.total } : {})} aria-label="Background job progress" />}
                  {describeJob(jobStatus)}
                </div>
              )}

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
                      This permanently deletes <strong>all films, assignments and ratings</strong>. User accounts are kept.
                      Download a backup first (Backup tab) if you might want the data back.
                      Raters will see "film database hasn't been set up" until you import again.
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
          const running = jobStatus?.state === 'running'
          const headers = impPreview?.headers || []
          const colLabel = (i) => `${i + 1}. ${(headers[i] || '(no header)').slice(0, 60)}`
          const setCol = (key) => (e) => setImpMap({ ...impMap, [key]: e.target.value === '' ? null : Number(e.target.value) })
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
                Add films from a spreadsheet exported as <strong>CSV</strong>.
                Only rows with an <strong>archive.org</strong> link are imported; other rows (YouTube links, free text, blanks) are skipped. If you map the <strong>Eligible</strong> column, only rows that say <em>yes</em> are imported; <em>no</em>, blank and unclear rows are skipped and listed.
              </p>

              {running && <div role="status" style={{ fontSize: 13, color: '#666' }}>{describeJob(jobStatus)}</div>}

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
                      {IMPORT_FIELDS.map(([key, label, required]) => (
                        <Fragment key={key}>
                          <label>{label}{required && <span style={{ color: '#a00' }}> *</span>}</label>{select(key, !required)}
                        </Fragment>
                      ))}
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
                        , <strong>{sum.skipped}</strong> skipped{sum.ineligible > 0 && <> (<strong>{sum.ineligible}</strong> not eligible)</>}.
                      </div>
                      {impPlan.samples.length > 0 && (
                        <ul style={{ margin: '8px 0 0', paddingLeft: 18, fontSize: 13 }}>
                          {impPlan.samples.map(f => (
                            <li key={f.row}>
                              <strong>{f.title || <em>(title will be looked up)</em>}</strong>{f.creator && <> by {f.creator}</>} — {f.identifier}
                              {f.exists && <span style={{ color: '#a60' }}> (already in the database)</span>}
                            </li>
                          ))}
                        </ul>
                      )}

                      {sum.ineligible_in_database > 0 && (
                        <div style={{ marginTop: 8, padding: '8px 10px', border: '1px solid #e0cfa8', background: '#fffaf0', borderRadius: 6, fontSize: 13 }}>
                          {sum.ineligible_in_database} film{sum.ineligible_in_database === 1 ? ' is' : 's are'} already in the database but now marked not eligible in this
                          spreadsheet. An import never removes films, so {sum.ineligible_in_database === 1 ? 'it stays' : 'they stay'} in the database
                          (delete the film database and re-import if they must go).
                        </div>
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
            <form onSubmit={sendInvite} style={{ border: '1px solid #ddd', borderRadius: 8, padding: 12, marginBottom: 14, maxWidth: 640 }}>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>Invite a person</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
                <input
                  type="email" required placeholder="email address" value={invEmail}
                  onChange={(e) => setInvEmail(e.target.value)} style={{ width: 240 }} aria-label="Email address to invite"
                />
                {['admin', 'reviewer', 'judge'].map((r) => (
                  <label key={r} style={{ fontSize: 13 }}>
                    <input type="checkbox" checked={invRoles[r]} onChange={(e) => setInvRoles({ ...invRoles, [r]: e.target.checked })} /> {r[0].toUpperCase() + r.slice(1)}
                  </label>
                ))}
                <label style={{ fontSize: 13 }}>
                  Link valid until{' '}
                  <input type="date" required value={invExpiry} min={dateInDays(1)} onChange={(e) => setInvExpiry(e.target.value)} />
                </label>
                <button className="btn-primary" type="submit" disabled={invBusy || !invEmail.trim()}>{invBusy ? 'Inviting…' : 'Invite'}</button>
              </div>
              <div style={{ fontSize: 12, color: '#555', marginTop: 6 }}>
                The app sends no email: you get a personal sign-in link to pass on. The person can use it as often as they like until it expires.
              </div>
            </form>

            {newLink && (
              <div role="status" style={{ border: '1px solid #b9d9b9', background: '#f3faf3', borderRadius: 8, padding: 12, marginBottom: 14, maxWidth: 760 }}>
                <div style={{ fontSize: 13, marginBottom: 6 }}>
                  Sign-in link for <strong>{newLink.email}</strong> (valid until {new Date(newLink.expires_at).toLocaleDateString()}).
                  <strong> Copy it now — it can't be shown again.</strong> If it is lost, create a new link.
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <input readOnly value={newLink.url} onFocus={(e) => e.target.select()} style={{ flex: 1, fontFamily: 'monospace', fontSize: 12 }} aria-label="Sign-in link" />
                  <button type="button" onClick={copyLink}>{copied ? 'Copied' : 'Copy'}</button>
                  <button type="button" onClick={() => setNewLink(null)}>Done</button>
                </div>
              </div>
            )}

            {actionMsg && <div style={{ marginBottom: 8, color: actionMsg.startsWith('Error') ? '#a00' : '#060', fontSize: 13 }}>{actionMsg}</div>}
            {usersError && <div style={{ color: '#a00', marginBottom: 8 }}>{usersError}</div>}
            <button onClick={loadUsers} disabled={usersLoading} style={{ marginBottom: 10, fontSize: 12 }}>
              {usersLoading ? 'Loading…' : '↻ Update'}
            </button>
            {users && (
              <div style={{ overflowX: 'auto' }}>
                <table className="grid-table" style={{ tableLayout: 'auto', fontSize: 13 }}>
                  <thead>
                    <tr>
                      <th>id</th>
                      <th>email</th>
                      <th>roles</th>
                      <th>sign-in link</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.map(u => (
                      <tr key={u.id}>
                        <td>{u.id}</td>
                        <td style={{ wordBreak: 'break-all' }}>{u.email}</td>
                        <td style={{ whiteSpace: 'nowrap' }}>
                          {[['admin', 'is_admin', 'Admin'], ['reviewer', 'is_reviewer', 'Reviewer'], ['judge', 'is_judge', 'Judge']].map(([role, col, label]) => {
                            const own = role === 'admin' && u.id === meId && !!u[col]
                            return (
                              <label key={role} style={{ marginRight: 12 }} title={own ? "You can't remove your own admin role" : undefined}>
                                <input
                                  type="checkbox"
                                  checked={!!u[col]}
                                  disabled={own}
                                  onChange={(e) => setRole(u, role, e.target.checked)}
                                  aria-label={`${label} role for ${u.email}`}
                                /> {label}
                              </label>
                            )
                          })}
                        </td>
                        <td>
                          <div style={{ color: u.link?.state === 'active' ? '#060' : '#a60', marginBottom: 4 }}>{describeLink(u.link)}</div>
                          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                            <input
                              type="date" value={expiryFor(u)} min={dateInDays(1)}
                              onChange={(e) => setRowExpiry({ ...rowExpiry, [u.id]: e.target.value })}
                              aria-label={`Expiry date for ${u.email}`}
                            />
                            <button style={{ fontSize: 12 }} onClick={() => issueLink(u)}>New link</button>
                            {u.link && <button style={{ fontSize: 12 }} onClick={() => changeExpiry(u)}>Set expiry</button>}
                            {u.link && <button style={{ fontSize: 12, color: '#a00' }} onClick={() => cancelLink(u)}>Cancel link</button>}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div style={{ fontSize: 12, color: '#666', marginTop: 6 }}>
                  {users.length} user{users.length !== 1 ? 's' : ''}. A new or cancelled link also logs that person out everywhere.
                </div>
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
                Exports all tables (users, films, assignments, ratings, etc.) as a single
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
// Main App
// ---------------------------------------------------------------------------

// What the rating screen shows when /api/films/next has no film. These codes are not errors.
const NOTICE_CODES = ['no_role', 'no_films', 'no_assignments', 'all_rated']

export default function App() {
  const [me, setMe] = useState(null)
  const [meLoaded, setMeLoaded] = useState(false)

  // A magic link opens /signin#<secret>. The secret is kept out of the address bar and history
  // once read, and nothing happens until the person presses "Sign in" (so link previewers
  // in chat and email apps can't use it up or sign anyone in).
  const [signinToken, setSigninToken] = useState(() => (window.location.pathname === '/signin' ? window.location.hash.slice(1) : null))
  const [signinError, setSigninError] = useState('')
  const [signinBusy, setSigninBusy] = useState(false)

  const [film, setFilm] = useState(null)
  const [categories, setCategories] = useState([])
  const [scores, setScores] = useState({}) // key -> number
  const [comment, setComment] = useState('')

  // Shown instead of a film when there is nothing to rate.
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
    setMeLoaded(true)
  }

  async function logout() {
    await apiJson('/api/auth/logout', { method: 'POST' })
    setMe(null)
    setFilm(null)
    setCategories([])
    setScores({})
    setComment('')
  }

  async function loadCategories() {
    const { ok, data } = await apiJson('/api/categories')
    setCategories(ok && Array.isArray(data) ? data : [])
  }

  async function loadNextFilm() {
    setError('')
    setNotice(null)
    setSubmitError('')
    const { ok, data } = await apiJson('/api/films/next')
    if (ok) {
      setFilm(data)
      setScores({})
      setComment('')
    } else {
      setFilm(null)
      if (NOTICE_CODES.includes(data?.code)) {
        setNotice({ code: data.code, text: data.error })
      } else {
        setError(data?.error || 'Could not load the next film')
      }
    }
  }

  async function submit() {
    if (!film?.identifier) return
    setSubmitError('')
    const { ok, data } = await apiJson(`/api/films/${encodeURIComponent(film.identifier)}/ratings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scores, comment })
    })

    if (!ok) {
      setSubmitError(data?.error || 'Submit failed')
      return
    }

    // advance
    await loadNextFilm()
  }

  useEffect(() => {
    if (window.location.pathname === '/signin' && window.location.hash) {
      window.history.replaceState({}, '', '/signin')
    }
    loadMe()
  }, [])

  async function signIn() {
    setSigninBusy(true); setSigninError('')
    const { ok, data } = await apiJson('/api/auth/signin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: signinToken }),
    })
    setSigninBusy(false)
    if (!ok) { setSigninError(data?.error || 'Could not sign in. Try again.'); return }
    window.history.replaceState({}, '', '/')
    setSigninToken(null)
    await loadMe()
  }

  useEffect(() => {
    if (me) {
      setLoading(true)
      Promise.all([loadCategories(), loadNextFilm()]).finally(() => setLoading(false))
    }
  }, [me])

  const allChosen = !!film?.identifier && categories.length > 0 && categories.every((c) => Number.isInteger(scores[c.key]))

  if (window.location.pathname === '/signin' && !me) {
    return (
      <div style={{ padding: 20, maxWidth: 520 }}>
        <h2>IA Film Rater</h2>
        {signinToken ? (
          <>
            <p style={{ marginTop: 0 }}>You've been invited to rate films. Press the button to sign in on this device.</p>
            {signinError ? <div role="alert" style={{ margin: '12px 0', color: '#a00' }}>{signinError}</div> : null}
            <button className="btn-primary" onClick={signIn} disabled={signinBusy}>{signinBusy ? 'Signing in…' : 'Sign in'}</button>
          </>
        ) : (
          <p style={{ marginTop: 0 }}>This sign-in link is incomplete. Open the whole link from your invitation again, or ask an administrator for a new one.</p>
        )}
      </div>
    )
  }

  if (!me) {
    return (
      <div style={{ padding: 20, maxWidth: 520 }}>
        <h2>IA Film Rater</h2>
        {meLoaded ? (
          <p style={{ marginTop: 0 }}>
            Sign-in is by invitation. Open the personal sign-in link an administrator sent you.
          </p>
        ) : null}
      </div>
    )
  }

  return (
    <div style={{ padding: 20, maxWidth: 980 }}>
      <style>{`
        .grid-table { width: 100%; border-collapse: collapse; table-layout: fixed; }
        .grid-table th { text-align: left; font-weight: 600; border-bottom: 2px solid #ddd; padding: 10px 8px; }
        .grid-table td { border-bottom: 1px solid #eee; padding: 10px 8px; vertical-align: middle; }
        .quick { display: flex; flex-wrap: wrap; gap: 6px; }
        .quick button { padding: 4px 8px; }
        .quick button.chosen { background: #1a56c4; color: #fff; border-color: #1a56c4; }
        .btn-primary { padding: 10px 14px; }
        .btn-primary[disabled] { opacity: 0.5; cursor: not-allowed; }
        .topbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
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
        <AdminPanel apiJson={apiJson} onDataChanged={loadNextFilm} meId={me.id} />
      ) : null}

      {loading ? <p>Loading…</p> : null}
      {error ? <div style={{ marginTop: 12, color: '#a00' }}>{error}</div> : null}
      {notice ? (
        <div role="status" style={{ marginTop: 12, padding: '12px 14px', border: '1px solid #cfd8e3', background: '#f4f8fc', borderRadius: 8, maxWidth: 620 }}>
          {notice.text}
          {me?.is_admin && notice.code === 'no_films' ? <div style={{ marginTop: 6, fontSize: 13, color: '#555' }}>As an admin, use Admin → Import.</div> : null}
        </div>
      ) : null}

      {film ? (
        <div className="film-panel">
          <h3 style={{ margin: '0 0 6px' }}>
            <a href={film.archiveUrl} target="_blank" rel="noreferrer">{film.title}</a>
            {film.creator ? <span style={{ fontWeight: 400 }}> by {film.creator}</span> : null}
          </h3>

          {film.description ? (
            <div className="film-desc">{linkifyText(film.description)}</div>
          ) : null}
          {film.publicDomainWorks ? (
            <div className="film-desc"><strong>Public domain works used</strong>{'\n'}{linkifyText(film.publicDomainWorks)}</div>
          ) : null}
          {film.aiDisclosure ? (
            <div className="film-desc"><strong>AI disclosure</strong>{'\n'}{linkifyText(film.aiDisclosure)}</div>
          ) : null}

          {film.embedUrl ? (
            <iframe className="player" src={film.embedUrl} allowFullScreen title={film.title} />
          ) : null}

          <table className="grid-table">
            <tbody>
              {categories.map((c) => (
                <tr key={c.key}>
                  <td>
                    <div><strong>{c.label}</strong></div>
                    <div style={{ fontSize: 13, color: '#555' }}>{c.description}</div>
                  </td>
                  <td>
                    <div className="quick" role="group" aria-label={`Score for ${c.label}`}>
                      {Array.from({ length: c.max - c.min + 1 }, (_, i) => c.min + i).map((n) => (
                        <button
                          key={n}
                          type="button"
                          className={scores[c.key] === n ? 'chosen' : ''}
                          aria-pressed={scores[c.key] === n}
                          onClick={() => setScores((prev) => ({ ...prev, [c.key]: n }))}
                        >
                          {n}
                        </button>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <label style={{ display: 'block', marginTop: 14 }}>
            <strong>Comments on Film</strong> <span style={{ fontSize: 12, color: '#555' }}>(May be used in presentation)</span>
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value.slice(0, 1000))}
              rows={5}
              style={{ display: 'block', width: '100%', boxSizing: 'border-box', font: 'inherit', padding: 8, marginTop: 4 }}
            />
            <span style={{ fontSize: 12, color: '#666' }}>{comment.length} / 1000</span>
          </label>

          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 14 }}>
            <button className="btn-primary" onClick={submit} disabled={!allChosen}>
              Submit & Next
            </button>
          </div>

          {submitError ? <div style={{ marginTop: 10, color: '#a00' }}>{submitError}</div> : null}
        </div>
      ) : null}
    </div>
  )
}
