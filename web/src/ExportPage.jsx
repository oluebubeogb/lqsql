import React, { useMemo, useState } from 'react';
import { FileCode2, FileSpreadsheet, Download, Table2, Eye, CheckSquare, Square, Search } from 'lucide-react';
import { api, fmtNum } from './api.js';
import { Note } from './ui.jsx';

export default function ExportPage({ ctx }) {
  const [fmt, setFmt] = useState('sql');
  const [sel, setSel] = useState(new Set());
  const [opt, setOpt] = useState({ ddl: true, data: true, drop: false });
  const [q, setQ] = useState('');
  const list = useMemo(() => ctx.tables.filter((t) => t.name.toLowerCase().includes(q.toLowerCase())), [ctx.tables, q]);
  const toggle = (n) => { const s = new Set(fmt === 'csv' ? [] : sel); if (sel.has(n)) s.delete(n); else s.add(n); setSel(s); };
  const names = ctx.tables.map((t) => t.name).filter((n) => sel.has(n));
  const href = fmt === 'sql'
    ? api.url('export/sql', { schema: ctx.schema, tables: names.join(','), ddl: opt.ddl ? 1 : 0, data: opt.data ? 1 : 0, drop: opt.drop ? 1 : 0 })
    : api.url('export/table.csv', { schema: ctx.schema, table: names[0] });
  return (
    <div className="col" style={{ gap: 14, maxWidth: 1000 }}>
      <div className="grid g2">
        <div className={`card stat`} style={{ cursor: 'pointer', outline: fmt === 'sql' ? '2px solid var(--accent)' : 'none' }} onClick={() => setFmt('sql')}>
          <span className="ib amber" style={{ width: 38, height: 38 }}><FileCode2 size={18} /></span>
          <div><div style={{ fontWeight: 600 }}>SQL dump</div><div className="k muted small">Schema + data as portable INSERTs. Re-import here or with psql / mysql / sqlite3.</div></div>
        </div>
        <div className={`card stat`} style={{ cursor: 'pointer', outline: fmt === 'csv' ? '2px solid var(--accent)' : 'none' }} onClick={() => { setFmt('csv'); setSel(new Set(names.slice(0, 1))); }}>
          <span className="ib violet" style={{ width: 38, height: 38 }}><FileSpreadsheet size={18} /></span>
          <div><div style={{ fontWeight: 600 }}>CSV</div><div className="k muted small">One table, UTF-8 with header row. For query results use the SQL terminal’s CSV button.</div></div>
        </div>
      </div>
      <div className="card">
        <div className="card-h"><span className="ib blue"><Table2 size={15} /></span><h3>{fmt === 'csv' ? 'Pick a table' : 'Pick tables'} in {ctx.schema}</h3>
          <div className="spacer" />
          <div className="search" style={{ width: 200 }}><Search size={14} /><input className="input sm" placeholder="Filter…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
          {fmt === 'sql' && <button className="btn sm ghost" onClick={() => setSel(sel.size === ctx.tables.length ? new Set() : new Set(ctx.tables.map((t) => t.name)))}>{sel.size === ctx.tables.length ? <Square size={13} /> : <CheckSquare size={13} />}{sel.size === ctx.tables.length ? 'None' : 'All'}</button>}
        </div>
        <div className="card-b"><div className="chips">
          {list.map((t) => (
            <span key={t.name} className={`chip ${sel.has(t.name) ? 'on' : ''}`} onClick={() => toggle(t.name)}>
              {t.type === 'view' ? <Eye size={12} /> : <Table2 size={12} />}{t.name}{t.rows != null && <span className="muted small">{fmtNum(t.rows)}</span>}
            </span>))}
          {!list.length && <span className="muted">No tables</span>}
        </div></div>
      </div>
      {fmt === 'sql' && (
        <div className="card"><div className="card-b row wrap" style={{ gap: 18 }}>
          <label className="chk"><input type="checkbox" checked={opt.ddl} onChange={(e) => setOpt({ ...opt, ddl: e.target.checked })} />Structure (CREATE TABLE, indexes, FKs)</label>
          <label className="chk"><input type="checkbox" checked={opt.data} onChange={(e) => setOpt({ ...opt, data: e.target.checked })} />Data (INSERT)</label>
          <label className="chk"><input type="checkbox" checked={opt.drop} disabled={!opt.ddl} onChange={(e) => setOpt({ ...opt, drop: e.target.checked })} />Add DROP … IF EXISTS</label>
        </div></div>
      )}
      {ctx.me.engine === 'postgresql' && fmt === 'sql' && <Note level="info">For very large or full-cluster backups prefer <code>pg_dump</code>. lqSQL dumps tables, sequences, indexes, constraints, views and required extensions (e.g. <code>vector</code>).</Note>}
      <div className="row">
        <a className={`btn primary ${names.length && (fmt === 'csv' || opt.ddl || opt.data) ? '' : 'disabled'}`} style={!names.length ? { pointerEvents: 'none', opacity: 0.5 } : undefined} href={href}>
          <Download size={14} />Download {fmt.toUpperCase()}</a>
        <span className="muted small">{names.length ? `${names.length} selected` : 'Nothing selected'}</span>
      </div>
    </div>
  );
}
