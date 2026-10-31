import { useEffect, useState } from 'react';
import { api, type GardenSettings } from '../api';
import { FERTILISER } from './Settings';
import { CHAT_TODO, NIGHTS, SEASON, SEASONS, SENSORS } from '../mock/data';
import { Back, Icon } from '../components/ui';
import type { TodoState } from '../App';

export function Chat({ state }: { state: TodoState }) {
  const added = state.list.some((t) => t.id === CHAT_TODO.id);
  const [declined, setDeclined] = useState(false);
  return (
    <div className="page">
      <header className="between">
        <div className="stack" style={{ gap: 2 }}>
          <h1 className="title-s">Fragen</h1>
          <span className="small muted">Kennt deine Pflanzen, Aufgaben und das Wetter</span>
        </div>
      </header>

      <div className="bubble-me">Was muss vor dem Frost am Dienstag noch passieren?</div>
      <div className="bubble-ai">
        <span>Bis Montagabend <strong>zwei Dinge</strong>:</span>
        <span>• <strong>Dahlie ‘Café au Lait’</strong> ausgraben – die Knollen erfrieren ab −2 °C.</span>
        <span>• <strong>Oleander</strong> ins Winterquartier – drei Nächte bis −6 °C sind zu viel.</span>
        <span>Dein <strong>Feldsalat</strong> in Gemüsebeet 1 ist erst 3 Wochen alt. Ein Vlies schützt ihn.</span>
        <span className="tiny">Quelle: DWD-Vorhersage von heute 17:00, deine Pflanzenliste</span>
      </div>
      <div className="outline stack" style={{ alignSelf: 'flex-start', maxWidth: '88%', border: '2px solid var(--green)', gap: 10 }}>
        <span>Soll ich eine Aufgabe anlegen?<br /><strong>„{CHAT_TODO.title}“ · bis Mo 2.11.</strong></span>
        {added && <a href="#/heute" style={{ fontWeight: 700 }}>✓ Angelegt – unter „Heute“ ansehen ›</a>}
        {declined && !added && <span className="muted">Nicht angelegt.</span>}
        {!added && !declined && (
          <div className="grid2" style={{ gap: 8 }}>
            <button className="btn" style={{ background: 'var(--green)', color: 'var(--green-ink)', border: 0, fontWeight: 700 }} onClick={state.addChatTodo}>Ja, anlegen</button>
            <button className="btn" onClick={() => setDeclined(true)}>Nein</button>
          </div>
        )}
      </div>

      <div className="row">
        <button className="btn small">Was säe ich 2027 in Beet 2?</button>
        <button className="btn small">Warum blüht meine Rose kaum?</button>
      </div>
      <div className="chatbar">
        <label className="sr-only" htmlFor="msg">Nachricht</label>
        <input id="msg" className="input" style={{ borderRadius: 24 }} placeholder="Frage zum Garten … (im Prototyp ohne Funktion)" />
        <button className="btn" aria-label="Senden" style={{ width: 48, padding: 0, borderRadius: 24, background: 'var(--green)', color: 'var(--green-ink)', border: 0 }}><Icon name="send" size={20} /></button>
      </div>
    </div>
  );
}

export function Weather() {
  const [s, setS] = useState<GardenSettings | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => { api.settings().then(setS, () => setFailed(true)); }, []);
  const place = s && [s.location.plz, s.location.ort].filter(Boolean).join(' ');
  const settings = s && [
    ['Ort', place || 'noch nicht gesetzt'],
    ['Bundesland', s.location.bundesland ?? 'noch nicht gesetzt'],
    ['Baumschutzsatzung', s.legal.baumschutz_girth_cm ? `ab ${s.legal.baumschutz_girth_cm} cm Umfang` : 'keine'],
    ['Dünger', FERTILISER[s.preferences.fertiliser]],
    ['Push bei Wetter-Warnungen', s.notifications.weather_push ? 'an' : 'aus'],
  ];
  return (
    <div className="page">
      <Back href="#/heute" label="Heute" />
      <h1 className="title-s">Wetter &amp; Jahreszeit</h1>

      <section className="stack">
        <h2 className="eyebrow">Garten jetzt · Home Assistant</h2>
        <div className="grid3">
          {SENSORS.map((s) => <div key={s.label} className="box" style={{ padding: 10 }}><div className="tiny">{s.label}</div><strong style={{ fontSize: 18 }}>{s.value}</strong></div>)}
        </div>
        <span className="tiny">Aktualisiert vor 3 Min.</span>
      </section>

      <section className="stack">
        <h2 className="eyebrow">Nächste 7 Nächte (DWD)</h2>
        <div className="nights">
          {NIGHTS.map((n) => (
            <div key={n.day} className="box" style={{ padding: '8px 0', textAlign: 'center', background: n.t < 0 ? 'var(--frost)' : 'var(--surface)', color: n.t < 0 ? '#FFFFFF' : 'var(--ink)' }}>
              <div className="small">{n.day}</div><strong>{n.t > 0 ? '+' : n.t < 0 ? '−' : ''}{Math.abs(n.t)}°</strong>
            </div>
          ))}
        </div>
      </section>

      <section className="stack">
        <h2 className="eyebrow">Phänologischer Kalender</h2>
        <div className="stack" style={{ gap: 2 }}>
          {SEASONS.map((s, i) => (
            <div key={s} className={i === SEASON.index ? 'season now' : i < SEASON.index ? 'season past' : 'season'}>
              <span>{s}</span><span className="small">{i === SEASON.index ? 'jetzt' : i < SEASON.index ? '✓' : ''}</span>
            </div>
          ))}
        </div>
        <span className="small" style={{ color: 'var(--ink-2)' }}>{SEASON.name} seit {SEASON.since} (Laubfall), <strong>{SEASON.delayDays} Tage später als im Mittel</strong>. Quellen: DWD-Meldungen der Region, Wärmesumme, deine Beobachtungen.</span>
        <button className="btn" style={{ borderColor: 'var(--green)', color: 'var(--green)', fontWeight: 700 }}>Beobachtung melden (z. B. „Hasel blüht“)</button>
      </section>

      <section className="stack" style={{ gap: 0, borderTop: '1px solid var(--line)', paddingTop: 14 }}>
        <h2 style={{ fontSize: 20, marginBottom: 6 }}>Einstellungen</h2>
        {failed && <p className="box">Einstellungen konnten nicht geladen werden.</p>}
        {settings?.map(([k, v]) => (
          <a key={k} href="#/einstellungen" className="setrow" style={{ textDecoration: 'none', color: 'var(--ink)' }}><span>{k}</span><span className="muted">{v} ›</span></a>
        ))}
        <a href="#/einstellungen" className="btn" style={{ marginTop: 12 }}>Einstellungen bearbeiten</a>
      </section>
    </div>
  );
}
