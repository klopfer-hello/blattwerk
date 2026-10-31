// Heute (M3: real data): this month's open to-dos (overdue, urgent, then by
// category) and what was done or skipped this month. Ticking off reloads the
// list, so every phone shows the same state. Weather alerts (M6b) sit on top;
// their urgent to-dos are in the list like any other.
import { useCallback, useEffect, useState } from 'react';
import { ApiError, CATEGORIES, api, type Category, type Heute, type Todo, type WeatherAlert } from '../api';
import { Back, Icon, TaskChip, deDate, localDay, monthName } from '../components/ui';
import { delayText } from './More';

const ORDER = Object.keys(CATEGORIES) as Category[];
export const UNDO_409 = 'Diese Aufgabe wurde inzwischen geändert – der Eintrag bleibt als Verlauf erhalten.';
const WEEKDAY = ['Sonntag', 'Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag'];

export function Today() {
  const [data, setData] = useState<Heute | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const load = useCallback(() => api.heute().then((h) => { setData(h); setError(''); }, (e) => setError(e instanceof ApiError ? e.message : 'Fehler')), []);
  useEffect(() => { load(); }, [load]);

  async function toggle(t: Todo) {
    if (busy) return;
    setBusy(t.id);
    try { await (t.status === 'open' ? api.done(t.id) : api.undo(t.id)); await load(); }
    catch (e) { setError(e instanceof ApiError && e.status === 409 ? UNDO_409 : e instanceof ApiError ? e.message : 'Fehler'); }
    finally { setBusy(null); }
  }

  const now = new Date();
  const groups: { key: string; label: string; urgent?: boolean; items: Todo[] }[] = [];
  if (data) {
    const rest = data.open.filter((t) => !t.overdue && !t.task.urgent);
    groups.push({ key: 'overdue', label: 'Überfällig', urgent: true, items: data.open.filter((t) => t.overdue) });
    groups.push({ key: 'urgent', label: 'Dringend', urgent: true, items: data.open.filter((t) => !t.overdue && t.task.urgent) });
    for (const c of ORDER) groups.push({ key: c, label: CATEGORIES[c], items: rest.filter((t) => t.task.category === c) });
  }
  const total = data ? data.open.length + data.done.length : 0;
  const pct = total ? Math.round(((data?.done.length ?? 0) / total) * 100) : 0;

  return (
    <div className="page">
      <header className="stack" style={{ gap: 12 }}>
        <div className="between">
          <span className="stack" style={{ gap: 2 }}>
            <span className="muted">{WEEKDAY[now.getDay()]}, {now.getDate()}. {monthName(now.getMonth() + 1)}</span>
            <SeasonChip />
          </span>
          <a href="#/aufgabe-neu" className="btn small"><Icon name="plus" size={18} />Aufgabe</a>
        </div>
        <h1 className="title">ToDos im {data ? monthName(data.month) : monthName(now.getMonth() + 1)}</h1>
      </header>

      <AlertCards />
      {error && <p className="box" role="alert" style={{ color: 'var(--urgent)' }}>{error}</p>}
      {!data && !error && <p className="muted">Lädt …</p>}

      {data && total > 0 && (
        <div className="stack">
          <strong>{data.done.length} von {total} erledigt</strong>
          <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}><div style={{ width: `${pct}%` }} /></div>
        </div>
      )}
      {data && total === 0 && (
        <div className="box stack">
          <strong>Für diesen Monat steht nichts an.</strong>
          <span>Lege Aufgaben an – bei einer Pflanze oder für den ganzen Garten. Mit dem Pflegeplan der KI (M5) kommen sie später automatisch.</span>
          <a href="#/aufgabe-neu" className="btn primary">Erste Aufgabe anlegen</a>
        </div>
      )}

      {groups.filter((g) => g.items.length).map((g) => (
        <section key={g.key} className="stack">
          <h2 className={g.urgent ? 'eyebrow urgent' : 'eyebrow'}>{g.label}</h2>
          {g.items.map((t) => <TodoItem key={t.id} t={t} busy={busy === t.id} onToggle={() => toggle(t)} />)}
        </section>
      ))}

      {data && data.done.length > 0 && (
        <section className="stack">
          <h2 className="eyebrow">Erledigt</h2>
          {data.done.map((t) => <TodoItem key={t.id} t={t} busy={busy === t.id} onToggle={() => toggle(t)} />)}
        </section>
      )}
    </div>
  );
}

function whenText(t: Todo): string {
  if (t.status === 'skipped') return 'Übersprungen' + (t.note ? ` · „${t.note}“` : '');
  if (t.status === 'done') return `Erledigt am ${t.done_at ? localDay(t.done_at) : ''}` + (t.note ? ` · „${t.note}“` : '');
  if (t.blocked_until) return `§ Erst ab ${deDate(t.blocked_until)} erlaubt (Vogelschutzzeit)`;
  if (t.overdue) return `Überfällig seit ${deDate(t.due_to)}`;
  if (t.postponed) return `Verschoben auf ${deDate(t.due_from)}`;
  return t.due_from === t.due_to ? `Fällig am ${deDate(t.due_from)}` : `bis ${deDate(t.due_to)}`;
}

