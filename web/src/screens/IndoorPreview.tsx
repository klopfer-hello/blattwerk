// Preview of indoor plants (M11) for approval: static example data, nothing is sent or
// stored. Shows the four new pieces: Drinnen/Draußen on the Standort, room and window on the
// plant, watering in "Heute" with feedback, and the care rhythm of a plant.
import { useState } from 'react';
import { Back, Icon } from '../components/ui';

const WATER = { background: 'var(--c-giessen)', color: 'var(--c-giessen-ink)' };
const FEED = { background: 'var(--c-duengen)', color: 'var(--c-duengen-ink)' };
const CARE = { background: 'var(--surface)', color: 'var(--ink-2)' };

function Section({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <section className="stack" style={{ gap: 10, borderTop: '1px solid var(--line)', paddingTop: 14 }}>
      <span className="eyebrow">{n}. {title}</span>
      {children}
    </section>
  );
}

function Choice({ options, value, onChange, label, columns }: { options: string[]; value: string; onChange: (v: string) => void; label: string; columns?: number }) {
  return (
    <div role="group" aria-label={label} style={{ display: 'grid', gridTemplateColumns: `repeat(${columns ?? options.length}, minmax(0, 1fr))`, gap: 6 }}>
      {options.map((o) => (
        <button key={o} className="btn" aria-pressed={value === o} onClick={() => onChange(o)}
          style={value === o ? { background: 'var(--green)', color: 'var(--green-ink)', border: 0, fontWeight: 700, padding: '0 4px' } : { padding: '0 4px' }}>{o}</button>
      ))}
    </div>
  );
}

