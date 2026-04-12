import { useEffect, useMemo, useState } from 'react'

function archiveDetailsUrl(identifier) {
  return identifier ? `https://archive.org/details/${identifier}` : null
}

function linkifyText(text) {
  const urlRegex = /(https?:\/\/[^\s]+)/g
  const parts = text.split(urlRegex)
  return parts.map((part, i) =>
    urlRegex.test(part)
      ? <a key={i} href={part} target="_blank" rel="noreferrer">{part}</a>
      : part
  )
}

function isIntString(s) {
  if (s === null || s === undefined) return false
  const t = String(s).trim()
  return /^-?\d+$/.test(t)
}

// ---------------------------------------------------------------------------
// AdminPanel
// ---------------------------------------------------------------------------

function AdminPanel({ syncing, syncResult, onSync, apiJson }) {
  const [tab, setTab] = useState('actions')

  // DB browser state
  const [tables, setTables] = useState(null)   // { tableName: rowCount }
  const [selTable, setSelTable] = useState('')
  const [rows, setRows] = useState(null)
  const [where, setWhere] = useState('')
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
    const w = opts.where  !== undefined ? opts.where  : where
    const o = opts.orderBy !== undefined ? opts.orderBy : orderBy
    const l = opts.limit  !== undefined ? opts.limit  : limit
    if (w)  params.set('where',    w)
    if (o)  params.set('order_by', o)
    if (l)  params.set('limit',    l)
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

  useEffect(() => {
    if (tab === 'db' && tables === null) loadTables()
    if (tab === 'users' && users === null) loadUsers()
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
        {['actions', 'db', 'users'].map(t => (
          <button key={t} style={tabStyle(t)} onClick={() => setTab(t)}>
            {t === 'actions' ? 'Actions' : t === 'db' ? 'DB Browser' : 'Users'}
          </button>
        ))}
      </div>

      <div style={{ padding: 14 }}>

        {/* ── Actions ── */}
        {tab === 'actions' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <button onClick={onSync} disabled={syncing}>
                {syncing ? 'Syncing…' : 'Sync Collection'}
              </button>
              {syncing && <span style={{ fontSize: 13, color: '#666' }}>Fetching from Internet Archive — may take a few minutes…</span>}
              {syncResult && <span style={{ fontSize: 13, color: '#060' }}>{syncResult}</span>}
            </div>
            <div>
              <a href="/api/admin/ratings.csv" style={{ fontSize: 14 }}>⬇ Download ratings.csv</a>
            </div>
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
                    onClick={() => { setSelTable(t); setWhere(''); setOrderBy(''); setLimit('100'); loadRows(t, { where: '', orderBy: '', limit: '100' }) }}
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
                  placeholder="WHERE …"
                  value={where}
                  onChange={e => setWhere(e.target.value)}
                  style={{ width: 200, fontFamily: 'monospace', fontSize: 13 }}
                />
                <input
                  placeholder="ORDER BY …"
                  value={orderBy}
                  onChange={e => setOrderBy(e.target.value)}
                  style={{ width: 160, fontFamily: 'monospace', fontSize: 13 }}
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

      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main App
// ---------------------------------------------------------------------------

export default function App() {
  const [me, setMe] = useState(null)
  const [authScheme, setAuthScheme] = useState('ia') // default matches server default
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  const [film, setFilm] = useState(null)
  const [criteria, setCriteria] = useState([])
  const [scores, setScores] = useState({}) // key -> string (user input)

  const [syncing, setSyncing] = useState(false)
  const [syncResult, setSyncResult] = useState('')

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
    setSubmitError('')
    const { ok, data } = await apiJson('/api/films/next')
    if (ok) {
      setFilm(data)
      setScores({})
    } else {
      setFilm(null)
      const msg = data?.error || 'No unrated films left (did you sync?)'
      // 404 is expected when exhausted; keep it non-fatal
      if (msg) setError(msg)
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

  async function adminSync() {
    setError('')
    setSyncResult('')
    setSyncing(true)
    const { ok, data } = await apiJson('/api/admin/sync', { method: 'POST' })
    setSyncing(false)
    if (!ok) {
      setError(data?.error || 'Admin sync failed')
      return
    }
    setSyncResult(`Sync complete — ${data.synced ?? '?'} films updated.`)
    await loadNextFilm()
  }

  useEffect(() => {
    apiJson('/api/config').then(({ ok, data }) => {
      setAuthScheme(ok ? (data?.auth_scheme ?? 'ia') : 'ia')
    })
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
        <AdminPanel
          syncing={syncing}
          syncResult={syncResult}
          onSync={adminSync}
          apiJson={apiJson}
        />
      ) : null}

      {loading ? <p>Loading…</p> : null}
      {error ? <div style={{ marginTop: 12, color: '#a00' }}>{error}</div> : null}

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
      ) : (
        <p style={{ marginTop: 14 }}>No films left.</p>
      )}
    </div>
  )
}
