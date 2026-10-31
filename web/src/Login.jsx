import React, { useState } from 'react';
import { Database, Loader2, Moon, Sun, LogIn } from 'lucide-react';
import { api } from './api.js';
import { IB } from './ui.jsx';

export default function Login({ engine, onDone, theme, toggleTheme }) {
  const [u, setU] = useState(''); const [p, setP] = useState('');
  const [busy, setBusy] = useState(false); const [err, setErr] = useState('');
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr('');
    try { await api.post('login', { username: u, password: p }); onDone(); } catch (x) { setErr(x.message); setBusy(false); }
  };
  return (
    <div className="login">
      <div style={{ position: 'fixed', top: 16, right: 16 }}><IB icon={theme === 'dark' ? Sun : Moon} tone="violet" title="Toggle theme" onClick={toggleTheme} /></div>
      <form className="card" onSubmit={submit}>
        <div className="logo" style={{ width: 40, height: 40, borderRadius: 12 }}><Database size={20} /></div>
        <h2>Sign in to lqSQL</h2>
        <p>Lightweight admin for your {engine ? { postgresql: 'PostgreSQL', mysql: 'MySQL', sqlite: 'SQLite' }[engine] || engine : ''} database.</p>
        <label className="field"><span>Username</span><input className="input" autoFocus autoComplete="username" value={u} onChange={(e) => setU(e.target.value)} /></label>
        <label className="field"><span>Password</span><input className="input" type="password" autoComplete="current-password" value={p} onChange={(e) => setP(e.target.value)} /></label>
        {err && <div className="note error" style={{ marginBottom: 10 }}>{err}</div>}
        <button className="btn primary" disabled={busy || !u || !p}>{busy ? <Loader2 size={15} className="spin" /> : <LogIn size={15} />}Sign in</button>
      </form>
    </div>
  );
}
