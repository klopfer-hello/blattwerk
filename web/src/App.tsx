// App shell: routing, navigation and the to-do state shared by the screens.
// Prototype phase: demo data only; ticks are remembered per device (browser
// storage) so a household member can try the app without losing their clicks.
import { useEffect, useMemo, useState } from 'react';
import { CHAT_TODO, TODOS, type Todo } from './mock/data';
import { Nav, useRoute } from './components/ui';
import { Alert, Today } from './screens/Today';
import { Task } from './screens/Task';
import { Calendar } from './screens/Calendar';
import { AddPlant, PlantDetail, Plants } from './screens/Plants';
import { Chat, Weather } from './screens/More';
import { Settings } from './screens/Settings';

export interface TodoState {
  list: Todo[];
  done: Record<string, boolean>;
  notes: Record<string, string>;
  toggle: (id: string) => void;
  setNote: (id: string, note: string) => void;
  addChatTodo: () => void;
}

const KEY = 'garten-planer-prototype-v1';
interface Saved { done: Record<string, boolean>; notes: Record<string, string>; chatTodo: boolean; welcomed: boolean }
const initial: Saved = { done: Object.fromEntries(TODOS.filter((t) => t.done).map((t) => [t.id, true])), notes: {}, chatTodo: false, welcomed: false };

function load(): Saved {
  try { return { ...initial, ...JSON.parse(localStorage.getItem(KEY) ?? '{}') }; } catch { return initial; }
}

export function App() {
  const route = useRoute();
  const [saved, setSaved] = useState<Saved>(load);
  const [toast, setToast] = useState('');
  useEffect(() => { try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch { /* private mode: keep in memory */ } }, [saved]);
  useEffect(() => {
    const on = (e: Event) => { setToast((e as CustomEvent<string>).detail); window.setTimeout(() => setToast(''), 2500); };
    window.addEventListener('prototype-note', on);
    return () => window.removeEventListener('prototype-note', on);
  }, []);

  const state: TodoState = useMemo(() => ({
    list: saved.chatTodo ? [CHAT_TODO, ...TODOS] : TODOS,
    done: saved.done,
    notes: saved.notes,
    toggle: (id) => setSaved((s) => ({ ...s, done: { ...s.done, [id]: !s.done[id] } })),
    setNote: (id, note) => setSaved((s) => ({ ...s, notes: { ...s.notes, [id]: note } })),
    addChatTodo: () => setSaved((s) => ({ ...s, chatTodo: true })),
  }), [saved]);

  const [page, arg] = route;
  const urgent = state.list.filter((t) => t.urgent && !state.done[t.id]).length;
  const screen = (() => {
    switch (page) {
      case 'warnung': return <Alert state={state} />;
      case 'aufgabe': return <Task key={arg} id={arg ?? ''} state={state} />;
      case 'kalender': return <Calendar />;
      case 'pflanzen': return <Plants />;
      case 'pflanze': return <PlantDetail key={arg} id={arg ?? ''} />;
      case 'neu': return <AddPlant />;
      case 'fragen': return <Chat state={state} />;
      case 'wetter': return <Weather />;
      case 'einstellungen': return <Settings />;
      default: return <Today state={state} />;
    }
  })();

  return (
    <div className="app">
      <div className="banner" role="note">
        <span>Prototyp mit Beispieldaten</span>
        <button onClick={() => setSaved((s) => ({ ...s, welcomed: false }))}>Was ist das?</button>
        <button onClick={() => setSaved({ ...initial, welcomed: true })}>Zurücksetzen</button>
      </div>
      <Nav route={page} urgent={urgent} />
      <main>{screen}</main>
      {!saved.welcomed && <Welcome onClose={() => setSaved((s) => ({ ...s, welcomed: true }))} />}
      {toast && <div role="status" style={{ position: 'fixed', left: 16, right: 16, bottom: 'calc(100px + env(safe-area-inset-bottom))', margin: '0 auto', maxWidth: 420, padding: '12px 16px', borderRadius: 12, background: 'var(--ink)', color: 'var(--bg)', textAlign: 'center', zIndex: 30 }}>{toast}</div>}
    </div>
  );
}

function Welcome({ onClose }: { onClose: () => void }) {
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="welcome-title" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 40, display: 'flex', alignItems: 'flex-end', justifyContent: 'center' }}>
      <div className="stack" style={{ background: 'var(--bg)', width: '100%', maxWidth: 520, borderRadius: '20px 20px 0 0', padding: '24px 20px calc(24px + env(safe-area-inset-bottom))', gap: 14 }}>
        <h2 id="welcome-title" style={{ fontSize: 24 }}>Willkommen im Garten-Planer</h2>
        <p>Das ist eine <strong>Vorschau</strong>, wie die App aussehen soll. Alle Pflanzen und Termine sind Beispiele.</p>
        <ul style={{ margin: 0, paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <li><strong>Heute</strong>: die Aufgaben dieses Monats. Kästchen antippen = erledigt. Antippen des Textes zeigt die Anleitung.</li>
          <li><strong>Kalender</strong>: was in jedem Monat ansteht.</li>
          <li><strong>Pflanzen</strong>: alle Pflanzen mit Pflegeplan und Schädlingen.</li>
          <li><strong>Fragen</strong>: hier beantwortet später eine KI Fragen zum Garten.</li>
        </ul>
        <p className="small muted">Tipp: Im Browser-Menü „Zum Home-Bildschirm“ wählen – dann öffnet sich die App wie eine normale App.</p>
        <p className="small muted">Was fehlt, was ist unklar? Einfach sagen – genau dafür ist die Vorschau da.</p>
        <button className="btn primary" onClick={onClose} autoFocus>Los geht’s</button>
      </div>
    </div>
  );
}
