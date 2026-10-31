import { ALERT, MONTHS, NIGHTS, SENSORS, SEASON, TODAY, type Category } from '../mock/data';
import { Back, Icon, TodoRow } from '../components/ui';
import type { TodoState } from '../App';

const GROUPS: { key: string; label: string; match: (c: Category, urgent?: boolean) => boolean }[] = [
  { key: 'urgent', label: 'Dringend wegen Frost', match: (_c, u) => !!u },
  { key: 'schutz', label: 'Pflanzenschutz', match: (c, u) => !u && c === 'Pflanzenschutz' },
  { key: 'winter', label: 'Winterschutz', match: (c, u) => !u && c === 'Winterschutz' },
  { key: 'pflege', label: 'Schnitt, Düngen, Ernte', match: (c, u) => !u && ['Schnitt', 'Düngen', 'Ernte'].includes(c) },
  { key: 'beet', label: 'Aussaat & Beete', match: (c, u) => !u && c === 'Aussaat' },
];

export function Today({ state }: { state: TodoState }) {
  const open = state.list.filter((t) => !state.done[t.id]);
  const done = state.list.filter((t) => state.done[t.id]);
  const urgentOpen = open.filter((t) => t.urgent).length;
  const pct = Math.round((done.length / state.list.length) * 100);
  return (
    <div className="page">
      <header className="stack" style={{ gap: 12 }}>
        <div className="between">
          <span className="muted">{TODAY.weekday}, {TODAY.date}</span>
          <a href="#/wetter" className="btn small" aria-label="Wetter und Einstellungen"><Icon name="cloud" size={20} />Wetter</a>
        </div>
        <h1 className="title">ToDos im {MONTHS[TODAY.month]}</h1>
        <a href="#/wetter" className="row" style={{ textDecoration: 'none' }}>
          <span className="pill" style={{ background: 'var(--green-tint)', color: 'var(--green)', fontWeight: 700 }}>
            <Icon name="leaf" size={16} />{SEASON.name} · {SEASON.delayDays} Tage später als normal</span>
          <span className="pill" style={{ background: 'var(--surface)', color: 'var(--ink)' }}>
            <Icon name="thermo" size={16} />{SENSORS[0].value} · Boden {SENSORS[1].value} · Gewächshaus {SENSORS[2].value}</span>
        </a>
      </header>

      {urgentOpen > 0 && (
        <a className="alert-card" href="#/warnung">
          <span className="alert-icon"><Icon name="frost" size={22} /></span>
          <span className="stack" style={{ gap: 4 }}>
            <strong style={{ fontSize: 17, color: 'var(--urgent)' }}>{ALERT.short}</strong>
            <span>Bis −6 °C in drei Nächten – ungewöhnlich früh. {urgentOpen} dringende {urgentOpen === 1 ? 'Aufgabe' : 'Aufgaben'}.</span>
            <span className="small" style={{ fontWeight: 700, color: 'var(--urgent)' }}>Warnung ansehen ›</span>
          </span>
        </a>
      )}

      <div className="stack">
        <div className="between"><strong>{done.length} von {state.list.length} erledigt</strong></div>
        <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}><div style={{ width: `${pct}%` }} /></div>
      </div>

      {GROUPS.map((g) => {
        const items = open.filter((t) => g.match(t.category, t.urgent));
        if (!items.length) return null;
        return (
          <section key={g.key} className="stack">
            <h2 className={g.key === 'urgent' ? 'eyebrow urgent' : 'eyebrow'}>{g.label}</h2>
            {items.map((t) => <TodoRow key={t.id} todo={t} done={false} onToggle={() => state.toggle(t.id)} />)}
          </section>
        );
      })}
      {open.length === 0 && <p className="box">Alles erledigt für diesen Monat.</p>}

      {done.length > 0 && (
        <section className="stack">
          <h2 className="eyebrow">Erledigt</h2>
          {done.map((t) => <TodoRow key={t.id} todo={t} done note={state.notes[t.id]} onToggle={() => state.toggle(t.id)} />)}
        </section>
      )}
    </div>
  );
}

export function Alert({ state }: { state: TodoState }) {
  const urgent = state.list.filter((t) => t.urgent);
  return (
    <div className="page">
      <Back href="#/heute" label="Heute" />
      <div className="stack">
        <span className="chip" style={{ background: 'var(--urgent-tint)', color: 'var(--urgent)' }}>Wetter-Warnung · dringend</span>
        <h1 className="title-s">{ALERT.title}</h1>
        <p style={{ color: 'var(--ink-2)' }}>{ALERT.text}</p>
      </div>

      <div className="box stack" style={{ gap: 12 }}>
        <span className="small muted" style={{ fontWeight: 700 }}>Tiefstwerte (DWD-Vorhersage, Stand {ALERT.forecastAt})</span>
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
        <span className="tiny">Blau = Frost.</span>
      </div>

      <section className="stack">
        <h2 className="eyebrow urgent">Jetzt erledigen</h2>
        {urgent.map((t) => <TodoRow key={t.id} todo={t} done={!!state.done[t.id]} note={state.notes[t.id]} onToggle={() => state.toggle(t.id)} />)}
      </section>

      <section className="outline stack" style={{ gap: 4 }}>
        <h2 style={{ fontSize: 16 }}>Nicht betroffen</h2>
        <span style={{ color: 'var(--ink-2)' }}>{ALERT.notAffected}</span>
      </section>

      <section className="stack" style={{ gap: 6 }}>
        <span className="tiny">So kam die Push-Nachricht aufs Handy:</span>
        <div style={{ padding: '12px 14px', borderRadius: 18, background: '#2B2F2C', color: '#FFFFFF', display: 'flex', gap: 12 }}>
          <img src="/icon-192.png" alt="" width={36} height={36} style={{ borderRadius: 9 }} />
          <span className="stack small" style={{ gap: 2 }}>
            <span className="between" style={{ color: '#C9D1CB' }}><span>Garten-Planer</span><span>{ALERT.push.time}</span></span>
            <strong style={{ fontSize: 15 }}>{ALERT.push.title}</strong>
            <span>{ALERT.push.body}</span>
          </span>
        </div>
        <span className="tiny">Nur eine Nachricht pro Ereignis. Ändert sich die Vorhersage, wird die Warnung aktualisiert.</span>
      </section>
    </div>
  );
}
