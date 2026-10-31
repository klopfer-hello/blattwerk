// Shared UI pieces: icons, navigation, chips, the to-do row and a tiny hash
// router (no dependency; the phone's back button works through the history).
import { useEffect, useState, type ReactNode } from 'react';
import type { Category, Todo } from '../mock/data';
import { CATEGORIES, type Category as ApiCategory, type LegalNote, type TaskIn } from '../api';

export function useRoute(): string[] {
  const read = () => (window.location.hash.replace(/^#\/?/, '') || 'heute').split('/');
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const on = () => { setRoute(read()); window.scrollTo(0, 0); };
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return route;
}

export function useWide(): boolean {
  const q = '(min-width: 900px)';
  const [wide, setWide] = useState(() => window.matchMedia(q).matches);
  useEffect(() => {
    const m = window.matchMedia(q);
    const on = () => setWide(m.matches);
    m.addEventListener('change', on);
    return () => m.removeEventListener('change', on);
  }, []);
  return wide;
}

const paths: Record<string, ReactNode> = {
  check: <><path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></>,
  calendar: <><rect x="3" y="4" width="18" height="18" rx="2" /><path d="M16 2v4M8 2v4M3 10h18" /></>,
  plant: <><path d="M12 22V12" /><path d="M12 12C12 8 9 5 4 5c0 4 3 7 8 7Z" /><path d="M12 14c0-4 3-7 8-7 0 4-3 7-8 7Z" /></>,
  chat: <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />,
  frost: <path d="M12 2v20M4.9 4.9l14.2 14.2M2 12h20M4.9 19.1 19.1 4.9" />,
  thermo: <path d="M14 4v10.5a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0Z" />,
  leaf: <><path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.5 19 2c1 2 2 4.2 2 8 0 5.5-4.8 10-10 10Z" /><path d="M2 21c0-3 1.9-5.4 5.2-6" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  tick: <path d="M20 6 9 17l-5-5" />,
  send: <><path d="M22 2 11 13" /><path d="M22 2 15 22l-4-9-9-4 20-7z" /></>,
  cloud: <path d="M17.5 19H9a7 7 0 1 1 6.7-9h1.8a4.5 4.5 0 1 1 0 9Z" />,
  more: <><circle cx="5" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="19" cy="12" r="1.6" /></>,
  gear: <><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1 7 17M17 7l2.1-2.1" /></>,
  info: <><circle cx="12" cy="12" r="10" /><path d="M12 16v-4M12 8h.01" /></>,
};

export function Icon({ name, size = 24, stroke = 2 }: { name: keyof typeof paths | string; size?: number; stroke?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
  );
}

const TABS = [
  { key: 'heute', label: 'Heute', icon: 'check' },
  { key: 'kalender', label: 'Kalender', icon: 'calendar' },
  { key: 'pflanzen', label: 'Pflanzen', icon: 'plant' },
  { key: 'fragen', label: 'Fragen', icon: 'chat' },
  { key: 'mehr', label: 'Mehr', icon: 'more' },
];
const SECTION: Record<string, string> = {
  heute: 'heute', warnung: 'heute', aufgabe: 'heute', kalender: 'kalender', pflanzen: 'pflanzen', pflanze: 'pflanzen',
  neu: 'pflanzen', fragen: 'fragen', mehr: 'mehr', wetter: 'mehr', einstellungen: 'mehr', standorte: 'mehr',
};

export function Nav({ route, urgent }: { route: string; urgent: number }) {
  const current = SECTION[route] ?? 'heute';
  return (
    <>
      <header className="topbar">
        <strong style={{ fontSize: 20, color: 'var(--green)' }}>Garten-Planer</strong>
        <nav aria-label="Hauptnavigation">
          {TABS.map((t) => (
            <a key={t.key} href={`#/${t.key}`} aria-current={current === t.key ? 'page' : undefined}>{t.label}</a>
          ))}
        </nav>
        {urgent > 0 && <a className="pill" href="#/warnung" style={{ background: 'var(--urgent-tint)', color: 'var(--urgent)', fontWeight: 700, textDecoration: 'none' }}>Kältewelle · {urgent} dringend</a>}
      </header>
      <nav className="tabbar" aria-label="Hauptnavigation">
        {TABS.map((t) => (
          <a key={t.key} className="tab" href={`#/${t.key}`} aria-current={current === t.key ? 'page' : undefined}>
            <Icon name={t.icon} stroke={current === t.key ? 2.2 : 2} />{t.label}
          </a>
        ))}
      </nav>
    </>
  );
}

const CAT: Record<Category, string> = {
  Schnitt: 'schnitt', Düngen: 'duengen', Ernte: 'ernte', Pflanzenschutz: 'schutz', Winterschutz: 'winter', Aussaat: 'aussaat',
};
export const catColors = (c: Category) => ({ background: `var(--c-${CAT[c]})`, color: `var(--c-${CAT[c]}-ink)` });

export function Chip({ category, label }: { category: Category; label?: string }) {
  return <span className="chip" style={catColors(category)}>{label ?? category}</span>;
}

export function Back({ href, label }: { href: string; label: string }) {
  return <a className="back" href={href}>‹ {label}</a>;
}

/** § notes from the rule engine (api legal.py), warnings first. */
export function LegalNotes({ notes }: { notes: LegalNote[] }) {
  if (!notes.length) return null;
  const sorted = [...notes].sort((a, b) => (a.severity === b.severity ? 0 : a.severity === 'warn' ? -1 : 1));
  return (
    <div className="stack" style={{ gap: 8 }}>
      {sorted.map((n) => <Legal key={n.code}>{n.text} <span className="tiny" style={{ color: 'inherit' }}>({n.ref})</span></Legal>)}
    </div>
  );
}

export function Legal({ children }: { children: ReactNode }) {
  return <div className="legal"><b className="sign" aria-hidden="true">§</b><span>{children}</span></div>;
}

export function TodoRow({ todo, done, note, onToggle }: { todo: Todo; done: boolean; note?: string; onToggle: () => void }) {
  return (
    <div className={done ? 'todo done' : 'todo'}>
      <button className="check" role="checkbox" aria-checked={done} onClick={onToggle}
        aria-label={done ? `${todo.title}: als offen markieren` : `${todo.title}: als erledigt markieren`}>
        <span>{done && <Icon name="tick" size={16} stroke={3} />}</span>
      </button>
      <a className="todo-body" href={`#/aufgabe/${todo.id}`}>
        <span className="todo-title">{todo.title}</span>
        <span className="small muted">{todo.plantText}</span>
        {done
          ? <span className="small muted">{note || todo.doneNote || 'Erledigt heute'}</span>
          : todo.when && <span className={todo.urgent ? 'when urgent' : 'when'}>{todo.when}</span>}
      </a>
    </div>
  );
}

// ----- real to-dos (API categories) ------------------------------------------

const TASK_CAT: Record<ApiCategory, string> = {
  schnitt: 'schnitt', duengen: 'duengen', ernte: 'ernte', pflanzenschutz: 'schutz', winterschutz: 'winter', aussaat: 'aussaat', sonstiges: '',
};
export const taskColors = (c: ApiCategory) =>
  TASK_CAT[c] ? { background: `var(--c-${TASK_CAT[c]})`, color: `var(--c-${TASK_CAT[c]}-ink)` } : { background: 'var(--surface)', color: 'var(--ink-2)' };

export function TaskChip({ category }: { category: ApiCategory }) {
  return <span className="chip" style={taskColors(category)}>{CATEGORIES[category]}</span>;
}

const MONTHS_DE = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'];
export const monthName = (m: number) => MONTHS_DE[m - 1];
export const deDate = (iso: string) => { const [y, m, d] = iso.split('-').map(Number); return `${d}.${m}.${y}`; };
/** Local (not UTC) calendar date of a timestamp, e.g. ticked at 00:30 → today. */
export const localDay = (ts: string) => new Date(ts).toLocaleDateString('de-DE');
/** YYYY-MM-DD of the local date `days` from today (for date inputs). */
export const localIso = (days = 0) => { const d = new Date(); d.setDate(d.getDate() + days); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

/** "jedes Jahr im November", "jedes Jahr November–Februar", "alle 7 Tage", "einmalig am 5.12.2026" */
export function timingText(t: Pick<TaskIn, 'recurrence' | 'due_date' | 'month_from' | 'month_to' | 'interval_days'>): string {
  if (t.recurrence === 'once') return t.due_date ? `einmalig am ${deDate(t.due_date)}` : 'einmalig';
  if (t.recurrence === 'interval') return t.interval_days === 1 ? 'täglich' : `alle ${t.interval_days} Tage`;
  if (t.month_from === t.month_to) return `jedes Jahr im ${monthName(t.month_from ?? 1)}`;
  return `jedes Jahr ${monthName(t.month_from ?? 1)}–${monthName(t.month_to ?? 1)}`;
}
