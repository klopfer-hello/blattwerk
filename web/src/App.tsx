// App shell: routing, navigation, the welcome sheet. Since M3 the checklist,
// plants and calendar are real data from the API; weather (M6) and the garden
// chat (M8) are still previews and say so on their screens.
import { useEffect, useState } from 'react';
import { Nav, useRoute } from './components/ui';
import { Alert, Today } from './screens/Today';
import { TaskForm, TodoDetail } from './screens/Task';
import { Calendar } from './screens/Calendar';
import { PlantDetail, PlantForm, Plants, Standorte } from './screens/Plants';
import { Chat, More, Weather } from './screens/More';
import { Settings } from './screens/Settings';

const KEY = 'garten-planer-welcomed-v2';
function seen(): boolean {
  try { return localStorage.getItem(KEY) === '1'; } catch { return false; }
}

export function App() {
  const route = useRoute();
  const [welcomed, setWelcomed] = useState(seen);
  useEffect(() => { try { localStorage.setItem(KEY, welcomed ? '1' : '0'); } catch { /* private mode */ } }, [welcomed]);

  const [page, arg, sub] = route;
  const screen = (() => {
    switch (page) {
      case 'warnung': return <Alert />;
      case 'aufgabe': return <TodoDetail key={arg} id={arg ?? ''} />;
      case 'aufgabe-neu': return <TaskForm key={`new-${arg ?? ''}`} plantId={arg} />;
      case 'aufgabe-bearbeiten': return <TaskForm key={`edit-${arg}`} id={arg} />;
      case 'kalender': return <Calendar />;
      case 'pflanzen': return <Plants />;
      case 'pflanze': return sub === 'bearbeiten' ? <PlantForm key={`edit-${arg}`} id={arg} /> : <PlantDetail key={arg} id={arg ?? ''} />;
      case 'neu': return <PlantForm key="new" />;
      case 'standorte': return <Standorte />;
      case 'fragen': return <Chat />;
      case 'wetter': return <Weather />;
      case 'einstellungen': return <Settings />;
      case 'mehr': return <More onWelcome={() => setWelcomed(false)} />;
      default: return <Today />;
    }
  })();

  return (
    <div className="app">
      <Nav route={page} urgent={0} />
      <main>{screen}</main>
      {!welcomed && <Welcome onClose={() => setWelcomed(true)} />}
    </div>
  );
}

function Welcome({ onClose }: { onClose: () => void }) {
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="welcome-title" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 40, display: 'flex', alignItems: 'flex-end', justifyContent: 'center' }}>
      <div className="stack" style={{ background: 'var(--bg)', width: '100%', maxWidth: 520, borderRadius: '20px 20px 0 0', padding: '24px 20px calc(24px + env(safe-area-inset-bottom))', gap: 14 }}>
        <h2 id="welcome-title" style={{ fontSize: 24 }}>Willkommen im Garten-Planer</h2>
        <ul style={{ margin: 0, paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <li><strong>Heute</strong>: die Aufgaben dieses Monats. Kästchen antippen = erledigt, Text antippen = Anleitung, Notiz, Verschieben.</li>
          <li><strong>Kalender</strong>: was in jedem Monat ansteht.</li>
          <li><strong>Pflanzen</strong>: eure Pflanzen und Standorte, mit ihren Aufgaben.</li>
          <li><strong>Fragen</strong>: hier beantwortet später eine KI Fragen zum Garten (noch Vorschau).</li>
          <li><strong>Mehr</strong>: Einstellungen, Standorte, Wetter (noch Vorschau).</li>
        </ul>
        <p className="small muted">Tipp: Im Browser-Menü „Zum Home-Bildschirm“ wählen – dann öffnet sich die App wie eine normale App.</p>
        <button className="btn primary" onClick={onClose} autoFocus>Los geht’s</button>
      </div>
    </div>
  );
}