export function TodoItem({ t, busy, onToggle }: { t: Todo; busy: boolean; onToggle: () => void }) {
  const done = t.status !== 'open';
  return (
    <div className={done ? 'todo done' : 'todo'}>
      <button className="check" role="checkbox" aria-checked={done} disabled={busy} onClick={onToggle}
        aria-label={done ? `${t.task.title}: wieder offen` : `${t.task.title}: erledigt`}>
        <span>{done && <Icon name="tick" size={16} stroke={3} />}</span>
      </button>
      <a className="todo-body" href={`#/aufgabe/${t.id}`}>
        <span className="todo-title">{t.task.title}</span>
        <span className="row" style={{ gap: 6 }}><TaskChip category={t.task.category} />{t.plant && <span className="small muted">{t.plant.title}</span>}</span>
        <span className={!done && (t.overdue || t.task.urgent) ? 'when urgent' : done ? 'small muted' : 'when'}>{whenText(t)}</span>
        {!done && t.legal_adjustment && <span className="small" style={{ color: 'var(--legal)', fontWeight: 700 }}>{t.legal_adjustment.startsWith('Verschoben') ? '§ verschoben (Vogelschutzzeit)' : '§ Zeitraum angepasst (Vogelschutzzeit)'}</span>}
      </a>
    </div>
  );
}

function SeasonChip() {
  const s = usePolled(api.season);
  if (!s?.current) return null;
  const d = s.current.delay_days;
  return (
    <a href="#/wetter" className="small" style={{ color: 'var(--green)', fontWeight: 700, textDecoration: 'none', minHeight: 44, display: 'inline-flex', alignItems: 'center' }}>
      {s.current.name}{d !== null && d !== 0 ? ` · ${delayText(d)}` : ''}
    </a>
  );
}

// ----- weather alerts (M6b) ---------------------------------------------------

const ICE = new Set(['frost', 'strong_frost', 'late_frost']);
export function alertWhen(w: WeatherAlert) {
  const d = new Date(`${w.day}T12:00:00`);
  const day = `${WEEKDAY[d.getDay()]}, ${d.getDate()}.${d.getMonth() + 1}.`;
  return ICE.has(w.kind) ? `in der Nacht auf ${day}` : `am ${day}`;
}

// Polls while visible, again when the app comes back to the front; errors keep the last answer.
function usePolled<T>(load: () => Promise<T>): T | null {
  const [v, setV] = useState<T | null>(null);
  useEffect(() => {
    let current = true;
    const get = () => load().then((x) => { if (current) setV(x); }, () => undefined);
    const onVisible = () => { if (document.visibilityState === 'visible') get(); };
    get();
    const t = window.setInterval(get, 5 * 60 * 1000);
    document.addEventListener('visibilitychange', onVisible);
    return () => { current = false; window.clearInterval(t); document.removeEventListener('visibilitychange', onVisible); };
  }, [load]);
  return v;
}

function AlertCards() {
  const list = usePolled(api.alerts);
  if (!list?.length) return null;
  return (
    <div className="stack" style={{ gap: 8 }} role="alert">
      {list.map((a) => (
        <a key={a.kind + a.day} href="#/warnung" className="card stack" style={{ gap: 4, textDecoration: 'none', color: 'var(--ink)', borderLeft: `6px solid ${ICE.has(a.kind) ? 'var(--frost)' : 'var(--urgent)'}` }}>
          <span className="eyebrow urgent">Wetterwarnung</span>
          <strong style={{ fontSize: 18 }}>{a.label}: {a.text}</strong>
          <span className="small muted">{alertWhen(a)}{a.tasks > 0 ? ' · Was zu tun ist, steht unten als dringende Aufgabe' : ' · keine Pflanze betroffen'} ›</span>
        </a>
      ))}
    </div>
  );
}

export function Alert() {
  const w = usePolled(api.weather);
  const nights = w?.days ?? [];
  return (
    <div className="page">
      <Back href="#/heute" label="Heute" />
      <h1 className="title-s">Wetterwarnungen</h1>
      {!w && <p className="muted">Lädt …</p>}
      {w && w.alerts.length === 0 && <p className="box">Gerade keine Warnung. Frost, Spätfrost, Hitze und Sturm werden 24–48 Stunden vorher gemeldet.</p>}
      {w?.alerts.map((a) => (
        <div key={a.kind + a.day} className="box stack" style={{ gap: 4, borderLeft: `6px solid ${ICE.has(a.kind) ? 'var(--frost)' : 'var(--urgent)'}` }}>
          <strong style={{ fontSize: 18 }}>{a.label}: {a.text}</strong>
          <span className="small muted">{alertWhen(a)}</span>
        </div>
      ))}
      {nights.length > 0 && (
        <div className="box stack" style={{ gap: 12 }}>
          <span className="small muted" style={{ fontWeight: 700 }}>Tiefstwerte der nächsten Tage</span>
          <div className="nights" style={{ height: 150 }}>
            {nights.map((n) => {
              const t = n.t_min ?? 0;
              return (
                <div key={n.date} className="night" style={{ height: '100%' }}>
                  <strong style={{ color: n.frost ? 'var(--frost)' : 'var(--muted)', fontSize: 15 }}>{Math.round(t)}°</strong>
                  <div style={{ width: '100%', borderRadius: 6, height: 20 + Math.min(Math.abs(t), 10) * 10, background: n.frost ? 'var(--frost)' : 'var(--line)' }} />
                  <span className="tiny">{new Date(`${n.date}T12:00:00`).toLocaleDateString('de-DE', { weekday: 'short' })}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
      <a href="#/heute" className="btn primary">Zu den dringenden Aufgaben</a>
    </div>
  );
}
