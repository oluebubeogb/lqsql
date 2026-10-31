import React, { useEffect, useRef, useState } from 'react';
import { FileSpreadsheet, FileCode2, UploadCloud, Loader2, Play, CheckCircle2, ArrowRight, RotateCcw } from 'lucide-react';
import { api, fmtNum, fmtBytes } from './api.js';
import { Note, useToast } from './ui.jsx';

function Drop({ accept, onFile, label, maxMb }) {
  const [over, setOver] = useState(false); const inp = useRef();
  return (
    <div className={`drop ${over ? 'over' : ''}`} onClick={() => inp.current.click()}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); if (e.dataTransfer.files[0]) onFile(e.dataTransfer.files[0]); }}>
      <UploadCloud size={26} /><div style={{ marginTop: 6, fontWeight: 550 }}>{label}</div>
      <div className="small">Drop a file or click to browse · max {maxMb} MB</div>
      <input ref={inp} type="file" accept={accept} hidden onChange={(e) => e.target.files[0] && onFile(e.target.files[0])} />
    </div>
  );
}

function Progress({ p }) {
  if (!p) return null;
  const pct = p.total ? Math.round((100 * p.done) / p.total) : 0;
  return (
    <div className="col">
      <div className="row small"><span>{fmtNum(p.done)} / {fmtNum(p.total)}</span><div className="spacer" /><span>{pct}%</span></div>
      <div className="bar"><i style={{ width: `${pct}%` }} /></div>
    </div>
  );
}

export default function ImportPage({ ctx }) {
  const [kind, setKind] = useState('csv');
  const ro = ctx.me.read_only;
  return (
    <div className="col" style={{ gap: 14, maxWidth: 1100 }}>
      <div className="row">
        <div className="tabs">
          <button className={kind === 'csv' ? 'on' : ''} onClick={() => setKind('csv')}><FileSpreadsheet size={14} />CSV into a table</button>
          <button className={kind === 'sql' ? 'on' : ''} onClick={() => setKind('sql')}><FileCode2 size={14} />Run a .sql file</button>
        </div>
        <span className="muted small">Target: <b>{ctx.schema}</b></span>
      </div>
      {ro ? <Note level="warn">Read-only mode is on (READ_ONLY=true) — imports are disabled.</Note>
        : kind === 'csv' ? <CsvImport ctx={ctx} /> : <SqlImport ctx={ctx} />}
    </div>
  );
}

