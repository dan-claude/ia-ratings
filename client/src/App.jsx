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
  assigned: { background: 'var(--border-soft)', color: 'var(--text-2)' },
  seen: { background: 'var(--chip-seen-bg)', color: 'var(--chip-seen-fg)' },
  rated: { background: 'var(--chip-rated-bg)', color: 'var(--chip-rated-fg)' },
}

function StatusChip({ status, label }) {
  return <span style={{ ...STATUS_STYLE[status], borderRadius: 10, padding: '1px 8px', fontSize: 12 }}>{label || status}</span>
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

  if (!data) return error ? <div style={{ color: 'var(--danger)' }}>{error}</div> : <p style={{ color: 'var(--muted)' }}>Loading…</p>

  const o = data.overall
  const raters = data.people.filter((p) => p.roles.includes('reviewer') || p.roles.includes('judge'))
  const person = data.people.find((p) => p.id === openPerson)
  const personFilms = person
    ? data.films.map((f) => ({ f, a: f.assignees.find((x) => x.user_id === person.id) })).filter((x) => x.a)
    : []
  const films = onlyNeeding ? data.films.filter((f) => !f.fully_reviewed) : data.films

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div role="status" style={{ border: '1px solid var(--info-border)', background: 'var(--info-bg)', borderRadius: 8, padding: '10px 14px', maxWidth: 700 }}>
        <div style={{ fontSize: 15 }}>
          <strong>{o.fully_reviewed}</strong> of <strong>{o.films}</strong> films fully reviewed; <strong>{o.needing_reviews}</strong> still need at least one review.
        </div>
        <div style={{ fontSize: 12, color: 'var(--muted-2)', marginTop: 4 }}>
          A film is fully reviewed when {o.reviews_per_film} reviewers have submitted. Reviews handed out: {o.assignments.assigned + o.assignments.seen + o.assignments.rated}
          {' '}({o.assignments.assigned} not opened, {o.assignments.seen} opened, {o.assignments.rated} submitted).
        </div>
        <button onClick={load} style={{ fontSize: 12, marginTop: 6 }}>↻ Update</button>
      </div>

      {msg && <div style={{ fontSize: 13, color: msg.startsWith('Error') ? 'var(--danger)' : 'var(--ok)' }}>{msg}</div>}

      {!o.distributed ? (
        <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, maxWidth: 700 }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Hand out the films</div>
          <div style={{ fontSize: 13, color: 'var(--muted-2)', marginBottom: 8 }}>
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
        <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, maxWidth: 700 }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Films have been handed out</div>
          {!resetOpen ? (
            <button onClick={() => { setResetOpen(true); setMsg('') }} style={{ color: 'var(--danger)' }}>Reset distribution…</button>
          ) : (
            <div style={{ border: '1px solid var(--danger-border)', background: 'var(--danger-bg)', borderRadius: 8, padding: 12 }}>
              <p style={{ margin: '0 0 8px', fontSize: 13 }}>
                This deletes <strong>every assignment and every rating</strong> ({o.assignments.rated} submitted so far) and empties the judges' pool, so the films can be
                handed out again. Download a backup first (Backup tab).
              </p>
              <label style={{ fontSize: 13 }}>Type <code>RESET</code> to confirm:{' '}
                <input value={resetText} onChange={(e) => setResetText(e.target.value)} style={{ width: 90 }} autoComplete="off" />
              </label>
              <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                <button onClick={reset} disabled={resetText !== 'RESET' || busy} style={{ color: 'var(--danger)' }}>{busy ? 'Resetting…' : 'Reset distribution'}</button>
                <button onClick={() => { setResetOpen(false); setResetText('') }} disabled={busy}>Cancel</button>
              </div>
            </div>
          )}
        </div>
      )}

      <div>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>People</div>
        {raters.length === 0 ? <p style={{ color: 'var(--muted)', margin: 0 }}>No reviewers or judges yet (Users tab).</p> : (
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
          <div style={{ marginTop: 10, border: '1px solid var(--border)', borderRadius: 8, padding: 10, maxWidth: 700 }}>
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
        {films.length === 0 ? <p style={{ color: 'var(--muted)', margin: 0 }}>{o.films === 0 ? 'No films yet (Import tab).' : 'Every film is fully reviewed.'}</p> : (
          <div style={{ overflowX: 'auto' }}>
            <table className="grid-table" style={{ tableLayout: 'auto', fontSize: 13 }}>
              <thead><tr><th>film</th><th>reviews</th><th>reviewers</th><th>add by hand</th></tr></thead>
              <tbody>
                {films.map((f) => {
                  const free = raters.filter((p) => !f.assignees.some((a) => a.user_id === p.id))
                  return (
                    <tr key={f.identifier}>
                      <td>{f.title}{f.creator && <span style={{ color: 'var(--muted)' }}> by {f.creator}</span>}</td>
                      <td style={{ whiteSpace: 'nowrap' }}>{f.rated} / {o.reviews_per_film}{f.fully_reviewed ? ' ✓' : ''}</td>
                      <td>
                        {f.assignees.length === 0 ? <span style={{ color: 'var(--faint)' }}>—</span> : f.assignees.map((a) => (
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

// ---------------------------------------------------------------------------
// Rankings and the judges' pool
// ---------------------------------------------------------------------------

function ScoreCell({ f }) {
  return f.average === null ? <span style={{ color: 'var(--faint)' }}>—</span> : <>{f.average.toFixed(2)}</>
}

function RankingTable({ films, openId, setOpenId }) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="grid-table" style={{ tableLayout: 'auto', fontSize: 13 }}>
        <thead><tr><th>rank</th><th>film</th><th>average</th><th>reviews</th><th></th></tr></thead>
        <tbody>
          {films.map((f) => (
            <Fragment key={f.identifier}>
              <tr>
                <td>{f.rank ?? '—'}</td>
                <td>{f.title}{f.creator && <span style={{ color: 'var(--muted)' }}> by {f.creator}</span>}{f.in_judges_pool && <span style={{ marginLeft: 6, background: 'var(--badge-bg)', borderRadius: 10, padding: '1px 8px', fontSize: 12 }}>judges' pool</span>}</td>
                <td><ScoreCell f={f} /></td>
                <td>{f.reviews}</td>
                <td>{setOpenId && <button style={{ fontSize: 12 }} onClick={() => setOpenId(openId === f.identifier ? null : f.identifier)}>{openId === f.identifier ? 'Hide details' : 'Details'}</button>}</td>
              </tr>
              {openId === f.identifier && (
                <tr><td colSpan={5} style={{ whiteSpace: 'pre-wrap', background: 'var(--surface-alt)', fontSize: 13 }}>
                  <div><strong>Archive.org:</strong> <a href={`https://archive.org/details/${f.identifier}`} target="_blank" rel="noreferrer">{f.identifier}</a></div>
                  {f.description && <div style={{ marginTop: 6 }}><strong>Description</strong>{'\n'}{f.description}</div>}
                  {f.public_domain_works && <div style={{ marginTop: 6 }}><strong>Public domain works used</strong>{'\n'}{f.public_domain_works}</div>}
                  {f.ai_disclosure && <div style={{ marginTop: 6 }}><strong>AI disclosure</strong>{'\n'}{f.ai_disclosure}</div>}
                </td></tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RankingsTab({ apiJson, onDataChanged }) {
  const [rank, setRank] = useState(null)       // { films, overall }
  const [pool, setPool] = useState(null)       // { exists, films, judges }
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [count, setCount] = useState('')
  const [preview, setPreview] = useState(null) // ok preview, or { blocked: {...} }
  const [confirming, setConfirming] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [openId, setOpenId] = useState(null)

  async function load() {
    setError('')
    const [r, p] = await Promise.all([apiJson('/api/admin/rankings'), apiJson('/api/admin/judges-pool')])
    if (r.ok && p.ok) {
      setRank(r.data); setPool(p.data)
      setCount((c) => c || String(Math.min(20, r.data.films.length || 20)))
    } else setError((!r.ok ? r.data?.error : p.data?.error) || 'Could not load the rankings')
  }
  useEffect(() => { load() }, [])

  async function runPreview(n = count) {
    setMsg(''); setConfirming(false); setPreview(null)
    const { ok, status, data } = await apiJson(`/api/admin/judges-pool/preview?count=${encodeURIComponent(n)}`)
    if (ok) setPreview(data)
    else if (status === 409) setPreview({ blocked: data })
    else setMsg(`Error: ${data?.error || 'Could not preview'}`)
  }

  async function confirmPool() {
    setBusy(true); setMsg('')
    const { ok, data } = await apiJson('/api/admin/judges-pool', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ count: Number(count) }),
    })
    setBusy(false); setConfirming(false)
    if (!ok) { setMsg(`Error: ${data?.error || 'Could not set the pool'}`); return }
    setMsg(`The judges' pool is set: ${data.count} films, given to ${data.judges} judge${data.judges === 1 ? '' : 's'}.`)
    setPreview(null)
    await load(); onDataChanged()
  }

  async function assignAgain() {
    setMsg('')
    const { ok, data } = await apiJson('/api/admin/judges-pool/assign', { method: 'POST' })
    setMsg(ok ? `Done: ${data.assigned} new film${data.assigned === 1 ? '' : 's'} given to ${data.judges} judge${data.judges === 1 ? '' : 's'}.` : `Error: ${data?.error || 'Failed'}`)
    await load()
  }

  async function clearPool() {
    setBusy(true); setMsg('')
    const { ok, data } = await apiJson('/api/admin/judges-pool', { method: 'DELETE' })
    setBusy(false); setClearing(false)
    setMsg(ok ? 'The judges\' pool was cleared.' : `Error: ${data?.error || 'Could not clear the pool'}`)
    await load(); onDataChanged()
  }

  if (!rank || !pool) return error ? <div style={{ color: 'var(--danger)' }}>{error}</div> : <p style={{ color: 'var(--muted)' }}>Loading…</p>

  const o = rank.overall
  const blocked = preview?.blocked

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, maxWidth: 800 }}>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>Judges' pool</div>
        {msg && <div style={{ fontSize: 13, marginBottom: 8, color: msg.startsWith('Error') ? 'var(--danger)' : 'var(--ok)' }}>{msg}</div>}

        {pool.exists ? (
          <>
            <div style={{ fontSize: 13, marginBottom: 8 }}>
              {pool.films.length} films are in the pool. Every judge rates all of them and never sees any scores.
            </div>
            <table className="grid-table" style={{ tableLayout: 'auto', fontSize: 13, marginBottom: 8 }}>
              <thead><tr><th>judge</th><th>films</th><th>not opened</th><th>opened</th><th>submitted</th></tr></thead>
              <tbody>
                {pool.judges.map((j) => <tr key={j.id}><td style={{ wordBreak: 'break-all' }}>{j.email}</td><td>{j.films}</td><td>{j.assigned}</td><td>{j.seen}</td><td>{j.rated}</td></tr>)}
                {pool.judges.length === 0 && <tr><td colSpan={5} style={{ color: 'var(--warn)' }}>No user has the judge role yet (Users tab).</td></tr>}
              </tbody>
            </table>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <button onClick={assignAgain}>Give the pool to all judges again</button>
              {!clearing
                ? <button style={{ color: 'var(--danger)' }} onClick={() => setClearing(true)}>Clear the pool…</button>
                : <span style={{ fontSize: 13 }}>Clear the pool and the judges' unrated films?{' '}
                    <button onClick={clearPool} disabled={busy} style={{ color: 'var(--danger)' }}>Yes, clear</button>{' '}
                    <button onClick={() => setClearing(false)}>Cancel</button></span>}
            </div>
          </>
        ) : (
          <>
            <div style={{ fontSize: 13, color: 'var(--muted-2)', marginBottom: 8 }}>
              The top films by the reviewers' average score become the judges' pool. Preview the list first; nothing is applied until you confirm.
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <label style={{ fontSize: 13 }}>Number of films{' '}
                <input type="number" min="1" max={rank.films.length} value={count} onChange={(e) => { setCount(e.target.value); setPreview(null) }} style={{ width: 70 }} />
              </label>
              <button onClick={() => runPreview()} disabled={!count}>Preview</button>
            </div>

            {blocked && (
              <div role="status" style={{ marginTop: 10, border: '1px solid var(--warn-border)', background: 'var(--warn-bg)', borderRadius: 6, padding: '8px 10px', fontSize: 13 }}>
                {blocked.error}
                {blocked.missing && blocked.missing.length > 0 && (
                  <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                    {blocked.missing.map((m) => <li key={m.identifier}>{m.title}: {m.rated} of {m.needed} reviews submitted</li>)}
                  </ul>
                )}
              </div>
            )}

            {preview && !blocked && (
              <div style={{ marginTop: 10 }}>
                {!preview.valid && (
                  <div role="alert" style={{ marginBottom: 8, border: '1px solid var(--danger-border)', background: 'var(--danger-bg)', borderRadius: 6, padding: '8px 10px', fontSize: 13 }}>
                    {preview.tie.message} It can't be confirmed. Valid numbers nearby:{' '}
                    {[preview.tie.nearest_valid_counts.lower, preview.tie.nearest_valid_counts.higher].filter((n) => n !== null).map((n, i) => (
                      <button key={n} style={{ fontSize: 12, marginRight: 6 }} onClick={() => { setCount(String(n)); runPreview(n) }}>{n}</button>
                    ))}
                    {preview.tie.nearest_valid_counts.lower === null && preview.tie.nearest_valid_counts.higher === null && 'none'}
                  </div>
                )}
                <div style={{ fontSize: 13, marginBottom: 4 }}>The {preview.count} highest-scoring films:</div>
                <RankingTable films={preview.films} openId={openId} setOpenId={setOpenId} />
                {preview.valid && (
                  <div style={{ marginTop: 10 }}>
                    {!confirming
                      ? <button className="btn-primary" onClick={() => setConfirming(true)}>Confirm judges' pool of {preview.count} films…</button>
                      : <div style={{ fontSize: 13 }}>Make these {preview.count} films the judges' pool and give them to every judge?{' '}
                          <button className="btn-primary" onClick={confirmPool} disabled={busy}>{busy ? 'Working…' : 'Yes, confirm'}</button>{' '}
                          <button onClick={() => setConfirming(false)} disabled={busy}>Cancel</button></div>}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>

      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 6, flexWrap: 'wrap' }}>
          <span style={{ fontWeight: 600 }}>All films by average score</span>
          <span style={{ fontSize: 13, color: 'var(--muted-2)' }}>{o.fully_reviewed} of {o.films} fully reviewed</span>
          <a href="/api/admin/rankings.csv" style={{ fontSize: 13 }}>⬇ Download rankings.csv</a>
          <button onClick={load} style={{ fontSize: 12 }}>↻ Update</button>
        </div>
        {rank.films.length === 0 ? <p style={{ color: 'var(--muted)', margin: 0 }}>No films yet.</p> : <RankingTable films={rank.films} openId={openId} setOpenId={setOpenId} />}
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
    border: '1px solid var(--border-strong)',
    borderBottom: tab === t ? '1px solid var(--surface)' : '1px solid var(--border-strong)',
    background: tab === t ? 'var(--surface)' : 'var(--surface-tab)',
    marginBottom: -1,
    fontWeight: tab === t ? 600 : 400,
    borderRadius: '6px 6px 0 0',
  })

  const cols = rows && rows.length > 0 ? Object.keys(rows[0]) : []

  return (
    <div style={{ marginTop: 12, border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 4, padding: '10px 12px 0', background: 'var(--surface-alt)', borderBottom: '1px solid var(--border)' }}>
        <span style={{ fontWeight: 700, alignSelf: 'center', marginRight: 8 }}>Admin</span>
        {['actions', 'import', 'users', 'reviews', 'rankings', 'db', 'backup'].map(t => (
          <button key={t} style={tabStyle(t)} onClick={() => setTab(t)}>
            {{ actions: 'Actions', import: 'Import', users: 'Users', reviews: 'Reviews', rankings: 'Rankings', db: 'DB Browser', backup: 'Backup' }[t]}
          </button>
        ))}
      </div>

      <div style={{ padding: 14 }}>

        {/* ── Reviews ── */}
        {tab === 'reviews' && <ReviewsTab apiJson={apiJson} onDataChanged={onDataChanged} />}

        {/* ── Rankings ── */}
        {tab === 'rankings' && <RankingsTab apiJson={apiJson} onDataChanged={onDataChanged} />}

        {/* ── Actions ── */}
        {tab === 'actions' && (() => {
          const running = jobStatus?.state === 'running'
          return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div style={{ fontSize: 14 }}>
                Films in the database: <strong>{jobStatus ? jobStatus.film_count : '…'}</strong>
              </div>

              {jobStatus && jobStatus.state !== 'idle' && (
                <div role="status" style={{ fontSize: 13, color: jobStatus.state === 'error' ? 'var(--danger)' : running ? 'var(--muted)' : 'var(--ok)' }}>
                  {running && <progress style={{ width: 320, display: 'block', marginBottom: 6 }} {...(jobStatus.total ? { value: jobStatus.done, max: jobStatus.total } : {})} aria-label="Background job progress" />}
                  {describeJob(jobStatus)}
                </div>
              )}

              <div>
                <a href="/api/admin/ratings.csv" style={{ fontSize: 14 }}>⬇ Download ratings.csv</a>
              </div>

              <div style={{ borderTop: '1px solid var(--border-soft)', paddingTop: 12 }}>
                <div style={{ fontWeight: 600, marginBottom: 6 }}>Danger zone</div>
                {!emptyOpen ? (
                  <button onClick={() => { setEmptyOpen(true); setEmptyMsg('') }} disabled={running} style={{ color: 'var(--danger)' }}>
                    Empty film database…
                  </button>
                ) : (
                  <div style={{ border: '1px solid var(--danger-border)', background: 'var(--danger-bg)', borderRadius: 8, padding: 12, maxWidth: 520 }}>
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
                        style={{ color: 'var(--danger)' }}
                      >
                        {emptying ? 'Emptying…' : 'Empty database'}
                      </button>
                      <button onClick={() => { setEmptyOpen(false); setEmptyConfirmText('') }} disabled={emptying}>Cancel</button>
                    </div>
                  </div>
                )}
                {emptyMsg && (
                  <div style={{ marginTop: 8, fontSize: 13, color: emptyMsg.startsWith('Error') ? 'var(--danger)' : 'var(--ok)' }}>{emptyMsg}</div>
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
              <p style={{ margin: 0, fontSize: 13, color: 'var(--muted-2)' }}>
                Add films from a spreadsheet exported as <strong>CSV</strong>.
                Only rows with an <strong>archive.org</strong> link are imported; other rows (YouTube links, free text, blanks) are skipped. If you map the <strong>Eligible</strong> column, only rows that say <em>yes</em> are imported; <em>no</em>, blank and unclear rows are skipped and listed.
              </p>

              {running && <div role="status" style={{ fontSize: 13, color: 'var(--muted)' }}>{describeJob(jobStatus)}</div>}

              <div>
                <input type="file" accept=".csv,text/csv" onChange={handleImportFile} disabled={impBusy} />
                {impFile && <span style={{ marginLeft: 8, fontSize: 13 }}>{impFile} — {impPreview.row_count} rows</span>}
              </div>
              {impMsg && <div style={{ fontSize: 13, color: impMsg.startsWith('Error') ? 'var(--danger)' : 'var(--ok)' }}>{impMsg}</div>}

              {impPreview && (
                <>
                  <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
                    <div style={{ fontWeight: 600, marginBottom: 8 }}>Which column is which?</div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '8px 12px', alignItems: 'center', fontSize: 14 }}>
                      {IMPORT_FIELDS.map(([key, label, required]) => (
                        <Fragment key={key}>
                          <label>{label}{required && <span style={{ color: 'var(--danger)' }}> *</span>}</label>{select(key, !required)}
                        </Fragment>
                      ))}
                    </div>
                  </div>

                  <div style={{ overflowX: 'auto' }}>
                    <div style={{ fontSize: 13, color: 'var(--muted-2)', marginBottom: 4 }}>First rows of your file:</div>
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
                    <div style={{ border: '1px solid var(--info-border)', background: 'var(--info-bg)', borderRadius: 8, padding: 12, fontSize: 14 }}>
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
                              {f.exists && <span style={{ color: 'var(--warn)' }}> (already in the database)</span>}
                            </li>
                          ))}
                        </ul>
                      )}

                      {sum.ineligible_in_database > 0 && (
                        <div style={{ marginTop: 8, padding: '8px 10px', border: '1px solid var(--warn-border)', background: 'var(--warn-bg)', borderRadius: 6, fontSize: 13 }}>
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
                        <fieldset style={{ marginTop: 10, border: '1px solid var(--warn-border)', background: 'var(--warn-bg)', borderRadius: 6 }}>
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
                      {needChoice && <div style={{ fontSize: 12, color: 'var(--warn)', marginTop: 6 }}>Choose what to do with the existing films to continue.</div>}
                    </div>
                  )}
                </>
              )}

              {impResult && (
                <div role="status" style={{ border: '1px solid var(--ok-border)', background: 'var(--ok-bg)', borderRadius: 8, padding: 12, fontSize: 14 }}>
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
            {dbError && <div style={{ color: 'var(--danger)', marginBottom: 8 }}>{dbError}</div>}

            {/* Table list */}
            {tables && (
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
                {Object.entries(tables).map(([t, count]) => (
                  <button
                    key={t}
                    onClick={() => { setSelTable(t); setOrderBy(''); setLimit('100'); loadRows(t, { orderBy: '', limit: '100' }) }}
                    style={{ fontWeight: selTable === t ? 700 : 400, background: selTable === t ? 'var(--selected-bg)' : '' }}
                  >
                    {t} <span style={{ fontSize: 12, color: 'var(--muted)' }}>({count})</span>
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
                ? <p style={{ color: 'var(--muted)' }}>(no rows)</p>
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
                                {row[c] === null ? <span style={{ color: 'var(--faint)' }}>NULL</span> : String(row[c])}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>{rows.length} row{rows.length !== 1 ? 's' : ''}</div>
                  </div>
                )
            )}

            {dbLoading && !rows && <p style={{ color: 'var(--muted)' }}>Loading…</p>}
          </div>
        )}

        {/* ── Users ── */}
        {tab === 'users' && (
          <div>
            <form onSubmit={sendInvite} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, marginBottom: 14, maxWidth: 640 }}>
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
              <div style={{ fontSize: 12, color: 'var(--muted-2)', marginTop: 6 }}>
                The app sends no email: you get a personal sign-in link to pass on. The person can use it as often as they like until it expires.
              </div>
            </form>

            {newLink && (
              <div role="status" style={{ border: '1px solid var(--ok-border)', background: 'var(--ok-bg)', borderRadius: 8, padding: 12, marginBottom: 14, maxWidth: 760 }}>
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

            {actionMsg && <div style={{ marginBottom: 8, color: actionMsg.startsWith('Error') ? 'var(--danger)' : 'var(--ok)', fontSize: 13 }}>{actionMsg}</div>}
            {usersError && <div style={{ color: 'var(--danger)', marginBottom: 8 }}>{usersError}</div>}
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
                          <div style={{ color: u.link?.state === 'active' ? 'var(--ok)' : 'var(--warn)', marginBottom: 4 }}>{describeLink(u.link)}</div>
                          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                            <input
                              type="date" value={expiryFor(u)} min={dateInDays(1)}
                              onChange={(e) => setRowExpiry({ ...rowExpiry, [u.id]: e.target.value })}
                              aria-label={`Expiry date for ${u.email}`}
                            />
                            <button style={{ fontSize: 12 }} onClick={() => issueLink(u)}>New link</button>
                            {u.link && <button style={{ fontSize: 12 }} onClick={() => changeExpiry(u)}>Set expiry</button>}
                            {u.link && <button style={{ fontSize: 12, color: 'var(--danger)' }} onClick={() => cancelLink(u)}>Cancel link</button>}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>
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
              <p style={{ margin: '0 0 8px', fontSize: 13, color: 'var(--muted-2)' }}>
                Exports all tables (users, films, assignments, ratings, etc.) as a single
                versioned JSON file. The filename includes the UTC timestamp.
              </p>
              <button onClick={downloadBackup}>⬇ Download backup</button>
              {backupStatus && (
                <div style={{ marginTop: 8, fontSize: 13, color: backupStatus.startsWith('Error') ? 'var(--danger)' : 'var(--ok)' }}>
                  {backupStatus}
                </div>
              )}
            </div>

            <hr style={{ border: 0, borderTop: '1px solid var(--border-soft)' }} />

            {/* Restore */}
            <div>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>Restore from backup</div>
              <p style={{ margin: '0 0 8px', fontSize: 13, color: 'var(--muted-2)' }}>
                Select a <code>.json</code> backup file. You'll be asked to confirm before
                any data is overwritten.
              </p>
              <input type="file" accept=".json,application/json" onChange={handleRestoreFile} />

              {restorePending && (
                <div style={{ marginTop: 12, padding: 12, border: '1px solid var(--warn-strong-border)', borderRadius: 8, background: 'var(--warn-bg)' }}>
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
                  <p style={{ fontSize: 13, color: 'var(--danger)', margin: '0 0 10px' }}>
                    This will <strong>permanently replace</strong> all existing rows in every
                    table included in the backup. This cannot be undone.
                  </p>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button
                      onClick={confirmRestore}
                      disabled={restoring}
                      style={{ background: 'var(--danger-solid)', color: 'var(--on-accent)', border: 'none', padding: '6px 14px', borderRadius: 4, cursor: 'pointer' }}
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
                <div style={{ marginTop: 8, fontSize: 13, color: restoreStatus.startsWith('Error') ? 'var(--danger)' : 'var(--ok)' }}>
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
// A judge's own ranked list (shown after their last film, and from "My ranked films")
// ---------------------------------------------------------------------------

function ResultsScreen({ results, categories, onBack }) {
  return (
    <div style={{ marginTop: 14 }}>
      <h3 style={{ margin: '0 0 4px' }}>Your ranked films</h3>
      <div style={{ fontSize: 14, color: 'var(--text-2)', marginBottom: 10 }}>
        {results.complete
          ? `You have rated all ${results.pool_size} films. Here is your list, highest total first.`
          : `You have rated ${results.rated} of ${results.pool_size} films so far.`}
        {' '}These are your own scores and comments; nobody else can see them here.
      </div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 10 }}>
        <a href="/api/me/results.csv" style={{ fontSize: 14 }}>⬇ Download my ratings (CSV)</a>
        {onBack && <button onClick={onBack}>Back to rating</button>}
      </div>
      {results.films.length === 0 ? <p style={{ color: 'var(--muted)' }}>You haven't rated any of these films yet.</p> : (
        <div style={{ overflowX: 'auto' }}>
          <table className="grid-table" style={{ tableLayout: 'auto', fontSize: 14 }}>
            <thead>
              <tr>
                <th>rank</th><th>film</th>
                {categories.map((c) => <th key={c.key}>{c.label}</th>)}
                <th>total</th><th>your comment</th>
              </tr>
            </thead>
            <tbody>
              {results.films.map((f) => (
                <tr key={f.identifier}>
                  <td>{f.rank}</td>
                  <td><a href={f.archiveUrl} target="_blank" rel="noreferrer">{f.title}</a>{f.creator && <span style={{ color: 'var(--muted)' }}> by {f.creator}</span>}</td>
                  {categories.map((c) => <td key={c.key}>{f.scores[c.key]}</td>)}
                  <td><strong>{f.total}</strong></td>
                  <td style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxWidth: 360 }}>{f.comment}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Light / dark mode: a Moon (switch to dark) / Sun (switch to light) button. The choice is
// remembered in this browser; the first visit follows the device setting (see index.html).
// ---------------------------------------------------------------------------

function currentTheme() {
  return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'
}

function ThemeToggle() {
  const [theme, setTheme] = useState(currentTheme)
  function toggle() {
    const next = theme === 'dark' ? 'light' : 'dark'
    document.documentElement.setAttribute('data-theme', next)
    try { localStorage.setItem('theme', next) } catch { /* private mode: the choice just isn't remembered */ }
    setTheme(next)
  }
  const dark = theme === 'dark'
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
      title={dark ? 'Switch to light mode' : 'Switch to dark mode'}
      style={{ fontSize: 18, lineHeight: 1, padding: '4px 8px' }}
    >
      {dark ? '☀️' : '🌙'}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Which page a reviewer or judge is on. The page is in the URL fragment so every film has a
// real link (#/film/<identifier>) and the browser's back button works:
//   #/ (or nothing)  rate: the next film        #/films    the list of my films
//   #/film/<id>      one particular film         #/results  a judge's ranked list
// ---------------------------------------------------------------------------

function parseRoute() {
  const h = window.location.hash.replace(/^#\/?/, '')
  if (h === 'films') return { view: 'films' }
  if (h === 'results') return { view: 'results' }
  if (h.startsWith('film/') && h.length > 5) {
    try { return { view: 'film', id: decodeURIComponent(h.slice(5)) } } catch { /* fall through */ }
  }
  return { view: 'rate' }
}

// What the list calls each assignment status.
const MY_STATUS_LABEL = { assigned: 'unseen', seen: 'seen', rated: 'rated' }

function MyFilmsScreen({ films }) {
  const [onlyOpen, setOnlyOpen] = useState(false)
  const count = (st) => films.filter((f) => f.status === st).length
  const shown = onlyOpen ? films.filter((f) => f.status !== 'rated') : films
  return (
    <div style={{ marginTop: 14 }}>
      <h3 style={{ margin: '0 0 4px' }}>My films</h3>
      <div style={{ fontSize: 14, color: 'var(--text-2)', marginBottom: 8 }}>
        {films.length} film{films.length === 1 ? '' : 's'}: {count('rated')} rated, {count('seen')} seen, {count('assigned')} unseen.
        Open any film to rate it. <a href="#/">Rate the next film</a>
      </div>
      {films.length === 0 ? <p style={{ color: 'var(--muted)' }}>No films have been assigned to you yet.</p> : (
        <>
          <label style={{ fontSize: 13, display: 'block', marginBottom: 8 }}>
            <input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} /> Only films I haven't rated
          </label>
          <table className="grid-table" style={{ tableLayout: 'auto', fontSize: 15, maxWidth: 760 }}>
            <thead><tr><th>film</th><th>status</th></tr></thead>
            <tbody>
              {shown.map((f) => (
                <tr key={f.identifier}>
                  <td><a href={`#/film/${encodeURIComponent(f.identifier)}`}>{f.title}</a>{f.creator && <span style={{ color: 'var(--muted)' }}> by {f.creator}</span>}</td>
                  <td><StatusChip status={f.status} label={MY_STATUS_LABEL[f.status]} /></td>
                </tr>
              ))}
              {shown.length === 0 && <tr><td colSpan={2} style={{ color: 'var(--muted)' }}>You have rated every film.</td></tr>}
            </tbody>
          </table>
        </>
      )}
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
  const [confirmOpen, setConfirmOpen] = useState(false)   // "Are you sure?" before a final submit
  const [submitting, setSubmitting] = useState(false)     // submit sent, next film not shown yet
  const [flash, setFlash] = useState('')                  // one-off message above the film
  const [results, setResults] = useState(null)            // a judge's own ranked list
  const [myFilms, setMyFilms] = useState(null)            // the list on the "My films" page
  const [route, setRoute] = useState(parseRoute)
  const loadedFor = useRef('')                            // "<user id>|<page>" whose data is on screen

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
    setFlash('')
    setResults(null)
    setMyFilms(null)
    loadedFor.current = ''
  }

  async function loadResults() {
    const { ok, data } = await apiJson('/api/me/results')
    if (ok) { setResults(data); return data }
    return null
  }

  // Go to another page: a new history entry (so Back works), or replace the current one.
  function navigate(hash, { replace = false } = {}) {
    if (replace) {
      window.history.replaceState({}, '', `/${hash}`)
      setRoute(parseRoute())
    } else {
      window.location.hash = hash   // fires hashchange, which updates the route
    }
  }

  async function loadMyFilms() {
    const { ok, status, data } = await apiJson('/api/me/films')
    if (ok) { setMyFilms({ films: data.films }); return }
    // Say what went wrong; an empty list would wrongly claim that nothing is assigned.
    setMyFilms({
      error: status === 403
        ? 'Your account does not have the reviewer or judge role, so it has no films. Ask an administrator to give you one.'
        : `Could not load your films (${status || 'no response'}${data?.error ? `: ${data.error}` : ''}). If this keeps happening, the server may need restarting.`,
    })
  }

  // One particular film, opened from the list (opening it marks it seen).
  async function loadFilm(identifier) {
    setError(''); setNotice(null); setSubmitError('')
    const { ok, data } = await apiJson(`/api/films/${encodeURIComponent(identifier)}`)
    if (ok) {
      setFilm(data); setScores({}); setComment('')
      window.scrollTo(0, 0)
    } else {
      setFilm(null)
      setError(data?.error || 'Could not load that film')
    }
  }

  async function loadCategories() {
    const { ok, data } = await apiJson('/api/categories')
    setCategories(ok && Array.isArray(data) ? data : [])
  }

  async function loadNextFilm() {
    if (me) loadedFor.current = `${me.id}|rate`
    setError('')
    setNotice(null)
    setSubmitError('')
    const { ok, data } = await apiJson('/api/films/next')
    if (ok) {
      // Film, scores and comment change together, in one render: the old film and its
      // scores stay on screen until the next film has loaded (no flash of cleared scores).
      setFilm(data)
      setScores({})
      setComment('')
      window.scrollTo(0, 0)
    } else {
      setFilm(null)
      if (NOTICE_CODES.includes(data?.code)) {
        setNotice({ code: data.code, text: data.error })
      } else {
        setError(data?.error || 'Could not load the next film')
      }
    }
  }

  // Called after the person confirmed. The scores stay visible (buttons disabled) until the
  // next film has loaded.
  async function submit() {
    if (!film?.identifier || submitting) return
    setSubmitError(''); setFlash('')
    setSubmitting(true)
    const { ok, status, data } = await apiJson(`/api/films/${encodeURIComponent(film.identifier)}/ratings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scores, comment })
    })

    if (!ok && status !== 409) {
      setSubmitting(false); setConfirmOpen(false)
      setSubmitError(data?.error || 'Submit failed')
      return
    }

    await loadNextFilm()
    if (parseRoute().view !== 'rate') navigate('', { replace: true })   // opened from the list: carry on with the next film
    setConfirmOpen(false)
    setSubmitting(false)
    if (status === 409) setFlash('That film had already been submitted (scores can’t be changed). Here is your next film.')
  }

  useEffect(() => {
    if (window.location.pathname === '/signin' && window.location.hash) {
      window.history.replaceState({}, '', '/signin')
    }
    loadMe()
  }, [])

  // Pasting a link into a tab that already shows /signin only changes the fragment (no reload).
  useEffect(() => {
    const onHash = () => {
      if (window.location.pathname === '/signin') {
        if (window.location.hash.length > 1) {
          setSigninToken(window.location.hash.slice(1))
          setSigninError('')
          window.history.replaceState({}, '', '/signin')
        }
      } else {
        setRoute(parseRoute())
      }
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
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

  // Load what the current page needs, when the person or the page changes. (After a submit the next
  // film is loaded directly and `loadedFor` already says so, so nothing is fetched twice.)
  useEffect(() => {
    if (!me) return
    const page = route.view === 'film' ? `film:${route.id}` : route.view
    const key = `${me.id}|${page}`
    if (loadedFor.current === key) return
    const newPerson = !loadedFor.current.startsWith(`${me.id}|`)
    loadedFor.current = key
    if (newPerson) {
      // A different person (e.g. after opening another sign-in link): drop everything of the last one.
      setScores({}); setComment(''); setSubmitError(''); setResults(null); setMyFilms(null); setConfirmOpen(false)
    }
    setFilm(null); setNotice(null); setError(''); setFlash('')
    setLoading(true)
    const run = {
      rate: () => loadNextFilm(),
      film: () => loadFilm(route.id),
      films: () => loadMyFilms(),
      results: () => loadResults(),
    }[route.view]
    Promise.all([newPerson ? loadCategories() : null, run()]).finally(() => setLoading(false))
  }, [me?.id, route.view, route.id])

  // After a judge's last film, go straight to their ranked list (only once a judges' pool exists).
  useEffect(() => {
    if (notice?.code === 'all_rated' && me?.is_judge && route.view === 'rate') {
      loadResults().then((d) => { if (d && d.pool_size > 0) navigate('#/results', { replace: true }) })
    }
  }, [notice?.code, me?.is_judge])

  const inRateView = route.view === 'rate' || route.view === 'film'
  const canRate = !!me && (me.is_reviewer || me.is_judge)
  // A film the person has already rated opens read-only, showing their own submitted rating.
  const readOnly = film?.status === 'rated'
  const shownScores = readOnly ? (film.rating?.scores || {}) : scores
  const shownComment = readOnly ? (film.rating?.comment || '') : comment
  const allChosen = !!film?.identifier && !readOnly && categories.length > 0 && categories.every((c) => Number.isInteger(scores[c.key]))
  const total = categories.reduce((sum, c) => sum + (shownScores[c.key] || 0), 0)

  // Also when someone is already signed in: opening a new link means they want to switch accounts.
  if (window.location.pathname === '/signin' && (!me || signinToken)) {
    return (
      <div style={{ padding: 20, maxWidth: 520 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}><h2>IA Film Rater</h2><ThemeToggle /></div>
        {signinToken ? (
          <>
            <p style={{ marginTop: 0 }}>You've been invited to rate films. Press the button to sign in on this device.</p>
            {signinError ? <div role="alert" style={{ margin: '12px 0', color: 'var(--danger)' }}>{signinError}</div> : null}
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
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}><h2>IA Film Rater</h2><ThemeToggle /></div>
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
        .grid-table th { text-align: left; font-weight: 600; border-bottom: 2px solid var(--border); padding: 10px 8px; }
        .grid-table td { border-bottom: 1px solid var(--border-soft); padding: 10px 8px; vertical-align: middle; }
        .btn-primary { padding: 10px 14px; }
        .btn-primary[disabled] { opacity: 0.5; cursor: not-allowed; }
        .topbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
        .film-panel { margin-top: 14px; max-width: 900px; }
        .film-title { margin: 0 0 4px; font-size: 24px; }
        .film-section { margin: 10px 0; padding: 10px 12px; border: 1px solid var(--border-soft); border-radius: 10px; background: var(--surface-alt); color: var(--text); white-space: pre-wrap; word-break: break-word; overflow-wrap: break-word; }
        .film-section h4 { margin: 0 0 4px; font-size: 14px; }
        .player { width: 100%; aspect-ratio: 16/9; border: 0; margin: 12px 0 16px; }
        .category { margin: 18px 0; }
        .category h4 { margin: 0; font-size: 17px; }
        .category .cat-desc { font-weight: 700; margin: 2px 0 8px; }
        .scale { display: flex; flex-wrap: wrap; gap: 6px; }
        .scale button { min-width: 42px; padding: 8px 0; font-size: 16px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface); color: var(--text); cursor: pointer; }
        .scale button.chosen { background: var(--accent); color: var(--on-accent); border-color: var(--accent); font-weight: 700; }
        .scale button[disabled] { cursor: not-allowed; opacity: 0.7; }
        .anchors { font-size: 13px; color: var(--muted-2); margin-top: 6px; }
        .total { font-size: 18px; margin: 14px 0 4px; min-height: 28px; }
        .comment-head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; margin-top: 20px; }
        .comment-head h4 { margin: 0; font-size: 17px; }
        .comment-head small { color: var(--muted-2); }
        .modal-backdrop { position: fixed; inset: 0; background: var(--overlay); display: flex; align-items: center; justify-content: center; padding: 16px; z-index: 1000; }
        .modal { background: var(--surface); color: var(--text); border-radius: 10px; padding: 18px; width: 100%; max-width: 440px; box-shadow: 0 10px 30px var(--shadow); }
        @media (max-width: 768px) {
          .grid-table, .grid-table thead, .grid-table tbody, .grid-table th, .grid-table td, .grid-table tr { display: block; }
          .grid-table thead { display: none; }
          .grid-table tr { border: 1px solid var(--border-soft); border-radius: 10px; margin-bottom: 10px; padding: 10px; }
          .grid-table td { border: 0; padding: 6px 0; }
        }
      `}</style>

      <div className="topbar">
        <h2 style={{ margin: 0 }}>IA Film Rater</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <ThemeToggle />
          <span style={{ fontSize: 14, color: 'var(--text-2)' }}>{me.email}</span>
          {canRate && <button onClick={() => navigate('')} disabled={route.view === 'rate'}>Rate</button>}
          {canRate && <button onClick={() => navigate('#/films')} disabled={route.view === 'films'}>My films</button>}
          {me.is_judge && <button onClick={() => navigate('#/results')} disabled={route.view === 'results'}>My ranked films</button>}
          <button onClick={logout}>Logout</button>
        </div>
      </div>

      {me?.is_admin ? (
        <AdminPanel apiJson={apiJson} onDataChanged={() => { loadedFor.current = ''; if (parseRoute().view === 'rate') loadNextFilm() }} meId={me.id} />
      ) : null}

      {route.view === 'results' && results ? (
        <ResultsScreen results={results} categories={categories} onBack={() => navigate('')} />
      ) : null}
      {route.view === 'films' && myFilms ? (
        myFilms.error
          ? <div role="alert" style={{ marginTop: 14, color: 'var(--danger)' }}>{myFilms.error}</div>
          : <MyFilmsScreen films={myFilms.films} />
      ) : null}

      {loading ? <p>Loading…</p> : null}
      {error ? (
        <div role="alert" style={{ marginTop: 12, color: 'var(--danger)' }}>
          {error}{route.view === 'film' && <> <a href="#/films">Back to my films</a></>}
        </div>
      ) : null}
      {notice && inRateView ? (
        <div role="status" style={{ marginTop: 12, padding: '12px 14px', border: '1px solid var(--info-border)', background: 'var(--info-bg)', borderRadius: 8, maxWidth: 620 }}>
          {notice.text}
          {me?.is_admin && notice.code === 'no_films' ? <div style={{ marginTop: 6, fontSize: 13, color: 'var(--muted-2)' }}>As an admin, use Admin → Import.</div> : null}
        </div>
      ) : null}

      {flash && inRateView ? <div role="status" style={{ marginTop: 12, color: 'var(--chip-seen-fg)' }}>{flash}</div> : null}

      {film && inRateView ? (
        <div className="film-panel">
          <h3 className="film-title">
            <a href={film.archiveUrl} target="_blank" rel="noreferrer">{film.title}</a>
            {film.creator ? <span style={{ fontWeight: 400 }}> by {film.creator}</span> : null}
          </h3>

          {film.description ? (
            <div className="film-section">{linkifyText(film.description)}</div>
          ) : null}
          {film.publicDomainWorks ? (
            <div className="film-section"><h4>List of public domain works used</h4>{linkifyText(film.publicDomainWorks)}</div>
          ) : null}
          {film.aiDisclosure ? (
            <div className="film-section"><h4>AI disclosure</h4>{linkifyText(film.aiDisclosure)}</div>
          ) : null}

          {film.embedUrl ? (
            <iframe className="player" src={film.embedUrl} allowFullScreen title={film.title} />
          ) : null}

          {readOnly ? (
            <div role="status" style={{ margin: '10px 0', padding: '10px 14px', border: '1px solid var(--ok-border)', background: 'var(--ok-bg)', borderRadius: 8 }}>
              You rated this film. Scores can’t be changed.{' '}
              <a href="#/films">Back to my films</a> · <a href="#/">Rate the next film</a>
            </div>
          ) : null}

          {categories.map((c) => (
            <div className="category" key={c.key}>
              <h4>{c.label}</h4>
              <div className="cat-desc">{c.description}</div>
              <div className="scale" role="group" aria-label={`Score for ${c.label}`}>
                {Array.from({ length: c.max - c.min + 1 }, (_, i) => c.min + i).map((n) => (
                  <button
                    key={n}
                    type="button"
                    className={shownScores[c.key] === n ? 'chosen' : ''}
                    aria-pressed={shownScores[c.key] === n}
                    disabled={submitting || readOnly}
                    onClick={() => setScores((prev) => ({ ...prev, [c.key]: n }))}
                  >
                    {n}
                  </button>
                ))}
              </div>
              <div className="anchors">
                {Object.entries(c.anchors || {}).map(([n, label]) => `${label} (${n})`).join(', ')}
              </div>
            </div>
          ))}

          <div className="total" aria-live="polite">
            {allChosen || (readOnly && categories.every((c) => Number.isInteger(shownScores[c.key])))
              ? <>Your score: <strong>{categories.map((c) => shownScores[c.key]).join(' + ')} = {total}</strong></>
              : <span style={{ color: 'var(--muted)', fontSize: 14 }}>Choose a score in every category to see your total.</span>}
          </div>

          <div className="comment-head">
            <h4>Comments on Film</h4>
            <small>(May be used in presentation)</small>
          </div>
          <textarea
            value={shownComment}
            onChange={(e) => setComment(e.target.value.slice(0, 1000))}
            rows={5}
            disabled={submitting}
            readOnly={readOnly}
            aria-label="Comments on Film"
            style={{ display: 'block', width: '100%', boxSizing: 'border-box', font: 'inherit', padding: 8, marginTop: 6 }}
          />
          {!readOnly && <div style={{ fontSize: 12, color: 'var(--muted)' }}>{comment.length} / 1000</div>}

          {!readOnly && (
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 14 }}>
              <button className="btn-primary" onClick={() => setConfirmOpen(true)} disabled={!allChosen || submitting}>
                {submitting ? 'Loading next film…' : 'Submit & Next'}
              </button>
            </div>
          )}

          {submitError ? <div role="alert" style={{ marginTop: 10, color: 'var(--danger)' }}>{submitError}</div> : null}
        </div>
      ) : null}

      {confirmOpen ? (
        <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !submitting) setConfirmOpen(false) }}>
          <div className="modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
            <h3 id="confirm-title" style={{ marginTop: 0 }}>Are you sure?</h3>
            <p style={{ margin: '0 0 6px' }}>Scores cannot be changed after you submit.</p>
            <p style={{ margin: '0 0 14px' }}><strong>{categories.map((c) => scores[c.key]).join(' + ')} = {total}</strong></p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button onClick={() => setConfirmOpen(false)} disabled={submitting}>Go back</button>
              <button className="btn-primary" onClick={submit} disabled={submitting} autoFocus>
                {submitting ? 'Submitting…' : 'Yes, submit'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
