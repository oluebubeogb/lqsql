import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { X, CheckCircle2, AlertCircle, AlertTriangle, Info, Loader2 } from 'lucide-react';

const ToastCtx = createContext(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const push = useCallback((msg, kind = 'ok') => {
    const id = Math.random();
    setItems((x) => [...x, { id, msg, kind }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), kind === 'err' ? 6000 : 3000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            {t.kind === 'err' ? <AlertCircle size={17} /> : <CheckCircle2 size={17} />}
            <span>{t.msg}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function Modal({ title, icon, onClose, children, footer, wide }) {
  useEffect(() => {
    const k = (e) => e.key === 'Escape' && onClose && onClose();
    window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose && onClose()}>
      <div className={`modal ${wide ? 'wide' : ''}`}>
        <div className="modal-h">{icon}<h3>{title}</h3><button className="ib sm" onClick={onClose} title="Close"><X size={14} /></button></div>
        <div className="modal-b">{children}</div>
        {footer && <div className="modal-f">{footer}</div>}
      </div>
    </div>
  );
}

export function Confirm({ title, children, confirmLabel = 'Confirm', danger, onConfirm, onClose, busy }) {
  return (
    <Modal title={title} onClose={onClose}
      icon={<span className={`ib ${danger ? 'rose' : 'amber'}`}><AlertTriangle size={16} /></span>}
      footer={<>
        <button className="btn ghost" onClick={onClose}>Cancel</button>
        <button className={`btn ${danger ? 'danger' : 'primary'}`} onClick={onConfirm} disabled={busy}>
          {busy && <Loader2 size={14} className="spin" />}{confirmLabel}
        </button>
      </>}>
      {children}
    </Modal>
  );
}

export function IB({ icon: Icon, tone, title, size = 15, small, ...p }) {
  return <button className={`ib ${tone || ''} ${small ? 'sm' : ''}`} title={title} aria-label={title} {...p}><Icon size={small ? 13 : size} /></button>;
}

export function Note({ level = 'info', children }) {
  const Icon = level === 'warn' ? AlertTriangle : level === 'ok' ? CheckCircle2 : level === 'error' ? AlertCircle : Info;
  return <div className={`note ${level}`}><Icon size={15} /><div>{children}</div></div>;
}

export function Spinner({ label = 'Loading…' }) {
  return <div className="empty"><Loader2 size={20} className="spin" /><div>{label}</div></div>;
}

export function Cell({ v, kind }) {
  if (v === null || v === undefined) return <span className="muted"><i>NULL</i></span>;
  if (typeof v === 'boolean') return <span className={`v-bool v-${v}`}>{String(v)}</span>;
  if (typeof v === 'object') return <span className="v-json">{JSON.stringify(v)}</span>;
  if (kind === 'vector') return <span className="v-vec">{String(v)}</span>;
  if (kind === 'json') return <span className="v-json">{String(v)}</span>;
  return String(v);
}

export const isNum = (v, kind) => kind === 'number' || typeof v === 'number';

export function ResultGrid({ columns, rows }) {
  if (!columns || !columns.length) return null;
  return (
    <div className="gridwrap">
      <table className="dg">
        <thead><tr><th className="ck"><div className="th">#</div></th>{columns.map((c, i) => <th key={i}><div className="th">{c}</div></th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="ck rn">{i + 1}</td>
              {r.map((v, j) => <td key={j} className={`${v === null ? 'null' : ''} ${typeof v === 'number' ? 'num' : ''}`} title={typeof v === 'string' && v.length > 40 ? v.slice(0, 1000) : undefined}><Cell v={v} /></td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && <div className="empty small">No rows</div>}
    </div>
  );
}
