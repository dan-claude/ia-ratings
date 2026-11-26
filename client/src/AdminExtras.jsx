// Admin pieces that stand on their own: the Overview page and the controls for the actions
// that can't be undone. They get `apiJson` (fetch + JSON) from the app.
import { useEffect, useState } from 'react'

const STAGE_BADGE = {
  done: { label: 'done', style: { background: 'var(--ok-bg)', color: 'var(--ok)', border: '1px solid var(--ok-border)' } },
  now: { label: 'now', style: { background: 'var(--info-bg)', color: 'var(--accent)', border: '1px solid var(--info-border)' } },
  locked: { label: 'locked', style: { background: 'var(--surface-alt)', color: 'var(--muted)', border: '1px solid var(--border)' } },
}

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`

export function OverviewTab({ apiJson }) {
  const [d, setD] = useState(null)
  const [error, setError] = useState('')

  async function load() {
    setError('')
    const [prog, users, pool, job] = await Promise.all([
      apiJson('/api/admin/progress'), apiJson('/api/admin/users'),
      apiJson('/api/admin/judges-pool'), apiJson('/api/admin/jobs/status'),
    ])
    if (prog.ok && users.ok && pool.ok && job.ok) setD({ prog: prog.data, users: users.data, pool: pool.data, job: job.data })
    else setError('Could not load the overview.')
  }
  useEffect(() => { load() }, [])

  if (!d) return error ? <div role="alert" style={{ color: 'var(--danger)' }}>{error}</div> : <p style={{ color: 'var(--muted)' }}>Loading…</p>

  const o = d.prog.overall
  const films = d.job.film_count
  const reviewers = d.users.filter((u) => u.is_reviewer).length
  const judges = d.users.filter((u) => u.is_judge).length
  const admins = d.users.filter((u) => u.is_admin).length
  const poolSize = d.pool.films.length
  const judgeRated = d.pool.judges.reduce((n, j) => n + j.rated, 0)
  const judgeTotal = d.pool.judges.length * poolSize

  const done = [
    films > 0,                                         // 1 films imported
    reviewers >= 2,                                    // 2 people invited (every film needs 2 reviewers)
    o.distributed,                                     // 3 films handed out
    o.distributed && o.needing_reviews === 0,          // 4 reviews finished
    d.pool.exists,                                     // 5 judges' pool chosen
    d.pool.exists && judgeTotal > 0 && judgeRated === judgeTotal,   // 6 judges finished
  ]
  const firstOpen = done.indexOf(false)
  const state = (i) => (done[i] ? 'done' : i === firstOpen ? 'now' : 'locked')

  const stages = [
    { title: 'Films imported', detail: films ? plural(films, 'film', 'films') : 'none yet', link: '#/admin/films' },
    { title: 'People invited', detail: `${plural(reviewers, 'reviewer', 'reviewers')}, ${plural(judges, 'judge', 'judges')}, ${plural(admins, 'admin', 'admins')}${done[1] ? '' : ' (at least 2 reviewers are needed)'}`, link: '#/admin/people' },
    { title: 'Films handed out', detail: o.distributed ? `${o.reviews_per_film} reviewers per film` : 'not yet', link: '#/admin/progress' },
    { title: 'Reviews', detail: o.distributed ? `${o.fully_reviewed} of ${o.films} films fully reviewed` : 'starts once films are handed out', bar: o.distributed ? o.fully_reviewed / Math.max(o.films, 1) : null, link: '#/admin/progress' },
    { title: "Judges' pool", detail: done[4] ? `${plural(poolSize, 'film', 'films')} chosen` : done[3] ? 'ready to choose' : `needs every film reviewed ${o.reviews_per_film} times`, link: '#/admin/rankings' },
    { title: 'Judges rate the pool', detail: done[4] ? `${judgeRated} of ${judgeTotal} ratings submitted (${plural(judges, 'judge', 'judges')})` : 'not started', bar: done[4] && judgeTotal ? judgeRated / judgeTotal : null, link: '#/admin/rankings' },
  ]

  const needing = o.needing_reviews
  const next = [
    ['Import the films', 'Load the spreadsheet of submissions.', '#/admin/films', 'Import films'],
    ['Invite the reviewers', 'At least 2 people with the reviewer role are needed to hand out films.', '#/admin/people', 'Invite people'],
    ['Hand out the films', `Give every film to ${o.reviews_per_film} reviewers.`, '#/admin/progress', 'Go to Progress'],
    ['Chase the last reviews', `${plural(needing, 'film', 'films')} still ${needing === 1 ? 'needs' : 'need'} a review. The judges' pool unlocks once every film has ${o.reviews_per_film}.`, '#/admin/progress', 'See who owes reviews'],
    ["Choose the judges' pool", 'Every film has its reviews. Preview the top films and confirm.', '#/admin/rankings', 'Open rankings and pool'],
    ['Wait for the judges', `${judgeRated} of ${judgeTotal} judge ratings are in.`, '#/admin/rankings', "See the judges' progress"],
  ][firstOpen]

  const expired = d.users.filter((u) => u.link?.state === 'expired').length
  const noRole = d.users.filter((u) => u.roles.length === 0).length
  const attention = []
  if (expired) attention.push(`${plural(expired, 'sign-in link has', 'sign-in links have')} expired`)
  if (noRole) attention.push(`${plural(noRole, 'person has', 'people have')} no role yet`)
  if (done[4] && judges === 0) attention.push("The judges' pool is set but nobody has the judge role")

  return (
    <div style={{ maxWidth: 760 }}>
      <h3 style={{ margin: '0 0 2px' }}>Overview</h3>
      <p style={{ margin: '0 0 12px', color: 'var(--muted-2)', fontSize: 14 }}>Where the contest stands, in the order things happen.</p>

      {next ? (
        <div role="status" style={{ border: '1px solid var(--info-border)', background: 'var(--info-bg)', borderRadius: 8, padding: '10px 14px', marginBottom: 14 }}>
          <div style={{ fontWeight: 600, color: 'var(--accent)' }}>Next step: {next[0]}</div>
          <div style={{ fontSize: 14, marginBottom: 6 }}>{next[1]}</div>
          <a href={next[2]}>{next[3]} →</a>
        </div>
      ) : (
        <div role="status" style={{ border: '1px solid var(--ok-border)', background: 'var(--ok-bg)', borderRadius: 8, padding: '10px 14px', marginBottom: 14 }}>
          Everything is done. Download the results under <a href="#/admin/data">Exports and safety</a>.
        </div>
      )}

      <div>
        {stages.map((st, i) => {
          const b = STAGE_BADGE[state(i)]
          return (
            <div key={st.title} style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '9px 0', borderTop: '1px solid var(--border-soft)', flexWrap: 'wrap' }}>
              <span style={{ ...b.style, borderRadius: 10, padding: '1px 9px', fontSize: 12, minWidth: 70, textAlign: 'center' }}>{i + 1} {b.label}</span>
              <a href={st.link} style={{ fontWeight: 600, minWidth: 150, color: 'var(--text)', textDecoration: 'none' }}>{st.title}</a>
              {st.bar !== null && st.bar !== undefined && <progress value={Math.round(st.bar * 100)} max={100} style={{ width: 120 }} aria-label={`${st.title} progress`} />}
              <span style={{ color: 'var(--muted-2)', fontSize: 14 }}>{st.detail}</span>
            </div>
          )
        })}
      </div>

      {attention.length > 0 && (
        <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px', marginTop: 14 }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Needs attention</div>
          {attention.map((text) => <div key={text} style={{ fontSize: 14 }}>{text} · <a href="#/admin/people">People</a></div>)}
        </div>
      )}
      <button onClick={load} style={{ marginTop: 12, fontSize: 12 }}>↻ Update</button>
    </div>
  )
}

