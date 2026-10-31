import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Database, Table2, Eye, TerminalSquare, Upload, Download, Gauge, Moon, Sun, LogOut, Search, RefreshCw, Lock, Menu, Layers, Loader2 } from 'lucide-react';
import { api, fmtNum } from './api.js';
import { ToastProvider, IB } from './ui.jsx';
import Login from './Login.jsx';
import TableView from './TableView.jsx';
import Terminal from './Terminal.jsx';
import ImportPage from './ImportPage.jsx';
import ExportPage from './ExportPage.jsx';
import Overview from './Overview.jsx';

const ENGINE = { postgresql: ['PostgreSQL', 'blue'], mysql: ['MySQL', 'amber'], sqlite: ['SQLite', 'teal'] };

function parseHash() {
  const h = decodeURIComponent(location.hash.replace(/^#\/?/, ''));
  const [page, ...rest] = h.split('/');
  if (page === 't' && rest.length >= 2) return { page: 't', schema: rest[0], table: rest.slice(1).join('/') };
  return { page: page || 'overview' };
}
export const go = (path) => { location.hash = '#/' + path; };

function useTheme() {
  const [theme, setTheme] = useState(document.documentElement.dataset.theme || 'light');
  useEffect(() => { document.documentElement.dataset.theme = theme; try { localStorage.setItem('lqsql-theme', theme); } catch (e) { /* ignore */ } }, [theme]);
  return [theme, () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))];
}

