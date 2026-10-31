// Kalender (M3: real data): enabled tasks projected onto the months of a year.
// Phone: month picker + list; desktop adds the year grid (plant × month).
import { useEffect, useState } from 'react';
import { ApiError, CATEGORIES, api, type CalendarEntry, type Category } from '../api';
import { Legal, TaskChip, monthName, taskColors, useWide } from '../components/ui';

const isBirdProtection = (m: number) => m >= 2 && m <= 8; // index 0-11: March-September

export function Calendar() {
  const wide = useWide();
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth());
  const [months, setMonths] = useState<CalendarEntry[][] | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let current = true;
    setMonths(null); setError('');
    api.calendar(year).then((r) => { if (current) setMonths(r.months); }, (e) => { if (current) setError(e instanceof ApiError ? e.message : 'Fehler'); });
    return () => { current = false; };
  }, [year]);
  const thisMonth = year === now.getFullYear() ? now.getMonth() : -1;
  const entries = months?.[month] ?? [];

  return (
    <div className={wide ? 'page wide' : 'page'}>
      <header className="between">
        <h1 className="title">Kalender</h1>
        <div className="row" role="group" aria-label="Jahr">
          <button className="btn small" aria-label="Vorheriges Jahr" disabled={year <= 2000} onClick={() => setYear(year - 1)}>‹</button>
          <strong>{year}</strong>
          <button className="btn small" aria-label="Nächstes Jahr" disabled={year >= 2100} onClick={() => setYear(year + 1)}>›</button>
        </div>
      </header>
      {error && <p className="box" role="alert">{error}</p>}

      {wide && months && <YearGrid months={months} thisMonth={thisMonth} />}

      <div className="months" role="group" aria-label="Monat wählen" style={wide ? { gridTemplateColumns: 'repeat(12, minmax(0, 1fr))' } : undefined}>
        {Array.from({ length: 12 }, (_, i) => (
          <button key={i} className={isBirdProtection(i) ? 'month birds' : 'month'} aria-pressed={i === month} onClick={() => setMonth(i)} aria-label={monthName(i + 1)}>
            <span>{monthName(i + 1).slice(0, 3)}</span>
            <span className="dot" style={{ background: i === thisMonth ? (i === month ? 'var(--green-ink)' : 'var(--green)') : 'transparent' }} />
          </button>
        ))}
      </div>
      <div className="row tiny" style={{ gap: 16 }}>
        <span className="row" style={{ gap: 6 }}><span style={{ width: 18, height: 4, borderRadius: 2, background: 'var(--legal-bar)' }} />Vogelschutzzeit (§ 39)</span>
        <span className="row" style={{ gap: 6 }}><span style={{ width: 8, height: 8, borderRadius: 4, background: 'var(--green)' }} />Heute</span>
      </div>

      <section className="stack" style={{ gap: 12 }}>
        <h2 style={{ fontSize: 24 }}>{monthName(month + 1)} {year}</h2>
        {isBirdProtection(month) && <Legal>1. März – 30. September: kein starker Rückschnitt von Hecken und Gehölzen. Schonende Pflegeschnitte sind erlaubt – vorher auf Nester prüfen.</Legal>}
        {!months && !error && <p className="muted">Lädt …</p>}
        {months && entries.length === 0 && <p className="box">In diesem Monat ist nichts geplant.</p>}
        {entries.map((e) => (
          <a key={e.task_id} href={`#/aufgabe-bearbeiten/${e.task_id}`} className="card stack" style={{ gap: 6, textDecoration: 'none', color: 'var(--ink)' }}>
            <span className="row" style={{ gap: 6 }}><TaskChip category={e.category} />{e.moved && <span className="small" style={{ color: 'var(--legal)', fontWeight: 700 }}>§ wegen Vogelschutzzeit hierher verschoben</span>}</span>
            <strong style={{ fontSize: 17, lineHeight: 1.3 }}>{e.title}</strong>
            <span className="small muted">{e.plant ? e.plant.title : 'Ganzer Garten'}</span>
          </a>
        ))}
      </section>
    </div>
  );
}

const SHORT: Record<Category, string> = { ...CATEGORIES, pflanzenschutz: 'Schutz', winterschutz: 'Winter' };

function YearGrid({ months, thisMonth }: { months: CalendarEntry[][]; thisMonth: number }) {
  const rows = new Map<string, { title: string; href?: string; byMonth: Category[][] }>();
  months.forEach((list, m) => list.forEach((e) => {
    const key = e.plant?.id ?? '_garden';
    const row = rows.get(key) ?? { title: e.plant?.title ?? 'Ganzer Garten', href: e.plant ? `#/pflanze/${e.plant.id}` : undefined, byMonth: Array.from({ length: 12 }, () => []) };
    row.byMonth[m].push(e.category);
    rows.set(key, row);
  }));
  if (rows.size === 0) return null;
  return (
    <div className="yeargrid-wrap">
      <div className="yeargrid">
        <div className="head" style={{ alignItems: 'flex-start', paddingLeft: 14 }}>Pflanze</div>
        {Array.from({ length: 12 }, (_, i) => (
          <div key={i} className={['head', isBirdProtection(i) && 'birds', i === thisMonth && 'now'].filter(Boolean).join(' ')}>{monthName(i + 1).slice(0, 3)}</div>
        ))}
        {[...rows.entries()].map(([key, r]) => (
          <Row key={key} r={r} thisMonth={thisMonth} />
        ))}
      </div>
    </div>
  );
}

function Row({ r, thisMonth }: { r: { title: string; href?: string; byMonth: Category[][] }; thisMonth: number }) {
  return (
    <>
      <div className="plant">{r.href ? <a href={r.href} style={{ fontWeight: 700, textDecoration: 'none', color: 'var(--ink)' }}>{r.title}</a> : <strong>{r.title}</strong>}</div>
      {r.byMonth.map((cats, i) => (
        <div key={i} className={i === thisMonth ? 'now' : undefined}>
          {cats.map((c, k) => <span key={k} className="mini" style={taskColors(c)}>{SHORT[c]}</span>)}
        </div>
      ))}
    </>
  );
}