function WaterRow({ name, room, note, base }: { name: string; room: string; note: string; base: number }) {
  const [done, setDone] = useState(false);
  const [soil, setSoil] = useState('');
  const next = soil === 'noch feucht' ? Math.round(base * 1.2) : soil === 'knochentrocken' ? Math.round(base * 0.8) : base;
  return (
    <div className="outline stack" style={{ gap: 8 }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
        <button className="check" role="checkbox" aria-checked={done} aria-label={`${name} gegossen`} onClick={() => { setDone(!done); setSoil(''); }}>
          <span>{done && <Icon name="tick" size={16} stroke={3} />}</span>
        </button>
        <span className="stack" style={{ gap: 4 }}>
          <span className="chip" style={WATER}><Icon name="drop" size={12} /> Gießen</span>
          <strong style={done ? { textDecoration: 'line-through', color: 'var(--muted)' } : undefined}>{name}</strong>
          <span className="small muted">{room} · {note}</span>
        </span>
      </div>
      {done && (
        <div className="stack" style={{ gap: 6 }}>
          <span className="small">Wie war die Erde vor dem Gießen?</span>
          <Choice label="Erde vor dem Gießen" options={['noch feucht', 'passt', 'knochentrocken']} value={soil} onChange={setSoil} />
          {soil && <span className="small muted">{next === base ? `Rhythmus bleibt: alle ${base} Tage.` : `Nächstes Mal in ${next} statt ${base} Tagen.`}</span>}
        </div>
      )}
    </div>
  );
}

export function IndoorPreview() {
  const [win, setWin] = useState('S');
  const [distance, setDistance] = useState('bis 1 m');
  const [material, setMaterial] = useState('Ton');
  const [idShown, setIdShown] = useState(false);
  const [inside, setInside] = useState('Drinnen');
  return (
    <div className="page">
      <Back href="#/mehr" label="Mehr" />
      <span className="chip" style={{ background: 'var(--legal-tint)', color: 'var(--legal-ink)' }}>Vorschau Zimmerpflanzen (M11) – Beispieldaten, nichts wird gespeichert</span>
      <h1 className="title-s">Zimmerpflanzen</h1>
      <span className="small muted">So würde es aussehen. Die Knöpfe reagieren, speichern aber nichts. Sag, was passt und was anders sein soll.</span>

      <Section n={1} title="Standort anlegen: drinnen oder draußen">
        <div className="field"><label htmlFor="pv-sname">Name</label><input id="pv-sname" className="input" defaultValue="Wohnzimmer" /></div>
        <Choice label="Drinnen oder draußen" options={['Draußen', 'Drinnen']} value={inside} onChange={setInside} />
        {inside === 'Drinnen'
          ? <span className="small muted">Art: Zimmer. Pflanzen hier bekommen Gieß-Erinnerungen, aber keine Frost- und Wetterwarnungen.</span>
          : <span className="small muted">Art: Beet, Gemüsebeet, Rasen, Hecke, Kübelplatz, Gewächshaus … – ohne Gieß-Erinnerungen, mit Wetterwarnungen (wie bisher).</span>}
      </Section>

      <Section n={2} title="Pflanze anlegen: Zimmer, Fenster, Topf">
        <button className="btn" onClick={() => setIdShown(true)} style={{ fontWeight: 700 }}><Icon name="camera" size={20} />Per Foto bestimmen</button>
        {idShown && (
          <div className="stack" style={{ gap: 6 }}>
            <span className="small muted">Die KI schlägt vor (Foto ohne Standort-Daten):</span>
            <button className="option" aria-pressed><span className="stack" style={{ gap: 2 }}><strong>Elefantenfuß</strong><span className="small muted" style={{ fontStyle: 'italic' }}>Beaucarnea recurvata · ziemlich sicher</span></span></button>
            <button className="option"><span className="stack" style={{ gap: 2 }}><strong>Yucca</strong><span className="small muted" style={{ fontStyle: 'italic' }}>Yucca elephantipes · möglich</span></span></button>
          </div>
        )}
        <div className="field"><label htmlFor="pv-room">Standort</label>
          <select id="pv-room" className="input" defaultValue="wz"><option value="wz">Wohnzimmer (drinnen)</option><option>Büro (drinnen)</option><option>Bad (drinnen)</option><option>Beet am Zaun (draußen)</option></select>
        </div>
        <span className="small">Fenster in Richtung</span>
        <Choice label="Fensterrichtung" options={['N', 'O', 'S', 'W', 'keins']} value={win} onChange={setWin} />
        <span className="small">Abstand zum Fenster</span>
        <Choice label="Abstand zum Fenster" options={['Fensterbank', 'bis 1 m', '1–2 m', 'Raummitte']} value={distance} onChange={setDistance} columns={2} />
        <div className="grid2" style={{ gap: 8, alignItems: 'end' }}>
          <div className="field"><label htmlFor="pv-pot">Topf Ø (cm)</label><input id="pv-pot" className="input" inputMode="numeric" defaultValue="18" /></div>
          <div className="field"><label htmlFor="pv-mat">Material</label>
            <select id="pv-mat" className="input" value={material} onChange={(e) => setMaterial(e.target.value)}><option>Kunststoff</option><option>Ton</option><option>Keramik</option><option>Glas</option></select>
          </div>
        </div>
        <span className="tiny">Licht, Topf und Jahreszeit bestimmen den Gieß-Rhythmus. Frostwarnungen und Schnittregeln gelten für Zimmerpflanzen nicht.</span>
      </Section>

      <Section n={3} title="Heute: Gießen mit Rückmeldung">
        <WaterRow name="Elefantenfuß" room="Wohnzimmer · Südfenster" note="durchdringend gießen, Wasser im Untersetzer nach 15 min weg" base={21} />
        <WaterRow name="Monstera" room="Büro · Ostfenster" note="obere 2–3 cm Erde trocken? Dann gießen" base={7} />
        <span className="tiny">Antippen = gegossen. Die Antwort zur Erde passt den Rhythmus an (je ±20 %, 2–60 Tage).</span>
      </Section>

      <Section n={4} title="Auf der Pflanzenseite: Pflege-Rhythmus">
        <strong style={{ fontSize: 20 }}>Elefantenfuß</strong>
        <span className="small muted">Wohnzimmer · Südfenster, bis 1 m · Topf 18 cm Ton</span>
        {([
          [WATER, 'Gießen', 'alle 21 Tage · Nov–Feb alle 35 Tage', 'nächstes: Mi, 12.11.'],
          [FEED, 'Düngen', 'alle 4 Wochen, April–September', 'Pause bis April'],
          [CARE, 'Topf drehen', 'alle 4 Wochen (wächst zum Licht)', 'nächstes: 20.11.'],
          [CARE, 'Blätter abstauben', 'alle 2 Monate', 'nächstes: Dezember'],
          [CARE, 'Umtopfen', 'alle 3 Jahre im Frühjahr', 'nächstes: März 2027'],
        ] as const).map(([color, what, rhythm, next]) => (
          <div key={what} className="planrow" style={{ gridTemplateColumns: 'minmax(0, 1fr) auto' }}>
            <span className="stack" style={{ gap: 3 }}><span className="chip" style={color}>{what}</span><span className="small">{rhythm}</span></span>
            <span className="small muted" style={{ textAlign: 'right' }}>{next}</span>
          </div>
        ))}
        <span className="small muted">Rhythmus zuletzt angepasst am 31.10.: 18 → 21 Tage („Erde noch feucht“).</span>
        <span className="tiny">Der Plan kommt wie im Garten von der KI; einzelne Aufgaben kannst du ändern oder abschalten.</span>
      </Section>

    </div>
  );
}