function Shell({ me, onLogout, theme, toggleTheme }) {
  const [route, setRoute] = useState(parseHash());
  const [schemas, setSchemas] = useState([]);
  const [schema, setSchema] = useState(localStorage.getItem('lqsql-schema') || me.default_schema);
  const [tables, setTables] = useState(null);
  const [q, setQ] = useState('');
  const [menu, setMenu] = useState(false);

  useEffect(() => { const f = () => { setRoute(parseHash()); setMenu(false); }; window.addEventListener('hashchange', f); return () => window.removeEventListener('hashchange', f); }, []);
  useEffect(() => {
    api.get('schemas').then((r) => {
      setSchemas(r.schemas);
      if (!r.schemas.includes(schema)) setSchema(r.schemas.includes(me.default_schema) ? me.default_schema : r.schemas[0]);
    }).catch(() => {});
  }, []); // eslint-disable-line
  const loadTables = useCallback(() => {
    if (!schema) return;
    setTables(null);
    api.get('tables', { schema }).then((r) => setTables(r.tables)).catch(() => setTables([]));
  }, [schema]);
  useEffect(() => { loadTables(); try { localStorage.setItem('lqsql-schema', schema); } catch (e) { /* ignore */ } }, [loadTables, schema]);
  useEffect(() => { if (route.page === 't' && route.schema !== schema && schemas.includes(route.schema)) setSchema(route.schema); }, [route, schemas]); // eslint-disable-line

  const shown = useMemo(() => (tables || []).filter((t) => t.name.toLowerCase().includes(q.toLowerCase())), [tables, q]);
  const [eng, tone] = ENGINE[me.engine] || [me.engine, ''];
  const nav = [
    ['overview', 'Overview', Gauge], ['sql', 'SQL terminal', TerminalSquare], ['import', 'Import', Upload], ['export', 'Export', Download],
  ];
  const ctx = { me, schema, schemas, tables: tables || [], reloadTables: loadTables };
  let title; let body; let flush = false;
  if (route.page === 't') {
    title = <><span className="crumb">{route.schema} /</span><span>{route.table}</span></>;
    body = <TableView key={route.schema + '.' + route.table} schema={route.schema} table={route.table} ctx={ctx} />; flush = true;
  } else if (route.page === 'sql') { title = <span>SQL terminal</span>; body = <Terminal ctx={ctx} />; flush = true; }
  else if (route.page === 'import') { title = <span>Import</span>; body = <ImportPage ctx={ctx} />; }
  else if (route.page === 'export') { title = <span>Export</span>; body = <ExportPage ctx={ctx} />; }
  else { title = <span>Overview</span>; body = <Overview ctx={ctx} />; }

  return (
    <div className={`app ${menu ? 'menu' : ''}`}>
      <aside className="side">
        <div className="brand">
          <div className="logo"><Database size={16} /></div>
          <div><b>lqSQL</b><small>{me.database || 'database'}</small></div>
        </div>
        <nav className="nav">
          {nav.map(([k, label, Icon]) => (
            <button key={k} className={route.page === k ? 'on' : ''} onClick={() => go(k)}><Icon size={16} />{label}</button>
          ))}
        </nav>
        <div className="side-sec">
          <div className="side-label"><span>{me.engine === 'mysql' ? 'Database' : 'Schema'}</span>
            <IB icon={RefreshCw} small title="Refresh tables" onClick={loadTables} /></div>
          {schemas.length > 1 && (
            <select className="select sm" value={schema} onChange={(e) => setSchema(e.target.value)}>
              {schemas.map((s) => <option key={s}>{s}</option>)}
            </select>
          )}
          <div className="search"><Search size={14} /><input className="input sm" placeholder="Find table…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        </div>
        <div className="tlist">
          {tables === null && <div className="empty small"><Loader2 size={16} className="spin" /></div>}
          {tables && !shown.length && <div className="empty small">No tables</div>}
          {shown.map((t) => {
            const on = route.page === 't' && route.table === t.name && route.schema === schema;
            return (
              <div key={t.name} className={`titem ${on ? 'on' : ''}`} onClick={() => go(`t/${encodeURIComponent(schema)}/${encodeURIComponent(t.name)}`)} title={t.name}>
                {t.type === 'view' ? <Eye size={14} /> : <Table2 size={14} />}
                <span className="nm">{t.name}</span>
                {t.rows !== null && t.rows !== undefined && <span className="ct">{t.approx ? '~' : ''}{fmtNum(t.rows)}</span>}
              </div>
            );
          })}
        </div>
        <div className="side-foot"><span>{tables ? `${tables.length} objects` : ''}</span><span>v{me.app_version}</span></div>
      </aside>
      <main className="main">
        <header className="top">
          <IB icon={Menu} title="Menu" className="ib only-mobile" onClick={() => setMenu((m) => !m)} />
          <h1>{title}</h1>
          <div className="spacer" />
          <span className={`pill ${tone}`}><span className="dot" />{eng} {me.version ? me.version.split(' ')[0] : ''}</span>
          {me.host && <span className="pill" title="Host"><Layers size={12} />{me.host}</span>}
          {me.read_only && <span className="pill amber"><Lock size={12} />Read-only</span>}
          <IB icon={theme === 'dark' ? Sun : Moon} tone="violet" title="Toggle theme" onClick={toggleTheme} />
          <IB icon={LogOut} tone="rose" title={`Sign out ${me.user}`} onClick={onLogout} />
        </header>
        <div className={`content ${flush ? 'flush' : ''}`}>{body}</div>
      </main>
    </div>
  );
}

export default function App() {
  const [theme, toggleTheme] = useTheme();
  const [state, setState] = useState({ loading: true });
  const load = useCallback(async () => {
    try {
      const s = await api.get('session');
      if (!s.signed_in) return setState({ signedIn: false, engine: s.engine });
      const me = await api.get('me');
      setState({ signedIn: true, me });
    } catch (e) { setState({ signedIn: false, error: e.message }); }
  }, []);
  useEffect(() => { load(); const f = () => setState((s) => ({ ...s, signedIn: false })); window.addEventListener('lqsql:logout', f); return () => window.removeEventListener('lqsql:logout', f); }, [load]);
  const logout = async () => { await api.post('logout').catch(() => {}); setState({ signedIn: false }); };
  return (
    <ToastProvider>
      {state.loading ? <div className="login"><Loader2 className="spin" /></div>
        : state.signedIn ? <Shell me={state.me} onLogout={logout} theme={theme} toggleTheme={toggleTheme} />
          : <Login engine={state.engine} onDone={load} theme={theme} toggleTheme={toggleTheme} />}
    </ToastProvider>
  );
}
