import { useEffect, useState } from 'react';
import { api, type GardenSettings, type Reading, type Weather as WeatherData } from '../api';
import { FERTILISER } from './Settings';
import { SEASON, SEASONS } from '../mock/data';
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

const num = (v: number | null | undefined, unit: string, digits = 1) =>
  v === null || v === undefined ? '–' : `${v.toLocaleString('de-DE', { maximumFractionDigits: digits })} ${unit}`;
const ago = (iso: string) => {
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  return min < 2 ? 'gerade eben' : min < 120 ? `vor ${min} Min.` : `seit ${new Date(iso).toLocaleString('de-DE', { day: 'numeric', month: 'numeric', hour: '2-digit', minute: '2-digit' })}`;
};
const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const dayName = (iso: string) => {
  const today = new Date();
  const tomorrow = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1);
  return iso === isoDay(today) ? 'Heute' : iso === isoDay(tomorrow) ? 'Morgen' : new Date(`${iso}T12:00:00`).toLocaleDateString('de-DE', { weekday: 'long' });
};
const since = (v: string) => (v === 'unbekannt' ? 'seit über einem Tag' : ago(v));

function WeatherNow() {
  const [w, setW] = useState<WeatherData | null>(null);
  const [failed, setFailed] = useState(false);
  const [, setTick] = useState(0);  // re-render for "vor x Min."
  useEffect(() => {   // every 5 min and when the app comes back to the front; errors keep the last answer
    let current = true;
    const load = () => api.weather().then((x) => { if (current) { setW(x); setFailed(false); } }, () => { if (current) setFailed(true); });
    const onVisible = () => { if (document.visibilityState === 'visible') load(); };
    load();
    const t = window.setInterval(load, 5 * 60 * 1000);
    const m = window.setInterval(() => setTick((n) => n + 1), 60 * 1000);
    document.addEventListener('visibilitychange', onVisible);
    return () => { current = false; window.clearInterval(t); window.clearInterval(m); document.removeEventListener('visibilitychange', onVisible); };
  }, []);
  if (!w && failed) return <p className="box">Wetterdaten sind gerade nicht erreichbar. Aufgaben richten sich solange nach dem Kalender.</p>;
  if (w && !w.available) return <p className="box">Wetterdaten sind gerade nicht verfügbar. Aufgaben richten sich solange nach dem Kalender.</p>;
  if (!w?.current) return <p className="box">Lädt …</p>;
  const c = w.current;
  const tiles: [string, Reading | undefined, string, number][] = [
    ['Draußen', c.outdoor, '°C', 1], ['Gewächshaus', c.greenhouse, '°C', 1], ['Regen heute', c.rain_day, 'mm', 1],
    ['Wind', c.wind, 'km/h', 0], ['Böen', c.gust, 'km/h', 0], ['Sonne', c.solar, 'W/m²', 0],
  ];
  const newest = [c.outdoor, c.greenhouse, ...c.soil].filter(Boolean).map((r) => r!.at).sort().pop();
  return (
    <>
      <section className="stack">
        <h2 className="eyebrow">Garten jetzt · Home Assistant</h2>
        {failed && <p className="small muted" role="status">Aktualisieren gerade nicht möglich – letzte bekannte Werte.</p>}
        {w.stale?.sensors && <p className="box" role="status" style={{ color: 'var(--urgent)' }}>Messwerte veraltet {since(w.stale.sensors)}.</p>}
        <div className="grid3">
          {tiles.map(([k, r, unit, digits]) => (
            <div key={k} className="box" style={{ padding: 10, opacity: r?.stale ? 0.55 : 1 }}>
              <div className="tiny">{k}{r?.stale ? ' · alt' : ''}</div><strong style={{ fontSize: 18 }}>{num(r?.value, unit, digits)}</strong>
            </div>
          ))}
        </div>
        {c.soil.length > 0 && (
          <div className="grid2" style={{ gap: 8 }}>
            {c.soil.map((s) => (
              <div key={s.label} className="box" style={{ padding: 10, opacity: s.stale ? 0.55 : 1 }}>
                <div className="tiny">Bodenfeuchte {s.label}{s.stale ? ' · alt' : ''}</div><strong style={{ fontSize: 18 }}>{num(s.value, '%', 0)}</strong>
              </div>
            ))}
          </div>
        )}
        {newest && !w.stale?.sensors && <span className="tiny">Aktualisiert {ago(newest)}</span>}
      </section>
      <section className="stack">
        <h2 className="eyebrow">Vorhersage</h2>
        {w.stale?.forecast === 'unbekannt' && !w.days?.length && <p className="box" role="status">Noch keine Vorhersage – sie kommt stündlich vom DWD und von Open-Meteo.</p>}
        {w.stale?.forecast && (w.days?.length ?? 0) > 0 && <p className="box" role="status" style={{ color: 'var(--urgent)' }}>Vorhersage veraltet {since(w.stale.forecast)}.</p>}
        <div className="stack" style={{ gap: 6 }}>
          {w.days?.map((d) => (
            <div key={d.date} className="box between" style={{ padding: '10px 12px', borderLeft: d.frost ? '6px solid var(--frost)' : undefined }}>
              <span className="stack" style={{ gap: 2 }}>
                <strong>{dayName(d.date)}</strong>
                <span className="small muted">{d.frost ? 'Frost' + (d.ground_min !== null && (d.t_min ?? 1) > 0 ? ' am Boden' : '') + ' · ' : ''}Regen {num(d.precip, 'mm')} · Böen bis {num(d.gust_max, 'km/h', 0)}</span>
              </span>
              <span style={{ textAlign: 'right' }}>
                <strong style={{ color: d.frost ? 'var(--frost)' : 'var(--ink)' }}>{num(d.t_min, '°', 0)}</strong>
                <span className="muted"> / {num(d.t_max, '°', 0)}</span>
              </span>
            </div>
          ))}
        </div>
        {w.days && w.days.length > 0 && (
          <span className="tiny">Quellen: {[w.days.some((d) => d.source === 'dwd') && 'Deutscher Wetterdienst (MOSMIX)', w.days.some((d) => d.source === 'openmeteo') && 'Open-Meteo.com (CC BY 4.0)'].filter(Boolean).join(', ')}</span>
        )}
      </section>
    </>
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
      <WeatherNow />
      <a href="#/warnung" className="small">Wetterwarnungen ›</a>

      <section className="stack">
        <h2 className="eyebrow">Phänologischer Kalender · Vorschau (M7)</h2>
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