function CsvImport({ ctx }) {
  const toast = useToast();
  const [file, setFile] = useState(null); const [pv, setPv] = useState(null); const [err, setErr] = useState('');
  const [mode, setMode] = useState('existing'); const [target, setTarget] = useState(''); const [newName, setNewName] = useState('');
  const [tmeta, setTmeta] = useState(null); const [map, setMap] = useState({}); // existing: column -> csv idx ; new: idx -> {name,type,on}
  const [newCols, setNewCols] = useState([]);
  const [opts, setOpts] = useState({ empty_as_null: true, truncate: false });
  const [prog, setProg] = useState(null); const [busy, setBusy] = useState(false); const [result, setResult] = useState(null);
  const tables = ctx.tables.filter((t) => t.type !== 'view');

  const pick = async (f) => {
    setFile(f); setPv(null); setErr(''); setResult(null); setProg(null);
    const fd = new FormData(); fd.append('file', f);
    try {
      const p = await api.upload('import/csv/preview', fd);
      setPv(p); setNewName(p.suggested_table);
      setNewCols(p.header.map((h, i) => ({ name: h.trim().replace(/\s+/g, '_').toLowerCase() || `col${i + 1}`, type: p.types[i], on: true })));
      const match = tables.find((t) => t.name.toLowerCase() === p.suggested_table.toLowerCase());
      if (match) { setMode('existing'); setTarget(match.name); } else { setMode('new'); }
    } catch (e) { setErr(e.message); }
  };
  useEffect(() => {
    if (mode !== 'existing' || !target) { setTmeta(null); return; }
    api.get('table', { schema: ctx.schema, table: target }).then((m) => {
      setTmeta(m);
      const auto = {};
      m.columns.forEach((c) => { const i = pv ? pv.header.findIndex((h) => h.trim().toLowerCase() === c.name.toLowerCase()) : -1; auto[c.name] = i; });
      setMap(auto);
    }).catch((e) => setErr(e.message));
  }, [mode, target, pv]); // eslint-disable-line

  const commit = async () => {
    setBusy(true); setErr(''); setResult(null); setProg({ done: 0, total: pv.rows });
    let mapping; let body;
    if (mode === 'existing') {
      mapping = Object.entries(map).filter(([, i]) => i >= 0).map(([column, i]) => ({ csv: i, column }));
      body = { token: pv.token, schema: ctx.schema, table: target, mapping, create: false, ...opts };
    } else {
      mapping = newCols.map((c, i) => ({ csv: i, column: c.on ? c.name : '' })).filter((m) => m.column);
      body = { token: pv.token, schema: ctx.schema, table: newName, mapping, create: true, types: newCols.map((c) => c.type), empty_as_null: opts.empty_as_null };
    }
    try {
      await api.stream('import/csv/commit', { body, onEvent: (ev) => {
        if (ev.type === 'start') setProg({ done: 0, total: ev.total });
        if (ev.type === 'progress') setProg({ done: ev.done, total: ev.total });
        if (ev.type === 'error') setErr(ev.message + (ev.rolled_back !== false ? ' — nothing was imported (rolled back).' : ''));
        if (ev.type === 'done') { setResult(ev); toast(`Imported ${fmtNum(ev.inserted)} rows`); ctx.reloadTables(); }
      } });
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const mappedCount = mode === 'existing' ? Object.values(map).filter((i) => i >= 0).length : newCols.filter((c) => c.on).length;

  return (
    <>
      {!pv && <Drop accept=".csv,.tsv,.txt,text/csv" onFile={pick} label="Choose a CSV file" maxMb={ctx.me.import_max_mb} />}
      {err && <Note level="error">{err}</Note>}
      {pv && (
        <>
          <div className="card">
            <div className="card-h"><span className="ib violet"><FileSpreadsheet size={15} /></span><h3>{file?.name}</h3>
              <span className="pill">{fmtBytes(file?.size)}</span><span className="pill blue">{fmtNum(pv.rows)} rows</span><span className="pill">delimiter “{pv.delimiter === '\t' ? 'tab' : pv.delimiter}”</span>
              <div className="spacer" /><button className="btn sm ghost" onClick={() => { setPv(null); setFile(null); setResult(null); setErr(''); }}><RotateCcw size={13} />Another file</button></div>
            <div className="gridwrap" style={{ maxHeight: 230 }}>
              <table className="dg"><thead><tr>{pv.header.map((h, i) => <th key={i}><div className="th">{h}<small>{pv.types[i]}</small></div></th>)}</tr></thead>
                <tbody>{pv.sample.slice(0, 8).map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j} className={v === '' ? 'null' : ''}>{v === '' ? 'empty' : v}</td>)}</tr>)}</tbody></table>
            </div>
          </div>
          <div className="card">
            <div className="card-h"><span className="ib blue"><ArrowRight size={15} /></span><h3>Destination & mapping</h3></div>
            <div className="card-b col" style={{ gap: 12 }}>
              <div className="row wrap">
                <div className="chips">
                  <span className={`chip ${mode === 'existing' ? 'on' : ''}`} onClick={() => setMode('existing')}>Existing table</span>
                  <span className={`chip ${mode === 'new' ? 'on' : ''}`} onClick={() => setMode('new')}>New table</span>
                </div>
                {mode === 'existing' ? (
                  <select className="select" value={target} onChange={(e) => setTarget(e.target.value)}>
                    <option value="">Choose table…</option>{tables.map((t) => <option key={t.name}>{t.name}</option>)}
                  </select>
                ) : <input className="input" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="new_table_name" />}
              </div>
              {mode === 'existing' && tmeta && (
                <table className="plain"><thead><tr><th>Table column</th><th>Type</th><th>From CSV column</th></tr></thead>
                  <tbody>{tmeta.columns.filter((c) => !c.generated).map((c) => (
                    <tr key={c.name}><td><b>{c.name}</b></td><td className="mono muted">{c.type}</td>
                      <td><select className="select sm" value={map[c.name] ?? -1} onChange={(e) => setMap({ ...map, [c.name]: +e.target.value })}>
                        <option value={-1}>— skip (default) —</option>{pv.header.map((h, i) => <option key={i} value={i}>{h}</option>)}
                      </select></td></tr>))}
                  </tbody></table>
              )}
              {mode === 'new' && (
                <table className="plain"><thead><tr><th /><th>CSV column</th><th>New column name</th><th>Type</th></tr></thead>
                  <tbody>{newCols.map((c, i) => (
                    <tr key={i}><td><input type="checkbox" checked={c.on} onChange={(e) => setNewCols(newCols.map((x, j) => (j === i ? { ...x, on: e.target.checked } : x)))} /></td>
                      <td>{pv.header[i]}</td>
                      <td><input className="input sm" value={c.name} onChange={(e) => setNewCols(newCols.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} /></td>
                      <td><select className="select sm" value={c.type} onChange={(e) => setNewCols(newCols.map((x, j) => (j === i ? { ...x, type: e.target.value } : x)))}>
                        <option value="text">text</option><option value="integer">integer</option><option value="number">number</option></select></td></tr>))}
                  </tbody></table>
              )}
              <div className="row wrap" style={{ gap: 16 }}>
                <label className="chk"><input type="checkbox" checked={opts.empty_as_null} onChange={(e) => setOpts({ ...opts, empty_as_null: e.target.checked })} />Empty cells → NULL</label>
                {mode === 'existing' && <label className="chk"><input type="checkbox" checked={opts.truncate} onChange={(e) => setOpts({ ...opts, truncate: e.target.checked })} />Delete existing rows first</label>}
                <span className="muted small">Runs in one transaction — any error rolls everything back.</span>
              </div>
              <Progress p={prog} />
              {result && <Note level="ok">Imported <b>{fmtNum(result.inserted)}</b> rows into <b>{mode === 'existing' ? target : newName}</b> in {result.ms} ms.</Note>}
              <div className="row"><button className="btn primary" disabled={busy || !mappedCount || (mode === 'existing' ? !target : !newName)} onClick={commit}>
                {busy ? <Loader2 size={14} className="spin" /> : <Play size={14} />}Import {fmtNum(pv.rows)} rows</button>
                <span className="muted small">{mappedCount} column{mappedCount === 1 ? '' : 's'} mapped</span></div>
            </div>
          </div>
        </>
      )}
    </>
  );
}

