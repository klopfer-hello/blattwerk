import { useState } from 'react';
import { TASK_DETAILS, genericDetail, plantById } from '../mock/data';
import { Back, Chip, Legal } from '../components/ui';
import type { TodoState } from '../App';

export function Task({ id, state }: { id: string; state: TodoState }) {
  const todo = state.list.find((t) => t.id === id);
  const [note, setNote] = useState(state.notes[id] ?? '');
  if (!todo) return <div className="page"><Back href="#/heute" label="Heute" /><p>Aufgabe nicht gefunden.</p></div>;
  const d = TASK_DETAILS[id] ?? genericDetail(todo);
  const done = !!state.done[id];
  return (
    <div className="page">
      <Back href="#/heute" label="Heute" />
      <div className="stack" style={{ gap: 10 }}>
        <div className="row"><Chip category={todo.category} /><span className="chip" style={{ background: 'var(--surface)', color: 'var(--ink-2)', fontWeight: 400 }}>{d.timing}</span></div>
        <h1 className="title-s">{todo.title}</h1>
        {todo.plantIds.length > 0
          ? todo.plantIds.map((p) => <a key={p} href={`#/pflanze/${p}`} style={{ fontWeight: 700, textDecoration: 'none' }}>{plantById(p)?.name} ›</a>)
          : <span className="muted">{todo.plantText}</span>}
      </div>

      <section className="box stack">
        <h2 style={{ fontSize: 17 }}>Warum jetzt?</h2>
        <p>{d.why}</p>
      </section>

      <section className="stack" style={{ gap: 12 }}>
        <h2 style={{ fontSize: 20 }}>Anleitung</h2>
        <ol style={{ margin: 0, paddingLeft: 22, display: 'flex', flexDirection: 'column', gap: 10 }}>
          {d.steps.map((s) => <li key={s}>{s}</li>)}
        </ol>
      </section>

      {d.material && (
        <section className="stack">
          <h2 style={{ fontSize: 20 }}>Material</h2>
          <div className="outline stack" style={{ gap: 4 }}>
            <strong>{d.material.name}</strong>
            {d.material.brands && <span style={{ color: 'var(--ink-2)' }}>{d.material.brands}</span>}
            <span className="small muted">{d.material.shops}</span>
          </div>
          <span className="tiny">Markenvorschläge von der KI, keine Werbung. Nur für Haus- und Kleingarten zugelassene Mittel.</span>
        </section>
      )}

      <Legal>{d.legal}</Legal>

      <section className="stack" style={{ gap: 10, borderTop: '1px solid var(--line)', paddingTop: 14 }}>
        <div className="field">
          <label htmlFor="note">Notiz (optional)</label>
          <textarea id="note" className="input" rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder="z. B. 14 Weibchen am Apfel, 3 an der Kirsche" />
        </div>
        <button className={done ? 'btn primary done' : 'btn primary'} onClick={() => { state.setNote(id, note.trim()); state.toggle(id); }}>
          {done ? '✓ Erledigt – rückgängig machen' : 'Als erledigt abhaken'}
        </button>
        <div className="grid2">
          <button className="btn" onClick={() => alertPrototype('Verschieben')}>Verschieben</button>
          <button className="btn" onClick={() => alertPrototype('Dieses Jahr nicht')}>Dieses Jahr nicht</button>
        </div>
      </section>
      <span className="tiny">Pflegeplan erstellt am 14.10.2026 · Claude · Plan-Version 3</span>
    </div>
  );
}

function alertPrototype(what: string) {
  window.dispatchEvent(new CustomEvent('prototype-note', { detail: `„${what}“ kommt in der echten App.` }));
}