export function DangerCard({ title, children }) {
  return (
    <div style={{ borderTop: '1px solid var(--danger-border)', padding: '10px 0' }}>
      <div style={{ fontWeight: 600 }}>{title}</div>
      {children}
    </div>
  )
}

const msgColor = (msg) => (msg.startsWith('Error') ? 'var(--danger)' : 'var(--ok)')

// Reset distribution: deletes every assignment and rating and empties the judges' pool.
export function ResetDistributionControl({ apiJson, onDataChanged }) {
  const [info, setInfo] = useState(null)
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  async function load() { const { ok, data } = await apiJson('/api/admin/progress'); if (ok) setInfo(data.overall) }
  useEffect(() => { load() }, [])
  async function reset() {
    setBusy(true); setMsg('')
    const { ok, data } = await apiJson('/api/admin/distribute/reset', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm: 'RESET' }),
    })
    setBusy(false)
    if (!ok) { setMsg(`Error: ${data?.error || 'Could not reset'}`); return }
    setMsg(`Reset: ${data.deleted.assignments} assignments and ${data.deleted.ratings} ratings deleted.`)
    setOpen(false); setText('')
    await load(); onDataChanged()
  }
  const total = info ? info.assignments.assigned + info.assignments.seen + info.assignments.rated : null
  return (
    <DangerCard title="Reset distribution">
      <div style={{ fontSize: 13, color: 'var(--muted-2)', marginBottom: 6 }}>Deletes every assignment and every rating, and clears the judges' pool, so the films can be handed out again.</div>
      {!open ? (
        <button onClick={() => { setOpen(true); setMsg('') }} disabled={!!info && !info.distributed} style={{ color: 'var(--danger)' }}>Reset distribution…</button>
      ) : (
        <div style={{ border: '1px solid var(--danger-border)', background: 'var(--surface)', borderRadius: 8, padding: 12, maxWidth: 520 }}>
          <p style={{ margin: '0 0 8px', fontSize: 13 }}>
            This deletes <strong>{total ?? 'all'} assignments and {info ? info.assignments.rated : 'all'} submitted ratings</strong>. Download a backup first.
          </p>
          <label style={{ fontSize: 13 }}>Type <code>RESET</code> to confirm:{' '}
            <input value={text} onChange={(e) => setText(e.target.value)} style={{ width: 90 }} autoComplete="off" />
          </label>
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button onClick={reset} disabled={text !== 'RESET' || busy} style={{ color: 'var(--danger)' }}>{busy ? 'Resetting…' : 'Reset distribution'}</button>
            <button onClick={() => { setOpen(false); setText('') }} disabled={busy}>Cancel</button>
          </div>
        </div>
      )}
      {info && !info.distributed && <span style={{ fontSize: 12, color: 'var(--muted)', marginLeft: 8 }}>Nothing has been handed out.</span>}
      {msg && <div style={{ marginTop: 6, fontSize: 13, color: msgColor(msg) }}>{msg}</div>}
    </DangerCard>
  )
}

