import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Table2, ListTree, Activity, Filter, RefreshCw, Plus, Trash2, FileSpreadsheet, FileCode2, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, ArrowUp, ArrowDown, KeyRound, X, Ban, Check, Lock, Code2 } from 'lucide-react';
import { api, fmtNum } from './api.js';
import { IB, Cell, Confirm, Modal, Spinner, useToast, Note } from './ui.jsx';
import TableAnalysis from './TableAnalysis.jsx';

const OPS = [['contains', 'contains'], ['eq', '='], ['neq', '≠'], ['starts', 'starts with'], ['gt', '>'], ['gte', '≥'], ['lt', '<'], ['lte', '≤'], ['null', 'is NULL'], ['notnull', 'is not NULL']];

export default function TableView({ schema, table, ctx }) {
  const [tab, setTab] = useState('browse');
  const [meta, setMeta] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => { api.get('table', { schema, table }).then(setMeta).catch((e) => setErr(e.message)); }, [schema, table]);
  if (err) return <div style={{ padding: 18 }}><Note level="error">{err}</Note></div>;
  if (!meta) return <Spinner />;
  return (
    <>
      <div className="toolbar" style={{ background: 'transparent' }}>
        <div className="tabs">
          <button className={tab === 'browse' ? 'on' : ''} onClick={() => setTab('browse')}><Table2 size={14} />Browse</button>
          <button className={tab === 'structure' ? 'on' : ''} onClick={() => setTab('structure')}><ListTree size={14} />Structure</button>
          <button className={tab === 'analysis' ? 'on' : ''} onClick={() => setTab('analysis')}><Activity size={14} />Analysis</button>
        </div>
        {meta.view && <span className="pill violet">View · read-only</span>}
        {!meta.view && !meta.editable && <span className="pill amber"><Lock size={11} />No primary key · read-only</span>}
        {meta.row_key && meta.row_key.type !== 'pk' && meta.editable && <span className="pill amber" title="No primary key; rows are addressed by the physical row id">Edits use {meta.row_key.type}</span>}
      </div>
      {tab === 'browse' && <Browse schema={schema} table={table} meta={meta} ctx={ctx} />}
      {tab === 'structure' && <div className="content"><Structure meta={meta} /></div>}
      {tab === 'analysis' && <div className="content"><TableAnalysis schema={schema} table={table} /></div>}
    </>
  );
}

function Structure({ meta }) {
  return (
    <div className="card">
      <div className="card-h"><span className="ib accent"><ListTree size={15} /></span><h3>Columns</h3><span className="muted small">{meta.columns.length}</span></div>
      <table className="plain">
        <thead><tr><th>Name</th><th>Type</th><th>Nullable</th><th>Default</th><th>Flags</th></tr></thead>
        <tbody>{meta.columns.map((c) => (
          <tr key={c.name}>
            <td><b>{c.name}</b> {c.pk && <KeyRound size={12} className="pk" />}</td>
            <td className="mono">{c.type}</td>
            <td>{c.nullable ? <span className="pill">null</span> : <span className="pill blue">not null</span>}</td>
            <td className="mono muted">{c.default ?? ''}</td>
            <td className="row wrap">{c.pk && <span className="pill amber">PK</span>}{c.auto && <span className="pill teal">auto</span>}{c.generated && <span className="pill violet">generated</span>}<span className="pill">{c.kind}</span></td>
          </tr>))}
        </tbody>
      </table>
    </div>
  );
}

