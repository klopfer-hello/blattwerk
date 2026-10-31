import { useState } from 'react';
import { CALENDAR, MONTHS, PLANTS, TODAY, isBirdProtection, type Category } from '../mock/data';
import { Chip, Legal, catColors, useWide } from '../components/ui';

export function Calendar() {
  const wide = useWide();
  const [month, setMonth] = useState(TODAY.month);
  const tasks = CALENDAR[month] ?? [];
  return (
    <div className={wide ? 'page wide' : 'page'}>
      <header className="stack" style={{ gap: 4 }}>
        <span className="muted">Gartenjahr 2026/27</span>
        <h1 className="title">Kalender</h1>
      </header>

      {wide && <YearGrid />}

      <div className="months" role="group" aria-label="Monat wählen" style={wide ? { gridTemplateColumns: 'repeat(12, minmax(0, 1fr))' } : undefined}>
        {MONTHS.map((m, i) => (
          <button key={m} className={isBirdProtection(i) ? 'month birds' : 'month'} aria-pressed={i === month} onClick={() => setMonth(i)} aria-label={m}>
            <span>{m.slice(0, 3)}</span>
            <span className="dot" style={{ background: i === TODAY.month ? (i === month ? 'var(--green-ink)' : 'var(--green)') : 'transparent' }} />
          </button>
        ))}
      </div>
      <div className="row tiny" style={{ gap: 16 }}>
        <span className="row" style={{ gap: 6 }}><span style={{ width: 18, height: 4, borderRadius: 2, background: 'var(--legal-bar)' }} />Vogelschutzzeit (§ 39)</span>
        <span className="row" style={{ gap: 6 }}><span style={{ width: 8, height: 8, borderRadius: 4, background: 'var(--green)' }} />Heute</span>
      </div>

      <section className="stack" style={{ gap: 12 }}>
        <h2 style={{ fontSize: 24 }}>{MONTHS[month]}</h2>
        {isBirdProtection(month) && <Legal>1. März – 30. September: kein starker Rückschnitt von Hecken und Gehölzen. Schonende Pflegeschnitte sind erlaubt – vorher auf Nester prüfen.</Legal>}
        {tasks.map(([cat, title, plant, note]) => (
          <div key={title} className="card stack" style={{ gap: 6 }}>
            <Chip category={cat} />
            <strong style={{ fontSize: 17, lineHeight: 1.3 }}>{title}</strong>
            <span className="small muted">{plant}</span>
            {note && <span className="small" style={{ color: 'var(--legal)', fontWeight: 700 }}>{note}</span>}
          </div>
        ))}
        <span className="tiny">Termine verschieben sich mit der echten Jahreszeit (Wetter + phänologischer Kalender).</span>
      </section>
    </div>
  );
}

const SHORT: Record<Category, string> = { Schnitt: 'Schnitt', Düngen: 'Düngen', Ernte: 'Ernte', Pflanzenschutz: 'Schutz', Winterschutz: 'Winter', Aussaat: 'Aussaat' };

function YearGrid() {
  const [off, setOff] = useState<Partial<Record<Category, boolean>>>({});
  const cats = Object.keys(SHORT) as Category[];
  return (
    <section className="stack" style={{ gap: 12 }}>
      <div className="row" role="group" aria-label="Kategorien">
        {cats.map((c) => (
          <button key={c} className="seg" aria-pressed={!off[c]} onClick={() => setOff({ ...off, [c]: !off[c] })}
            style={off[c] ? { textDecoration: 'line-through', color: 'var(--muted)' } : catColors(c)}>{c}</button>
        ))}
      </div>
      <div className="yeargrid-wrap">
        <div className="yeargrid">
          <div className="head" style={{ alignItems: 'flex-start', paddingLeft: 14 }}>Pflanze</div>
          {MONTHS.map((m, i) => (
            <div key={m} className={['head', isBirdProtection(i) && 'birds', i === TODAY.month && 'now'].filter(Boolean).join(' ')}>{m.slice(0, 3)}</div>
          ))}
          {PLANTS.map((p) => (
            <Row key={p.id} name={p.name} href={`#/pflanze/${p.id}`} byMonth={(m) => p.plan.filter((t) => t.month === m && !off[t.category]).map((t) => t.category)} />
          ))}
        </div>
      </div>
    </section>
  );
}

function Row({ name, href, byMonth }: { name: string; href: string; byMonth: (m: number) => Category[] }) {
  return (
    <>
      <div className="plant"><a href={href} style={{ fontWeight: 700, textDecoration: 'none', color: 'var(--ink)' }}>{name}</a></div>
      {MONTHS.map((m, i) => (
        <div key={m} className={i === TODAY.month ? 'now' : undefined}>
          {byMonth(i).map((c, k) => <span key={k} className="mini" style={catColors(c)}>{SHORT[c]}</span>)}
        </div>
      ))}
    </>
  );
}
