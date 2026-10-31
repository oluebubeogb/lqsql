import React, { useEffect, useState } from 'react';
import { HardDrive, Table2, Rows3, Activity, Plug, Sparkles, Lightbulb, RefreshCw, Gauge, Boxes, KeyRound } from 'lucide-react';
import { api, fmtBytes, fmtNum } from './api.js';
import { IB, Note, Spinner } from './ui.jsx';
import { go } from './App.jsx';

function Stat({ icon: Icon, tone, k, v, sub }) {
  return (
    <div className="card stat">
      <span className={`ib ${tone}`} style={{ width: 38, height: 38, borderRadius: 11 }}><Icon size={18} /></span>
      <div><div className="v">{v}</div><div className="k">{k}{sub ? <> · {sub}</> : null}</div></div>
    </div>
  );
}

export default function Overview({ ctx }) {
  const [d, setD] = useState(null); const [err, setErr] = useState('');
  const load = () => { setD(null); setErr(''); api.get('analysis').then(setD).catch((e) => setErr(e.message)); };
  useEffect(load, []);
  if (err) return <Note level="error">{err}</Note>;
  if (!d) return <Spinner label="Analysing database…" />;
  const s = d.stats || {};
  const max = Math.max(1, ...d.tables.map((t) => t.bytes || 0));
  const engineStat = d.engine === 'postgresql'
    ? <Stat icon={Activity} tone="teal" k="Cache hit" v={s.cache_hit_pct != null ? `${s.cache_hit_pct}%` : '—'} sub={`${s.connections}/${s.max_connections} conns`} />
    : d.engine === 'mysql'
      ? <Stat icon={Activity} tone="teal" k="Reclaimable" v={fmtBytes(s.free_bytes)} sub={s.version} />
      : <Stat icon={Activity} tone="teal" k="Journal" v={s.journal_mode || '—'} sub={s.quick_check ? `check: ${s.quick_check}` : `free ${fmtBytes(s.free_bytes)}`} />;
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="row"><div className="muted small">Database <b>{s.database}</b> · {d.engine} {s.version}</div><div className="spacer" /><IB icon={RefreshCw} tone="teal" title="Re-run analysis" onClick={load} /></div>
      <div className="grid g4">
        <Stat icon={HardDrive} tone="blue" k="Database size" v={fmtBytes(s.size_bytes)} />
        <Stat icon={Table2} tone="violet" k="Tables" v={fmtNum(s.tables ?? d.tables.length)} />
        <Stat icon={Rows3} tone="green" k="Rows (estimated)" v={fmtNum(s.total_rows)} />
        {engineStat}
      </div>
      <div className="grid g2" style={{ alignItems: 'start' }}>
        <div className="card">
          <div className="card-h"><span className="ib blue"><Boxes size={15} /></span><h3>Tables by size</h3><span className="muted small">{d.tables.length}</span></div>
          <table className="plain">
            <thead><tr><th>Table</th><th className="r">Rows</th><th className="r">Size</th><th style={{ width: '28%' }} /></tr></thead>
            <tbody>{d.tables.slice(0, 40).map((t) => (
              <tr key={t.schema + t.name} style={{ cursor: 'pointer' }} onClick={() => go(`t/${encodeURIComponent(t.schema)}/${encodeURIComponent(t.name)}`)}>
                <td><span className="muted">{t.schema !== ctx.schema ? `${t.schema}.` : ''}</span><b>{t.name}</b> {!t.has_pk && <span className="pill amber" style={{ marginLeft: 4 }}>no PK</span>}</td>
                <td className="r">{fmtNum(t.rows)}</td>
                <td className="r">{fmtBytes(t.bytes)}</td>
                <td><div className="bar"><i style={{ width: `${Math.max(2, (100 * (t.bytes || 0)) / max)}%` }} /></div></td>
              </tr>))}
            </tbody>
          </table>
          {!d.tables.length && <div className="empty small">No tables yet</div>}
        </div>
        <div className="col" style={{ gap: 14 }}>
          <div className="card">
            <div className="card-h"><span className="ib amber"><Lightbulb size={15} /></span><h3>Health notes</h3><span className="muted small">{d.notes.length}</span></div>
            <div className="card-b col">
              {d.notes.length ? d.notes.map((n, i) => <Note key={i} level={n.level}>{n.table && <b>{n.table}: </b>}{n.text}</Note>) : <Note level="ok">Nothing to flag — looks healthy.</Note>}
            </div>
          </div>
          {d.engine === 'postgresql' && (
            <div className="card">
              <div className="card-h"><span className="ib violet"><Plug size={15} /></span><h3>Extensions</h3></div>
              <div className="card-b col">
                <div className="chips">
                  {d.extensions.map((e) => <span key={e.name} className={`pill ${e.name === 'vector' ? 'teal' : 'blue'}`}>{e.name === 'vector' && <Sparkles size={11} />}{e.name} {e.version}</span>)}
                </div>
                {d.available_extensions?.length > 0 && <div className="small muted">Available, not installed: {d.available_extensions.map((e) => e.name).join(', ')}</div>}
                {d.vector_columns?.length > 0 && (
                  <div className="small"><b>pgvector columns:</b> {d.vector_columns.map((v) => <code key={v.schema + v.table + v.column} style={{ marginRight: 8 }}>{v.schema}.{v.table}.{v.column}</code>)}</div>
                )}
              </div>
            </div>
          )}
          {d.unused_indexes?.length > 0 && (
            <div className="card">
              <div className="card-h"><span className="ib rose"><KeyRound size={15} /></span><h3>Unused indexes</h3><span className="muted small">0 scans since stats reset</span></div>
              <table className="plain"><tbody>{d.unused_indexes.map((u) => <tr key={u.index}><td className="mono">{u.index}</td><td className="muted">{u.schema}.{u.table}</td><td className="r">{fmtBytes(u.bytes)}</td></tr>)}</tbody></table>
            </div>
          )}
          {d.engine === 'sqlite' && (
            <div className="card"><div className="card-h"><span className="ib teal"><Gauge size={15} /></span><h3>SQLite settings</h3></div>
              <table className="plain"><tbody>
                <tr><td>journal_mode</td><td className="r mono">{s.journal_mode}</td></tr>
                <tr><td>foreign_keys</td><td className="r mono">{String(s.foreign_keys)}</td></tr>
                <tr><td>free pages</td><td className="r">{fmtBytes(s.free_bytes)}</td></tr>
                <tr><td>integrity quick_check</td><td className="r mono">{s.quick_check || 'skipped'}</td></tr>
              </tbody></table></div>
          )}
        </div>
      </div>
    </div>
  );
}
