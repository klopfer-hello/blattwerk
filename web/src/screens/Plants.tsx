import { useState } from 'react';
import { MONTHS, NAME_SUGGESTIONS, PLANTS, STANDORTE, plantById, standortById, type Light } from '../mock/data';
import { Back, Chip, Icon, Legal } from '../components/ui';

const LIGHT: Record<Light, { bg: string; fg: string }> = {
  sonnig: { bg: '#FDF1CF', fg: '#6B4A00' }, halbschattig: { bg: '#E9EEF0', fg: '#2F4550' }, schattig: { bg: '#E1E4EA', fg: '#2B3244' },
};
const LightChip = ({ light }: { light: Light }) => <span className="chip" style={{ background: LIGHT[light].bg, color: LIGHT[light].fg }}>{light}</span>;

export function Plants() {
  const [q, setQ] = useState('');
  const needle = q.trim().toLowerCase();
  const match = (p: (typeof PLANTS)[number]) => !needle || `${p.name} ${p.latin}`.toLowerCase().includes(needle);
  const sites = STANDORTE.map((s) => ({ ...s, plants: PLANTS.filter((p) => p.standortId === s.id && match(p)) })).filter((s) => s.plants.length);
  return (
    <div className="page">
      <header className="stack" style={{ gap: 12 }}>
        <div className="between">
          <h1 className="title">Pflanzen</h1>
          <a href="#/neu" className="btn primary" style={{ minHeight: 44, fontSize: 16, borderRadius: 22 }}><Icon name="plus" size={18} stroke={2.5} />Neu</a>
        </div>
        <label className="sr-only" htmlFor="q">Pflanze suchen</label>
        <input id="q" type="search" className="input" placeholder="Suchen: deutsch oder lateinisch" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="small muted">{PLANTS.length} Pflanzen · {STANDORTE.length} Standorte (Beispieldaten)</span>
      </header>
      {sites.map((s) => (
        <section key={s.id} className="stack">
          <div className="between"><h2 style={{ fontSize: 18 }}>{s.name}</h2><LightChip light={s.light} /></div>
          {s.plants.map((p) => (
            <a key={p.id} href={`#/pflanze/${p.id}`} className="card between" style={{ textDecoration: 'none', color: 'var(--ink)' }}>
              <span className="stack" style={{ gap: 3, minWidth: 0 }}>
                <strong style={{ fontSize: 17 }}>{p.name}</strong>
                <span className="small muted" style={{ fontStyle: 'italic' }}>{p.latin}</span>
                <span className="small" style={{ color: 'var(--green)' }}>Nächstes: {p.next}</span>
              </span>
              <span aria-hidden="true" style={{ fontSize: 22, color: 'var(--muted)' }}>›</span>
            </a>
          ))}
        </section>
      ))}
      {sites.length === 0 && <p className="box">Keine Pflanze gefunden. <a href="#/neu">Neu anlegen?</a></p>}
    </div>
  );
}