function SqlImport({ ctx }) {
  const toast = useToast();
  const [file, setFile] = useState(null); const [singleTx, setSingleTx] = useState(true); const [stop, setStop] = useState(true);
  const [prog, setProg] = useState(null); const [busy, setBusy] = useState(false); const [log, setLog] = useState([]); const [res, setRes] = useState(null);
  const run = async () => {
    setBusy(true); setLog([]); setRes(null); setProg(null);
    const fd = new FormData(); fd.append('file', file); fd.append('single_tx', singleTx ? '1' : '0'); fd.append('stop_on_error', stop ? '1' : '0');
    const add = (l) => setLog((x) => [...x, l]);
    try {
      await api.stream('import/sql', { form: fd, onEvent: (ev) => {
        if (ev.type === 'start') { setProg({ done: 0, total: ev.total }); add(`${ev.total} statements found${ev.skipped ? `, ${ev.skipped} skipped` : ''}`); }
        if (ev.type === 'progress') setProg({ done: ev.done, total: ev.total });
        if (ev.type === 'error') { add(`✗ ${ev.index ? `#${ev.index}: ` : ''}${ev.message}${ev.statement ? `\n   ${ev.statement.slice(0, 200)}` : ''}`); setRes({ error: true, ...ev }); }
        if (ev.type === 'done') { add(`✓ executed ${ev.executed}, skipped ${ev.skipped} in ${ev.ms} ms`); (ev.errors || []).forEach((e) => add(`✗ #${e.index}: ${e.message}`)); setRes(ev); toast('SQL file imported'); ctx.reloadTables(); }
      } });
    } catch (e) { add('✗ ' + e.message); setRes({ error: true }); } finally { setBusy(false); }
  };
  return (
    <div className="card">
      <div className="card-h"><span className="ib amber"><FileCode2 size={15} /></span><h3>Run a SQL script</h3><span className="muted small">dumps from LiteSQL, pg_dump --inserts, mysqldump, sqlite3 .dump</span></div>
      <div className="card-b col" style={{ gap: 12 }}>
        {!file ? <Drop accept=".sql,.txt" onFile={setFile} label="Choose a .sql file" maxMb={ctx.me.import_max_mb} />
          : <div className="row"><span className="ib amber"><FileCode2 size={15} /></span><b>{file.name}</b><span className="pill">{fmtBytes(file.size)}</span><div className="spacer" /><button className="btn sm ghost" disabled={busy} onClick={() => { setFile(null); setLog([]); setRes(null); setProg(null); }}><RotateCcw size={13} />Change</button></div>}
        <div className="row wrap" style={{ gap: 16 }}>
          <label className="chk"><input type="checkbox" checked={singleTx} onChange={(e) => setSingleTx(e.target.checked)} />Single transaction (all or nothing)</label>
          <label className="chk"><input type="checkbox" checked={stop || singleTx} disabled={singleTx} onChange={(e) => setStop(e.target.checked)} />Stop on first error</label>
        </div>
        {ctx.me.engine === 'mysql' && <Note level="info">MySQL commits DDL (CREATE/ALTER/DROP) implicitly, so a failed script can leave earlier DDL applied.</Note>}
        <Progress p={prog} />
        {log.length > 0 && <div className="log">{log.join('\n')}</div>}
        {res && !res.error && <Note level="ok">Done — {res.executed} statements executed.</Note>}
        {res && res.error && res.rolled_back && <Note level="warn">Stopped and rolled back; no changes were kept.</Note>}
        <div><button className="btn primary" disabled={!file || busy} onClick={run}>{busy ? <Loader2 size={14} className="spin" /> : <Play size={14} />}Run script</button></div>
      </div>
    </div>
  );
}
