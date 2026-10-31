import React, { useEffect, useState } from 'react';
import { HardDrive, Rows3, KeyRound, Link2, Lightbulb, Columns3, Fingerprint, RefreshCw } from 'lucide-react';
import { api, fmtBytes, fmtNum } from './api.js';
import { IB, Note, Spinner } from './ui.jsx';

export default function TableAnalysis({ schema, table }) {
  const [d, setD] = useState(null); const [err, setErr] = useState('');
  const load = () => { setD(null); api.get('analysis/table', { schema, table }).then(setD).catch((e) => setErr(e.message)); };
  useEffect(load, [schema, table]); // eslint-disable-line
  if (err) return <Note level="error">{err}</Note>;
  if (!d) return <Spinner label="Profiling columns…" />;
  const dc = d.duplicate_check;
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="grid g4">
        <div className="card stat"><span className="ib green" style={{ width: 38, height: 38 }}><Rows3 size={18} /></span><div><div className="v">{d.rows_approx ? '~' : ''}{fmtNum(d.rows)}</div><div className="k">Rows{d.sampled ? ` · profiled ${fmtNum(d.sampled)} sample` : ''}</div></div></div>
        <div className="card stat"><span className="ib blue" style={{ width: 38, height: 38 }}><HardDrive size={18} /></span><div><div className="v">{fmtBytes(d.size?.total)}</div><div className="k">Total{d.size?.indexes != null ? ` · ${fmtBytes(d.size.indexes)} indexes` : ''}</div></div></div>
        <div className="card stat"><span className="ib violet" style={{ width: 38, height: 38 }}><Columns3 size={18} /></span><div><div className="v">{d.columns.length}</div><div className="k">Columns · {d.indexes.length} indexes</div></div></div>
        <div className="card stat"><span className={`ib ${dc && dc.duplicates ? 'rose' : 'teal'}`} style={{ width: 38, height: 38 }}><Fingerprint size={18} /></span><div><div className="v">{dc ? fmtNum(dc.duplicates) : '—'}</div><div className="k">{dc ? `Duplicate ${dc.columns.join(', ')}` : 'No key to check'}</div></div></div>
      </div>
      <div className="card">
        <div className="card-h"><span className="ib amber"><Lightbulb size={15} /></span><h3>Notes</h3><div className="spacer" /><IB icon={RefreshCw} small tone="teal" title="Re-run" onClick={load} /></div>
        <div className="card-b col">{d.notes.length ? d.notes.map((n, i) => <Note key={i} level={n.level}>{n.text}</Note>) : <Note level="ok">No issues found for this table.</Note>}</div>
      </div>
      <div className="card">
        <div className="card-h"><span className="ib violet"><Columns3 size={15} /></span><h3>Column profile</h3></div>
        <table className="plain">
          <thead><tr><th>Column</th><th>Type</th><th>Nullable</th><th className="r">NULLs</th><th style={{ width: '18%' }}>Null rate</th><th className="r">Distinct</th></tr></thead>
          <tbody>{d.columns.map((c) => (
            <tr key={c.name}>
              <td><b>{c.name}</b> {c.pk && <KeyRound size={11} className="pk" />}</td>
              <td className="mono">{c.type}</td>
              <td>{c.nullable ? 'yes' : <span className="pill blue">not null</span>}</td>
              <td className="r">{fmtNum(c.null_count)}</td>
              <td><div className="row"><div className="bar" style={{ flex: 1 }}><i style={{ width: `${c.null_pct || 0}%`, background: c.null_pct > 50 ? 'var(--amber)' : undefined }} /></div><span className="small muted" style={{ width: 44, textAlign: 'right' }}>{c.null_pct != null ? `${c.null_pct}%` : '—'}</span></div></td>
              <td className="r">{c.distinct != null ? fmtNum(c.distinct) : <span className="muted">—</span>}</td>
            </tr>))}
          </tbody>
        </table>
      </div>
      <div className="grid g2" style={{ alignItems: 'start' }}>
        <div className="card">
          <div className="card-h"><span className="ib blue"><KeyRound size={15} /></span><h3>Indexes</h3></div>
          <table className="plain"><tbody>
            {d.indexes.map((i) => (
              <tr key={i.name}><td className="mono">{i.name}</td><td>{i.columns.join(', ')}</td>
                <td className="row">{i.primary && <span className="pill amber">PK</span>}{i.unique && !i.primary && <span className="pill blue">unique</span>}{i.scans != null && <span className={`pill ${i.scans ? '' : 'rose'}`}>{fmtNum(i.scans)} scans</span>}</td>
                <td className="r">{i.bytes != null ? fmtBytes(i.bytes) : ''}</td></tr>))}
          </tbody></table>
          {!d.indexes.length && <div className="empty small">No indexes</div>}
        </div>
        <div className="card">
          <div className="card-h"><span className="ib teal"><Link2 size={15} /></span><h3>Relationships</h3></div>
          <table className="plain"><tbody>
            {d.foreign_keys.map((f) => <tr key={f.name}><td className="mono">{f.columns.join(', ')}</td><td>→ {f.ref}({f.ref_columns.join(', ')})</td></tr>)}
            {d.referenced_by.map((f, i) => <tr key={i}><td className="mono">{f.name}</td><td>← referenced by <b>{f.table}</b></td></tr>)}
          </tbody></table>
          {!d.foreign_keys.length && !d.referenced_by.length && <div className="empty small">No foreign keys</div>}
        </div>
      </div>
    </div>
  );
}