export function PlantDetail({ id }: { id: string }) {
  const p = plantById(id);
  const [tab, setTab] = useState<'plan' | 'pests' | 'history'>('plan');
  if (!p) return <div className="page"><Back href="#/pflanzen" label="Pflanzen" /><p>Pflanze nicht gefunden.</p></div>;
  const site = standortById(p.standortId);
  const facts = [['Standort', `${site?.name} · ${site?.light}`], ['Form', p.form], ['Gepflanzt', String(p.planted)], ['Winterhart', p.hardy]];
  return (
    <div className="page">
      <Back href="#/pflanzen" label="Pflanzen" />
      <div className="stack" style={{ gap: 4 }}>
        <h1 className="title-s">{p.name}</h1>
        <span className="muted" style={{ fontStyle: 'italic' }}>{p.latin}</span>
      </div>
      <div className="grid2" style={{ gap: 8 }}>
        {facts.map(([k, v]) => <div key={k} className="box" style={{ padding: '10px 12px' }}><div className="tiny">{k}</div><strong style={{ fontSize: 15 }}>{v}</strong></div>)}
      </div>
      <div className="tabs" role="tablist">
        {([['plan', 'Pflegeplan'], ['pests', 'Schädlinge'], ['history', 'Verlauf']] as const).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>

      {tab === 'plan' && (
        <div className="stack" style={{ gap: 4 }}>
          {p.woody && p.id === 'rhapsodie' && <Legal>Regelprüfung: 1 Aufgabe angepasst. „Starker Verjüngungsschnitt“ von April auf Februar verschoben (§ 39 BNatSchG).</Legal>}
          {p.plan.map((t) => (
            <div key={t.title} className="planrow">
              <strong style={{ color: 'var(--green)' }}>{MONTHS[t.month].slice(0, 3)}</strong>
              <span className="stack" style={{ gap: 3 }}><Chip category={t.category} /><strong>{t.title}</strong><span className="small muted">{t.detail}</span></span>
            </div>
          ))}
          <div className="grid2" style={{ paddingTop: 10 }}>
            <button className="btn">Eigene Aufgabe</button>
            <button className="btn">Plan neu erstellen</button>
          </div>
          <span className="tiny">Erstellt von Claude für Sorte, Form und Standort dieser Pflanze. Kein Gießen – das planst du selbst.</span>
        </div>
      )}
      {tab === 'pests' && (
        <div className="stack" style={{ gap: 10 }}>
          {p.pests.length === 0 && <p className="box">Keine typischen Schädlinge oder Krankheiten bekannt.</p>}
          {p.pests.map((x) => (
            <div key={x.name} className="outline stack" style={{ gap: 6 }}>
              <div className="between"><strong style={{ fontSize: 17 }}>{x.name}</strong><span className="tiny">{x.time}</span></div>
              <span><strong>Vorbeugen:</strong> {x.prevent}</span>
              <span><strong>Bei Befall:</strong> {x.treat}</span>
            </div>
          ))}
        </div>
      )}
      {tab === 'history' && (
        <div className="stack" style={{ gap: 0 }}>
          {p.history.length === 0 && <p className="box">Noch nichts erledigt.</p>}
          {p.history.map((h) => (
            <div key={h.date + h.title} className="planrow" style={{ gridTemplateColumns: '72px minmax(0, 1fr)' }}>
              <span className="small muted">{h.date}</span>
              <span className="stack" style={{ gap: 2 }}><strong>✓ {h.title}</strong>{h.note && <span className="small muted">{h.note}</span>}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function AddPlant() {
  const [name, setName] = useState('Felsenbrine Obelisk');
  const [cand, setCand] = useState(0);
  const [site, setSite] = useState('hecke');
  const [saved, setSaved] = useState(false);
  if (saved) {
    return (
      <div className="page">
        <h1 className="title-s">Angelegt</h1>
        <p className="box">Im fertigen Programm erstellt Claude jetzt im Hintergrund den Pflegeplan (ca. 30 Sekunden). Im Prototyp geht es zur Beispiel-Felsenbirne.</p>
        <a className="btn primary" href="#/pflanze/obelisk">Zur Pflanze</a>
      </div>
    );
  }
  return (
    <div className="page">
      <Back href="#/pflanzen" label="Abbrechen" />
      <h1 className="title-s">Pflanze hinzufügen</h1>
      <div className="field">
        <label htmlFor="name">Name (deutsch oder lateinisch, mit Sorte)</label>
        <input id="name" className="input" style={{ border: '2px solid var(--green)' }} value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <fieldset className="stack" style={{ border: 0, margin: 0, padding: 0 }}>
        <legend className="label" style={{ paddingBottom: 8 }}>Meinten Sie …</legend>
        {NAME_SUGGESTIONS.map((c, i) => (
          <button key={c.de} className="option" aria-pressed={cand === i} onClick={() => setCand(i)}>
            <span className="stack" style={{ gap: 3 }}>
              <strong style={{ fontSize: 17 }}>{c.de}</strong>
              <span className="small muted" style={{ fontStyle: 'italic' }}>{c.latin}</span>
              {c.hint && <span className="small">{c.hint}</span>}
            </span>
            <span className="radio" />
          </button>
        ))}
        <span className="tiny">„Felsenbrine“ als Tippfehler erkannt. Vorschläge von Claude – die Auswahl triffst du.</span>
      </fieldset>
      <div className="stack" style={{ gap: 14, borderTop: '1px solid var(--line)', paddingTop: 14 }}>
        <div className="stack">
          <span className="label">Standort</span>
          <div className="row">
            {STANDORTE.slice(0, 5).map((s) => <button key={s.id} className="seg" aria-pressed={site === s.id} onClick={() => setSite(s.id)}>{s.name}</button>)}
            <button className="seg" aria-pressed={false}>+ Neuer Standort</button>
          </div>
        </div>
        <div className="grid2">
          <div className="field">
            <label htmlFor="form">Wuchsform</label>
            <select id="form" className="input"><option>Säule</option><option>Strauch</option><option>Hecke</option><option>Kübel</option></select>
          </div>
          <div className="field">
            <label htmlFor="year">Gepflanzt</label>
            <input id="year" className="input" inputMode="numeric" defaultValue="2023" />
          </div>
        </div>
        <div className="field">
          <label htmlFor="nick">Spitzname (optional)</label>
          <input id="nick" className="input" placeholder="z. B. Felsenbirne an der Bank" />
        </div>
      </div>
      <button className="btn primary" onClick={() => setSaved(true)}>Anlegen und Pflegeplan erstellen</button>
    </div>
  );
}
