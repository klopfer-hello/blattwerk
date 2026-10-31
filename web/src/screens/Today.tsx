// Heute (M3: real data): this month's open to-dos (overdue, urgent, then by
// category) and what was done or skipped this month. Ticking off reloads the
// list, so every phone shows the same state. The weather warning stays a
// preview page until M6.
import { useCallback, useEffect, useState } from 'react';
import { ApiError, CATEGORIES, api, type Category, type Heute, type Todo } from '../api';
import { ALERT, NIGHTS, TODOS } from '../mock/data';
import { Back, Icon, TaskChip, deDate, localDay, monthName } from '../components/ui';

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
          <span className="muted">{WEEKDAY[now.getDay()]}, {now.getDate()}. {monthName(now.getMonth() + 1)}</span>
          <a href="#/aufgabe-neu" className="btn small"><Icon name="plus" size={18} />Aufgabe</a>
        </div>
        <h1 className="title">ToDos im {data ? monthName(data.month) : monthName(now.getMonth() + 1)}</h1>
      </header>

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

// ----- preview until M6 (weather) ---------------------------------------------

export function Alert() {
  const urgent = TODOS.filter((t) => t.urgent);
  return (
    <div className="page">
      <Back href="#/wetter" label="Wetter" />
      <span className="chip" style={{ background: 'var(--legal-tint)', color: 'var(--legal-ink)' }}>Vorschau – so sieht eine Wetter-Warnung aus (M6)</span>
      <div className="stack">
        <h1 className="title-s">{ALERT.title}</h1>
        <p style={{ color: 'var(--ink-2)' }}>{ALERT.text}</p>
      </div>
      <div className="box stack" style={{ gap: 12 }}>
        <span className="small muted" style={{ fontWeight: 700 }}>Tiefstwerte (Beispiel)</span>
        <div className="nights" style={{ height: 150 }}>
          {NIGHTS.map((n) => {
            const frost = n.t < 0;
            return (
              <div key={n.day} className="night" style={{ height: '100%' }}>
                <strong style={{ color: frost ? 'var(--frost)' : 'var(--muted)', fontSize: 15 }}>{n.t > 0 ? '+' : n.t < 0 ? '−' : ''}{Math.abs(n.t)}°</strong>
                <div style={{ width: '100%', borderRadius: 6, height: 20 + Math.abs(n.t) * 12, background: frost ? 'var(--frost)' : 'var(--line)' }} />
                <span className="tiny">{n.day}</span>
              </div>
            );
          })}
        </div>
      </div>
      <section className="stack">
        <h2 className="eyebrow urgent">Würde dann dringend</h2>
        {urgent.map((t) => <div key={t.id} className="card"><strong>{t.title}</strong><div className="small muted">{t.plantText}</div></div>)}
      </section>
    </div>
  );
}
