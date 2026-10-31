import React, { useEffect, useRef, useState } from 'react';
import { Play, History, Eraser, FileSpreadsheet, Loader2, CheckCircle2, AlertCircle, Clock, Copy, Trash2 } from 'lucide-react';
import { api, fmtNum } from './api.js';
import { IB, Confirm, ResultGrid, Note, useToast } from './ui.jsx';

const HKEY = 'lqsql-history';
const loadHist = () => { try { return JSON.parse(localStorage.getItem(HKEY) || '[]'); } catch (e) { return []; } };

export default function Terminal({ ctx }) {
  const toast = useToast();
  const [sql, setSql] = useState(() => localStorage.getItem('lqsql-draft') || (ctx.tables[0] ? `SELECT * FROM ${ctx.tables[0].name} LIMIT 50;` : 'SELECT 1;'));
  const [busy, setBusy] = useState(false);
  const [out, setOut] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const [hist, setHist] = useState(loadHist);
  const [showHist, setShowHist] = useState(false);
  const ta = useRef();
  useEffect(() => { try { localStorage.setItem('lqsql-draft', sql); } catch (e) { /* ignore */ } }, [sql]);

  const selected = () => {
    const el = ta.current; if (!el) return sql;
    const s = el.value.slice(el.selectionStart, el.selectionEnd);
    return s.trim() ? s : sql;
  };
  const run = async (force, text) => {
    const q = text || selected();
    if (!q.trim()) return;
    setBusy(true); setConfirm(null);
    try {
      const r = await api.post('sql', { sql: q, confirm: !!force });
      setOut(r);
      const h = [q.trim(), ...hist.filter((x) => x !== q.trim())].slice(0, 50);
      setHist(h); localStorage.setItem(HKEY, JSON.stringify(h));
      if (r.error) toast(`Failed at statement ${r.failed_index}`, 'err');
      if (r.results?.some((x) => !x.columns)) ctx.reloadTables();
    } catch (e) {
      if (e.status === 409 && e.data?.needs_confirm) setConfirm({ q, reasons: e.data.reasons || [] });
      else setOut({ error: e.message, results: [] });
    } finally { setBusy(false); }
  };
  const onKey = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); run(false); }
    if (e.key === 'Tab') { e.preventDefault(); const el = e.target; const s = el.selectionStart; const v = el.value; setSql(v.slice(0, s) + '  ' + v.slice(el.selectionEnd)); setTimeout(() => { el.selectionStart = el.selectionEnd = s + 2; }); }
  };
  const exportCsv = async (q) => { try { await api.download('export/query.csv', { sql: q }, 'query.csv'); } catch (e) { toast(e.message, 'err'); } };

  return (
    <div className="term">
      <div className="editor-wrap">
        <textarea ref={ta} className="editor" spellCheck={false} value={sql} onChange={(e) => setSql(e.target.value)} onKeyDown={onKey} placeholder="Write SQL… (Ctrl/⌘ + Enter to run; runs the selection if any)" />
        <div className="row" style={{ marginTop: 8 }}>
          <button className="btn primary" onClick={() => run(false)} disabled={busy}>{busy ? <Loader2 size={14} className="spin" /> : <Play size={14} />}Run</button>
          <span className="muted small">Ctrl/⌘ + Enter · multiple statements run in one transaction{ctx.me.read_only ? ' · read-only mode' : ''}</span>
          <div className="spacer" />
          <IB icon={History} tone="blue" title="History" onClick={() => setShowHist(!showHist)} />
          <IB icon={Eraser} tone="amber" title="Clear editor" onClick={() => { setSql(''); ta.current?.focus(); }} />
        </div>
        {showHist && (
          <div className="card" style={{ marginTop: 10 }}>
            <div className="card-h"><History size={14} /><h3>Recent queries</h3><div className="spacer" /><IB icon={Trash2} small tone="rose" title="Clear history" onClick={() => { setHist([]); localStorage.removeItem(HKEY); }} /></div>
            <div className="hist">{hist.length ? hist.map((h, i) => <div key={i} title={h} onClick={() => { setSql(h); setShowHist(false); }}>{h.replace(/\s+/g, ' ')}</div>) : <div className="muted">No history yet</div>}</div>
          </div>
        )}
      </div>
      <div className="results">
        {!out && <div className="empty">Results appear here. Each statement gets its own grid with timing and affected rows.</div>}
        {out && out.results?.map((r) => (
          <div key={r.index} className="card res">
            <div className="card-h">
              <span className="ib green sm"><CheckCircle2 size={13} /></span>
              <span className="pill">{r.keyword || 'SQL'}</span>
              <span className="sqlline" title={r.sql}>{r.sql}</span>
              <span className="pill blue"><Clock size={11} />{r.ms} ms</span>
              {r.columns ? <span className="pill green">{fmtNum(r.rows.length)} row{r.rows.length === 1 ? '' : 's'}{r.truncated ? ` (first ${fmtNum(ctx.me.max_result_rows)})` : ''}</span>
                : <span className="pill violet">{r.rowcount >= 0 ? `${fmtNum(r.rowcount)} affected` : 'OK'}</span>}
              {r.columns && <IB icon={FileSpreadsheet} small tone="violet" title="Export full result as CSV" onClick={() => exportCsv(r.sql)} />}
              <IB icon={Copy} small title="Copy SQL" onClick={() => { navigator.clipboard?.writeText(r.sql); toast('Copied'); }} />
            </div>
            {r.columns && <ResultGrid columns={r.columns} rows={r.rows} />}
          </div>
        ))}
        {out && out.error && (
          <div className="card res">
            <div className="card-h"><span className="ib rose sm"><AlertCircle size={13} /></span><h3>{out.failed_index ? `Statement ${out.failed_index} failed` : 'Error'}</h3>{out.rolled_back && <span className="pill amber">rolled back</span>}</div>
            <div className="card-b col">
              {out.failed_sql && <pre className="code">{out.failed_sql}</pre>}
              <pre className="err">{out.error}</pre>
              {out.note && <Note level="warn">{out.note}</Note>}
            </div>
          </div>
        )}
        {out && out.ms != null && <div className="muted small">Total {out.ms} ms</div>}
      </div>
      {confirm && (
        <Confirm danger title="Run destructive SQL?" confirmLabel="Run anyway" onConfirm={() => run(true, confirm.q)} onClose={() => setConfirm(null)}>
          <p style={{ marginTop: 0 }}>This batch contains statements that can destroy data:</p>
          <div className="col">{confirm.reasons.map((r, i) => <Note key={i} level="warn">{r}</Note>)}</div>
          <pre className="code" style={{ marginTop: 10 }}>{confirm.q.slice(0, 1500)}</pre>
        </Confirm>
      )}
    </div>
  );
}