function Browse({ schema, table, meta, ctx }) {
  const toast = useToast();
  const ro = ctx.me.read_only || !meta.editable;
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(ctx.me.page_size || 50);
  const [sort, setSort] = useState(null); const [dir, setDir] = useState('asc');
  const [filters, setFilters] = useState([]); const [applied, setApplied] = useState([]);
  const [showF, setShowF] = useState(false);
  const [data, setData] = useState(null); const [err, setErr] = useState('');
  const [sel, setSel] = useState(new Set());
  const [edit, setEdit] = useState(null); // {r, c, value}
  const [confirmDel, setConfirmDel] = useState(false); const [busy, setBusy] = useState(false);
  const [insert, setInsert] = useState(false); const [showSql, setShowSql] = useState(false);

  const load = useCallback(() => {
    setErr('');
    api.get('rows', { schema, table, page, size, sort, dir, f: applied.length ? JSON.stringify(applied) : '' })
      .then((d) => { setData(d); setSel(new Set()); }).catch((e) => setErr(e.message));
  }, [schema, table, page, size, sort, dir, applied]);
  useEffect(() => { load(); }, [load]);

  const colMeta = useMemo(() => Object.fromEntries(meta.columns.map((c) => [c.name, c])), [meta]);
  const keyCols = meta.row_key ? meta.row_key.columns : [];
  const keyOf = (row) => Object.fromEntries(keyCols.map((k) => [k, row[data.columns.indexOf(k)]]));
  const pages = data ? Math.max(1, Math.ceil((data.total || 0) / size)) : 1;

  const clickSort = (c) => { if (sort === c) setDir(dir === 'asc' ? 'desc' : 'asc'); else { setSort(c); setDir('asc'); } setPage(1); };
  const applyFilters = () => { setApplied(filters.filter((f) => f.column && (f.op === 'null' || f.op === 'notnull' || f.value !== ''))); setPage(1); };

  const startEdit = (ri, ci) => {
    const col = data.columns[ci]; const cm = colMeta[col];
    if (ro || !cm || cm.generated) return;
    const v = data.rows[ri][ci];
    setEdit({ r: ri, c: ci, value: v === null ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v), isNull: v === null });
  };
  const saveEdit = async (asNull) => {
    const col = data.columns[edit.c]; const row = data.rows[edit.r];
    const value = asNull ? null : edit.value;
    try {
      await api.patch('rows', { schema, table, key: keyOf(row), values: { [col]: value } });
      toast(`Updated ${col}`); setEdit(null); load();
    } catch (e) { toast(e.message, 'err'); }
  };
  const doDelete = async () => {
    setBusy(true);
    try {
      const keys = [...sel].map((i) => keyOf(data.rows[i]));
      const r = await api.post('rows/delete', { schema, table, keys });
      toast(`Deleted ${r.deleted} row${r.deleted === 1 ? '' : 's'}`); setConfirmDel(false); load(); ctx.reloadTables();
    } catch (e) { toast(e.message, 'err'); } finally { setBusy(false); }
  };
  const fParam = applied.length ? JSON.stringify(applied) : '';
  const visibleCols = data ? data.columns.map((c, i) => [c, i]).filter(([c]) => c !== '__rowid') : [];

  return (
    <>
      <div className="toolbar">
        <IB icon={Filter} tone={applied.length ? 'accent' : 'blue'} title="Filter" onClick={() => { setShowF(!showF); if (!filters.length) setFilters([{ column: meta.columns[0]?.name, op: 'contains', value: '' }]); }} />
        <IB icon={RefreshCw} tone="teal" title="Refresh" onClick={load} />
        {!ro && <IB icon={Plus} tone="green" title="Insert row" onClick={() => setInsert(true)} />}
        {!ro && <IB icon={Trash2} tone="rose" title="Delete selected" disabled={!sel.size} onClick={() => setConfirmDel(true)} />}
        <span style={{ width: 1, height: 20, background: 'var(--border)', margin: '0 2px' }} />
        <a className="ib violet" title="Export CSV (current filter & sort)" href={api.url('export/table.csv', { schema, table, f: fParam, sort, dir })}><FileSpreadsheet size={15} /></a>
        {!meta.view && <a className="ib amber" title="Export SQL dump of this table" href={api.url('export/sql', { schema, tables: table, ddl: 1, data: 1 })}><FileCode2 size={15} /></a>}
        <IB icon={Code2} tone="" title="Show generated SQL" onClick={() => setShowSql(!showSql)} />
        {applied.length > 0 && <span className="pill blue">{applied.length} filter{applied.length > 1 ? 's' : ''}<X size={11} style={{ cursor: 'pointer' }} onClick={() => { setApplied([]); setFilters([]); setShowF(false); }} /></span>}
        {sel.size > 0 && <span className="pill blue">{sel.size} selected</span>}
        <div className="spacer" />
        {ro && !meta.view && meta.editable && <span className="pill amber"><Lock size={11} />Read-only mode</span>}
        <span className="muted small">{data ? `${data.ms} ms` : ''}</span>
      </div>
      {showF && (
        <div className="filters">
          {filters.map((f, i) => (
            <div className="frow" key={i}>
              <select className="select sm" value={f.column} onChange={(e) => setFilters(filters.map((x, j) => (j === i ? { ...x, column: e.target.value } : x)))}>
                {meta.columns.map((c) => <option key={c.name}>{c.name}</option>)}
              </select>
              <select className="select sm" value={f.op} onChange={(e) => setFilters(filters.map((x, j) => (j === i ? { ...x, op: e.target.value } : x)))}>
                {OPS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
              {f.op !== 'null' && f.op !== 'notnull' && <input className="input sm" style={{ width: 240 }} value={f.value} placeholder="value"
                onKeyDown={(e) => e.key === 'Enter' && applyFilters()} onChange={(e) => setFilters(filters.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />}
              <IB icon={X} small title="Remove" onClick={() => setFilters(filters.filter((_, j) => j !== i))} />
            </div>
          ))}
          <div className="row">
            <button className="btn sm ghost" onClick={() => setFilters([...filters, { column: meta.columns[0]?.name, op: 'contains', value: '' }])}><Plus size={13} />Add condition</button>
            <button className="btn sm soft" onClick={applyFilters}><Check size={13} />Apply</button>
          </div>
        </div>
      )}
      {showSql && data && <div style={{ padding: '8px 18px', borderBottom: '1px solid var(--border)' }}><pre className="code">{data.sql}</pre></div>}
      <div className="gridwrap">
        {err && <div style={{ padding: 18 }}><Note level="error">{err}</Note></div>}
        {!data && !err && <Spinner />}
        {data && (
          <table className="dg">
            <thead><tr>
              <th className="ck"><div className="th">{!ro && <input type="checkbox" checked={data.rows.length > 0 && sel.size === data.rows.length} onChange={(e) => setSel(e.target.checked ? new Set(data.rows.map((_, i) => i)) : new Set())} />}</div></th>
              {visibleCols.map(([c]) => {
                const cm = colMeta[c] || {};
                return (
                  <th key={c}><div className="th" onClick={() => clickSort(c)} title={`${cm.type || ''}${cm.nullable === false ? ' · not null' : ''}`}>
                    {cm.pk && <KeyRound size={11} className="pk" />}{c}<small>{(cm.type || '').slice(0, 18)}</small>
                    {sort === c && (dir === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}
                  </div></th>
                );
              })}
            </tr></thead>
            <tbody>
              {data.rows.map((row, ri) => (
                <tr key={ri} className={sel.has(ri) ? 'sel' : ''}>
                  <td className="ck">{!ro ? <input type="checkbox" checked={sel.has(ri)} onChange={() => { const s = new Set(sel); s.has(ri) ? s.delete(ri) : s.add(ri); setSel(s); }} /> : <span className="rn">{(page - 1) * size + ri + 1}</span>}</td>
                  {visibleCols.map(([c, ci]) => {
                    const v = row[ci]; const cm = colMeta[c] || {};
                    if (edit && edit.r === ri && edit.c === ci) {
                      return (
                        <td key={c} className="edit">
                          <div className="row" style={{ gap: 4 }}>
                            <input autoFocus value={edit.value} placeholder={edit.isNull ? 'NULL' : ''} onChange={(e) => setEdit({ ...edit, value: e.target.value, isNull: false })}
                              onKeyDown={(e) => { if (e.key === 'Enter') saveEdit(false); if (e.key === 'Escape') setEdit(null); }} />
                            <IB icon={Check} small tone="green" title="Save (Enter)" onClick={() => saveEdit(false)} />
                            {cm.nullable !== false && <IB icon={Ban} small tone="amber" title="Set NULL" onClick={() => saveEdit(true)} />}
                            <IB icon={X} small title="Cancel (Esc)" onClick={() => setEdit(null)} />
                          </div>
                        </td>
                      );
                    }
                    return (
                      <td key={c} className={`${v === null ? 'null' : ''} ${cm.kind === 'number' ? 'num' : ''}`} onDoubleClick={() => startEdit(ri, ci)}
                        title={typeof v === 'string' && v.length > 30 ? v.slice(0, 1000) : ro ? undefined : 'Double-click to edit'}>
                        <Cell v={v} kind={cm.kind} />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {data && !data.rows.length && <div className="empty">No rows{applied.length ? ' match these filters' : ''}.</div>}
      </div>
      <div className="footbar">
        <IB icon={ChevronsLeft} small title="First" disabled={page <= 1} onClick={() => setPage(1)} />
        <IB icon={ChevronLeft} small title="Previous" disabled={page <= 1} onClick={() => setPage(page - 1)} />
        <span>Page <b>{page}</b> of {fmtNum(pages)}</span>
        <IB icon={ChevronRight} small title="Next" disabled={page >= pages} onClick={() => setPage(page + 1)} />
        <IB icon={ChevronsRight} small title="Last" disabled={page >= pages} onClick={() => setPage(pages)} />
        <span className="muted">· {data ? `${data.approx ? '~' : ''}${fmtNum(data.total)} rows` : ''}</span>
        <div className="spacer" />
        <select className="select sm" value={size} onChange={(e) => { setSize(+e.target.value); setPage(1); }}>
          {[25, 50, 100, 250, 500].map((n) => <option key={n} value={n}>{n} / page</option>)}
        </select>
      </div>
      {confirmDel && (
        <Confirm danger title={`Delete ${sel.size} row${sel.size > 1 ? 's' : ''}?`} confirmLabel="Delete" busy={busy} onConfirm={doDelete} onClose={() => setConfirmDel(false)}>
          <p style={{ marginTop: 0 }}>This permanently deletes the selected rows from <b>{schema}.{table}</b>, matched by {keyCols.join(', ')}.</p>
          <pre className="code">{[...sel].slice(0, 8).map((i) => JSON.stringify(keyOf(data.rows[i]))).join('\n')}{sel.size > 8 ? `\n… and ${sel.size - 8} more` : ''}</pre>
        </Confirm>
      )}
      {insert && <InsertModal schema={schema} table={table} meta={meta} onClose={() => setInsert(false)} onDone={() => { setInsert(false); load(); ctx.reloadTables(); }} />}
    </>
  );
}

function InsertModal({ schema, table, meta, onClose, onDone }) {
  const toast = useToast();
  const cols = meta.columns.filter((c) => !c.generated);
  const [vals, setVals] = useState(() => Object.fromEntries(cols.map((c) => [c.name, { v: '', mode: c.auto || c.default != null ? 'default' : 'value' }])));
  const [busy, setBusy] = useState(false); const [err, setErr] = useState('');
  const set = (n, patch) => setVals({ ...vals, [n]: { ...vals[n], ...patch } });
  const submit = async () => {
    setBusy(true); setErr('');
    const values = {};
    for (const c of cols) { const x = vals[c.name]; if (x.mode === 'null') values[c.name] = null; else if (x.mode === 'value') values[c.name] = x.v; }
    try { await api.post('rows', { schema, table, values }); toast('Row inserted'); onDone(); } catch (e) { setErr(e.message); setBusy(false); }
  };
  return (
    <Modal wide title={`Insert into ${table}`} icon={<span className="ib green"><Plus size={16} /></span>} onClose={onClose}
      footer={<><button className="btn ghost" onClick={onClose}>Cancel</button><button className="btn primary" disabled={busy} onClick={submit}><Check size={14} />Insert row</button></>}>
      <div className="form">
        {cols.map((c) => {
          const x = vals[c.name];
          return (
            <React.Fragment key={c.name}>
              <label title={c.name}>{c.pk && <KeyRound size={11} className="pk" />} {c.name}<small>{c.type}{c.nullable ? '' : ' · required'}</small></label>
              <input className="input" disabled={x.mode !== 'value'} value={x.mode === 'value' ? x.v : ''} placeholder={x.mode === 'default' ? `DEFAULT${c.default ? ' ' + String(c.default).slice(0, 40) : ''}` : x.mode === 'null' ? 'NULL' : ''}
                onChange={(e) => set(c.name, { v: e.target.value })} />
              <select className="select sm" value={x.mode} onChange={(e) => set(c.name, { mode: e.target.value })}>
                <option value="value">value</option>
                {(c.auto || c.default != null || c.nullable) && <option value="default">default</option>}
                {c.nullable && <option value="null">NULL</option>}
              </select>
            </React.Fragment>
          );
        })}
      </div>
      {err && <div style={{ marginTop: 12 }}><Note level="error">{err}</Note></div>}
    </Modal>
  );
}
