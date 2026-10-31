import { useEffect, useState } from 'react';
import { api, type GardenSettings } from '../api';
import { FERTILISER } from './Settings';
import { NIGHTS, SEASON, SEASONS, SENSORS } from '../mock/data';
import { Back, Icon } from '../components/ui';

export function Chat() {
  const [answer, setAnswer] = useState<'yes' | 'no' | null>(null);
  return (
    <div className="page">
      <header className="stack" style={{ gap: 6 }}>
        <span className="chip" style={{ background: 'var(--legal-tint)', color: 'var(--legal-ink)' }}>Vorschau – der Garten-Chat kommt mit M8</span>
        <h1 className="title-s">Fragen</h1>
        <span className="small muted">Kennt später deine Pflanzen, Aufgaben und das Wetter. So soll es aussehen:</span>
      </header>

      <div className="bubble-me">Was muss vor dem Frost am Dienstag noch passieren?</div>
      <div className="bubble-ai">
        <span>Bis Montagabend <strong>zwei Dinge</strong>:</span>
        <span>• <strong>Dahlie ‘Café au Lait’</strong> ausgraben – die Knollen erfrieren ab −2 °C.</span>
        <span>• <strong>Oleander</strong> ins Winterquartier – drei Nächte bis −6 °C sind zu viel.</span>
        <span className="tiny">Beispiel-Antwort</span>
      </div>
      <div className="outline stack" style={{ alignSelf: 'flex-start', maxWidth: '88%', border: '2px solid var(--green)', gap: 10 }}>
        <span>Soll ich eine Aufgabe anlegen?<br /><strong>„Gemüsebeet 1 mit Vlies abdecken“</strong></span>
        {answer === null ? (
          <div className="grid2" style={{ gap: 8 }}>
            <button className="btn" style={{ background: 'var(--green)', color: 'var(--green-ink)', border: 0, fontWeight: 700 }} onClick={() => setAnswer('yes')}>Ja, anlegen</button>
            <button className="btn" onClick={() => setAnswer('no')}>Nein</button>
          </div>
        ) : <span className="muted">{answer === 'yes' ? 'In der Vorschau wird nichts angelegt.' : 'Nicht angelegt.'}</span>}
      </div>
      <div className="chatbar">
        <label className="sr-only" htmlFor="msg">Nachricht</label>
        <input id="msg" className="input" style={{ borderRadius: 24 }} placeholder="Kommt mit M8" disabled />
        <button className="btn" aria-label="Senden" disabled style={{ width: 48, padding: 0, borderRadius: 24 }}><Icon name="send" size={20} /></button>
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
      <Back href="#/mehr" label="Mehr" />
      <h1 className="title-s">Wetter &amp; Jahreszeit</h1>
      <span className="chip" style={{ background: 'var(--legal-tint)', color: 'var(--legal-ink)' }}>Vorschau mit Beispielwerten – echte Daten mit M6/M7</span>
      <a href="#/warnung" className="small">So sieht eine Frost-Warnung aus ›</a>

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

// "Mehr" tab: everything that is not daily use. Later also Standorte, Backup.
export function More({ onWelcome }: { onWelcome: () => void }) {
  const [version, setVersion] = useState('');
  useEffect(() => {
    fetch('/api/healthz').then((r) => r.json()).then((h: { version?: string }) => setVersion(h.version ?? ''), () => setVersion(''));
  }, []);
  const rows = [
    { href: '#/einstellungen', icon: 'gear', title: 'Einstellungen', text: 'Ort, Bundesland, Dünger, Baumschutz, Benachrichtigungen' },
    { href: '#/standorte', icon: 'plant', title: 'Standorte', text: 'Orte im Garten mit Sonne/Schatten' },
    { href: '#/wetter', icon: 'cloud', title: 'Wetter & Jahreszeit', text: 'Messwerte, Frostnächte, phänologischer Kalender' },
  ];
  return (
    <div className="page">
      <h1 className="title">Mehr</h1>
      <nav className="stack" aria-label="Mehr">
        {rows.map((r) => (
          <a key={r.href} href={r.href} className="card" style={{ display: 'flex', gap: 14, alignItems: 'center', textDecoration: 'none', color: 'var(--ink)', minHeight: 64 }}>
            <span style={{ color: 'var(--green)' }}><Icon name={r.icon} /></span>
            <span className="stack" style={{ gap: 2, flex: 1 }}><strong style={{ fontSize: 17 }}>{r.title}</strong><span className="small muted">{r.text}</span></span>
            <span aria-hidden="true" style={{ fontSize: 22, color: 'var(--muted)' }}>›</span>
          </a>
        ))}
        <button className="card" onClick={onWelcome} style={{ display: 'flex', gap: 14, alignItems: 'center', minHeight: 64, cursor: 'pointer', textAlign: 'left' }}>
          <span style={{ color: 'var(--green)' }}><Icon name="info" /></span>
          <span className="stack" style={{ gap: 2 }}><strong style={{ fontSize: 17 }}>Kurze Erklärung</strong><span className="small muted">Die Begrüßung mit den Tipps noch einmal zeigen</span></span>
        </button>
      </nav>
      <span className="tiny">Garten-Planer {version || '…'}</span>
    </div>
  );
}