// Clear the judges' pool (allowed until a judge has rated).
export function ClearPoolControl({ apiJson, onDataChanged }) {
  const [pool, setPool] = useState(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  async function load() { const { ok, data } = await apiJson('/api/admin/judges-pool'); if (ok) setPool(data) }
  useEffect(() => { load() }, [])
  async function clear() {
    setBusy(true); setMsg('')
    const { ok, data } = await apiJson('/api/admin/judges-pool', { method: 'DELETE' })
    setBusy(false); setOpen(false)
    setMsg(ok ? "The judges' pool was cleared." : `Error: ${data?.error || 'Could not clear the pool'}`)
    await load(); onDataChanged()
  }
  return (
    <DangerCard title="Clear the judges' pool">
      <div style={{ fontSize: 13, color: 'var(--muted-2)', marginBottom: 6 }}>Removes the pool and the judges' unrated pool films so a different pool can be chosen. Not possible once a judge has rated.</div>
      {!open ? (
        <button onClick={() => { setOpen(true); setMsg('') }} disabled={!!pool && !pool.exists} style={{ color: 'var(--danger)' }}>Clear the pool…</button>
      ) : (
        <span style={{ fontSize: 13 }}>Clear the pool and the judges' unrated films?{' '}
          <button onClick={clear} disabled={busy} style={{ color: 'var(--danger)' }}>Yes, clear</button>{' '}
          <button onClick={() => setOpen(false)} disabled={busy}>Cancel</button></span>
      )}
      {pool && !pool.exists && <span style={{ fontSize: 12, color: 'var(--muted)', marginLeft: 8 }}>There is no pool.</span>}
      {msg && <div style={{ marginTop: 6, fontSize: 13, color: msgColor(msg) }}>{msg}</div>}
    </DangerCard>
  )
}
