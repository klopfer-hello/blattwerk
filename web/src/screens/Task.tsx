// To-do detail (one occurrence: note, done/undo, skip, postpone) and the task
// form (what and when: once / every year in a month window / every n days).
import { useEffect, useState } from 'react';
import { ApiError, CATEGORIES, INDOOR_CATEGORIES, api, type Category, type LegalNote, type Plant, type PhaseKey, type Recurrence, type Task, type TaskIn, PHASES, type Todo } from '../api';
import { Back, Legal, LegalNotes, TaskChip, deDate, localIso, monthName, timingText, Waiting } from '../components/ui';
import { UNDO_409 } from './Today';

const msg = (e: unknown) => (e instanceof ApiError ? e.message : 'Unbekannter Fehler');

export function TodoDetail({ id }: { id: string }) {
  const [t, setT] = useState<Todo | null>(null);
  const [note, setNote] = useState('');
  const [later, setLater] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.todo(id).then((x) => { setT(x); setNote(x.note); }, (e) => setError(msg(e))); }, [id]);
  if (!t) return <div className="page"><Back href="#/heute" label="Heute" /><p className="box">{error || <Waiting />}</p></div>;

  async function run(f: () => Promise<Todo>, on409 = 'Nur offene Aufgaben können verschoben werden.') {
    if (busy) return;
    setBusy(true); setError('');
    try { const x = await f(); setT(x); setNote(x.note); }
    catch (e) {
      const legal = e instanceof ApiError ? e.fields.to : undefined;  // § reason from the server (German)
      setError(e instanceof ApiError && e.status === 409 ? on409 : legal && legal.includes('§') ? legal
        : e instanceof ApiError && e.status === 422 ? 'Bitte ein Datum nach heute wählen.' : msg(e));
    }
    finally { setBusy(false); }
  }
  const open = t.status === 'open';
  return (
    <div className="page">
      <Back href="#/heute" label="Heute" />
      <div className="stack" style={{ gap: 10 }}>
        <div className="row"><TaskChip category={t.task.category} />{t.task.urgent && <span className="chip" style={{ background: 'var(--urgent-tint)', color: 'var(--urgent)' }}>dringend</span>}</div>
        <h1 className="title-s">{t.task.title}</h1>
        {t.plant ? <a href={`#/pflanze/${t.plant.id}`} style={{ fontWeight: 700, textDecoration: 'none' }}>{t.plant.title} ›</a> : <span className="muted">Ganzer Garten</span>}
        <span className={t.overdue ? 'when urgent' : 'small muted'}>
          {t.due_from === t.due_to ? `Fällig am ${deDate(t.due_from)}` : `Fällig ${deDate(t.due_from)} – ${deDate(t.due_to)}`}
          {t.overdue ? ' · überfällig' : ''}{t.postponed ? ' · verschoben' : ''}
          {t.blocked_until ? ` · § erst ab ${deDate(t.blocked_until)} erlaubt` : ''}
        </span>
      </div>
      {t.task.instructions
        ? <section className="box stack"><h2 style={{ fontSize: 17 }}>Anleitung</h2><p style={{ whiteSpace: 'pre-wrap' }}>{t.task.instructions}</p></section>
        : <p className="small muted">Keine Anleitung hinterlegt. Mit dem KI-Pflegeplan (M5) kommt sie automatisch.</p>}
      {t.legal_adjustment && <Legal><strong>{t.legal_adjustment}</strong></Legal>}
      <LegalNotes notes={t.notes} />

      <section className="stack" style={{ gap: 10, borderTop: '1px solid var(--line)', paddingTop: 14 }}>
        <div className="field">
          <label htmlFor="note">Notiz (optional)</label>
          <textarea id="note" className="input" rows={3} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} placeholder="z. B. 14 Weibchen am Leimring" />
        </div>
        {error && <p className="small" role="alert" style={{ color: 'var(--urgent)' }}>{error}</p>}
        {open
          ? <button className="btn primary" disabled={busy} onClick={() => run(() => api.done(t.id, note))}>Als erledigt abhaken</button>
          : <button className="btn primary done" disabled={busy} onClick={() => run(() => api.undo(t.id), UNDO_409)}>✓ {t.status === 'done' ? 'Erledigt' : 'Übersprungen'} – rückgängig machen</button>}
        {open && (
          <>
            <button className="btn" disabled={busy} onClick={() => run(() => api.skip(t.id, note))}>Dieses Mal überspringen</button>
            <div className="grid2" style={{ alignItems: 'end' }}>
              <div className="field"><label htmlFor="later">Verschieben auf</label><input id="later" type="date" className="input" min={localIso(1)} value={later} onChange={(e) => setLater(e.target.value)} /></div>
              <button className="btn" disabled={busy || !later} onClick={() => run(() => api.postpone(t.id, later))}>Verschieben</button>
            </div>
          </>
        )}
      </section>
      <a className="btn" href={`#/aufgabe-bearbeiten/${t.task.id}`}>Aufgabe bearbeiten (Zeitraum, Text …)</a>
    </div>
  );
}

const EMPTY: TaskIn = { plant_id: null, title: '', category: 'sonstiges', cut_type: null, instructions: '', recurrence: 'yearly', due_date: null, month_from: new Date().getMonth() + 1, month_to: new Date().getMonth() + 1, interval_days: 7, start_date: null, urgent: false };
const FIELD_TEXT: Record<string, string> = { title: 'Bitte einen Titel (bis 120 Zeichen).', due_date: 'Bitte ein Datum wählen.', interval_days: '1 bis 3650 Tage.', plant_id: 'Pflanze nicht gefunden.' };

export function TaskForm({ id, plantId }: { id?: string; plantId?: string }) {
  const [v, setV] = useState<TaskIn>({ ...EMPTY, plant_id: plantId ?? null });
  const [enabled, setEnabled] = useState(true);
  const [plants, setPlants] = useState<Plant[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [fromPlan, setFromPlan] = useState<Pick<Task, 'products' | 'why' | 'source'> | null>(null);
  const [season, setSeason] = useState(false);  // interval only in some months (e.g. fertilise Apr–Sep, M11)
  useEffect(() => { api.plants().then(setPlants, () => undefined); }, []);
  useEffect(() => {
    if (!id) return;
    api.task(id).then((t) => {
      const { id: _i, plant: _p, source, enabled: on, notes: _n, products, why, next_due: _d, ...rest } = t;
      setV(rest); setEnabled(on); setFromPlan({ source, products, why });
      setSeason(rest.recurrence === 'interval' && rest.month_from != null && rest.month_to != null);
    }, (e) => setError(e instanceof ApiError ? e : new ApiError(0, msg(e))));
  }, [id]);
  const set = (p: Partial<TaskIn>) => setV((x) => ({ ...x, ...p }));
  const back = id ? '#/heute' : v.plant_id ? `#/pflanze/${v.plant_id}` : '#/heute';

  async function save() {
    if (saving) return;
    setSaving(true); setError(null);
    const body: TaskIn = {
      ...v,
      due_date: v.recurrence === 'once' ? v.due_date : null,
      month_from: v.recurrence === 'yearly' || (v.recurrence === 'interval' && season) ? v.month_from : null,
      month_to: v.recurrence === 'yearly' || (v.recurrence === 'interval' && season) ? v.month_to : null,
      winter_interval_days: v.recurrence === 'interval' ? v.winter_interval_days ?? null : null,
      amount_ml: v.category === 'giessen' ? v.amount_ml ?? null : null,
      pheno_phase: v.recurrence === 'yearly' ? v.pheno_phase ?? null : null,
      interval_days: v.recurrence === 'interval' ? v.interval_days : null, start_date: v.recurrence === 'interval' ? v.start_date : null,
    };
    try {
      const t = id ? await api.updateTask(id, body) : await api.createTask(body);
      window.location.hash = t.plant ? `#/pflanze/${t.plant.id}` : '#/heute';
    } catch (e) { setError(e instanceof ApiError ? e : new ApiError(0, msg(e))); } finally { setSaving(false); }
  }
  async function toggleEnabled() {
    if (!id || toggling) return;
    setToggling(true);
    try { setEnabled((await api.setTaskEnabled(id, !enabled)).enabled); } catch (e) { setError(e instanceof ApiError ? e : new ApiError(0, msg(e))); } finally { setToggling(false); }
  }
  const fieldErr = (f: string) => (error?.fields[f] ? FIELD_TEXT[f] ?? 'Ungültig.' : null);
  const indoor = !!plants.find((p) => p.id === v.plant_id)?.standort.indoor;
  const categories = (Object.keys(CATEGORIES) as Category[]).filter((c) => indoor || c === v.category || !INDOOR_CATEGORIES.includes(c));
  const monthSelect = (label: string, value: number | null, onChange: (m: number) => void, idAttr: string) => (
    <div className="field">
      <label htmlFor={idAttr}>{label}</label>
      <select id={idAttr} className="input" value={value ?? 1} onChange={(e) => onChange(Number(e.target.value))}>
        {Array.from({ length: 12 }, (_, i) => <option key={i + 1} value={i + 1}>{monthName(i + 1)}</option>)}
      </select>
    </div>
  );

  return (
    <div className="page">
      <Back href={back} label="Abbrechen" />
      <h1 className="title-s">{id ? 'Aufgabe bearbeiten' : 'Neue Aufgabe'}</h1>
      <div className="field">
        <label htmlFor="title">Was ist zu tun?</label>
        <input id="title" className="input" maxLength={120} value={v.title} onChange={(e) => set({ title: e.target.value })} placeholder="z. B. Leimringe prüfen" aria-invalid={!!fieldErr('title')} />
        {fieldErr('title') && <span className="small" style={{ color: 'var(--urgent)' }}>{fieldErr('title')}</span>}
      </div>
      <div className="stack">
        <span className="label">Kategorie</span>
        <div className="row" role="group" aria-label="Kategorie">
          {categories.map((c) => <button key={c} className="seg" aria-pressed={v.category === c} onClick={() => set({ category: c, cut_type: c === 'schnitt' ? v.cut_type ?? 'pflege' : null })}>{CATEGORIES[c]}</button>)}
        </div>
      </div>
      {v.category === 'giessen' && (
        <div className="field"><label htmlFor="ml">Menge pro Gießen (ml, optional)</label><input id="ml" className="input" inputMode="numeric" value={v.amount_ml ?? ''} onChange={(e) => set({ amount_ml: e.target.value ? Number(e.target.value) : null })} aria-invalid={!!fieldErr('amount_ml')} /></div>
      )}
      {v.category === 'schnitt' && (
        <div className="stack">
          <span className="label">Art des Schnitts</span>
          <div className="row" role="group" aria-label="Art des Schnitts">
            <button className="seg" aria-pressed={v.cut_type === 'pflege'} onClick={() => set({ cut_type: 'pflege' })}>Schonender Pflegeschnitt</button>
            <button className="seg" aria-pressed={v.cut_type === 'stark'} onClick={() => set({ cut_type: 'stark' })}>Starker Rückschnitt / Roden</button>
          </div>
          <span className="tiny">Pflegeschnitt = Zuwachs entfernen, in Form halten. Stark = deutlich zurückschneiden, auf den Stock setzen oder entfernen.</span>
        </div>
      )}
      <div className="field">
        <label htmlFor="plant">Pflanze</label>
        <select id="plant" className="input" value={v.plant_id ?? ''} onChange={(e) => { const pid = e.target.value || null; const inside = !!plants.find((p) => p.id === pid)?.standort.indoor;
          set({ plant_id: pid, ...(!inside && INDOOR_CATEGORIES.includes(v.category) ? { category: 'sonstiges' } : {}) }); }}>
          <option value="">Ganzer Garten (keine bestimmte Pflanze)</option>
          {plants.map((p) => <option key={p.id} value={p.id}>{p.nickname || `${p.species.german}${p.cultivar ? ` ‘${p.cultivar.name}’` : ''}`} · {p.standort.name}</option>)}
        </select>
      </div>
      <div className="stack">
        <span className="label">Wann?</span>
        <div className="row" role="group" aria-label="Wiederholung">
          {([['yearly', 'Jedes Jahr'], ['interval', 'Alle … Tage'], ['once', 'Einmalig']] as [Recurrence, string][]).map(([r, label]) => (
            <button key={r} className="seg" aria-pressed={v.recurrence === r} onClick={() => set({ recurrence: r })}>{label}</button>
          ))}
        </div>
      </div>
      {v.recurrence === 'yearly' && (
        <>
          <div className="grid2">
            {monthSelect('Von', v.month_from, (m) => set({ month_from: m }), 'mfrom')}
            {monthSelect('Bis', v.month_to, (m) => set({ month_to: m }), 'mto')}
          </div>
          <div className="field">
            <label htmlFor="pheno">An die Jahreszeit koppeln (optional)</label>
            <select id="pheno" className="input" value={v.pheno_phase ?? ''} onChange={(e) => set({ pheno_phase: (e.target.value || null) as PhaseKey | null })}>
              <option value="">nein – nach Monaten</option>
              {PHASES.map(([k, name, ind]) => <option key={k} value={k}>zur {ind} ({name})</option>)}
            </select>
            {v.pheno_phase && <span className="small muted">Der Termin folgt der echten Jahreszeit in deiner Region (oder deiner Beobachtung). Die Monate oben gelten, solange es dafür noch keine Daten gibt.</span>}
          </div>
          {v.pheno_phase && (
            <div className="grid2">
              <div className="field"><label htmlFor="poff">Tage danach (− = davor)</label><NumberField id="poff" value={v.pheno_offset ?? 0} min={-60} max={120} onChange={(n) => set({ pheno_offset: n })} invalid={!!fieldErr('pheno_offset')} /></div>
              <div className="field"><label htmlFor="pwin">Zeitraum (Tage)</label><NumberField id="pwin" value={v.pheno_window ?? 14} min={1} max={60} onChange={(n) => set({ pheno_window: n })} invalid={!!fieldErr('pheno_window')} /></div>
            </div>
          )}
        </>
      )}
      {v.recurrence === 'interval' && (
        <>
          <div className="grid2">
            <div className="field"><label htmlFor="days">Alle … Tage</label><input id="days" className="input" inputMode="numeric" value={v.interval_days ?? ''} onChange={(e) => set({ interval_days: e.target.value ? Number(e.target.value) : null })} aria-invalid={!!fieldErr('interval_days')} /></div>
            <div className="field"><label htmlFor="start">Erstes Mal</label><input id="start" type="date" className="input" min="2000-01-01" max="2100-12-31" value={v.start_date ?? ''} onChange={(e) => set({ start_date: e.target.value || null })} /></div>
          </div>
          {indoor && (
            <div className="field"><label htmlFor="wdays">Nov–Feb alle … Tage (optional)</label><input id="wdays" className="input" inputMode="numeric" value={v.winter_interval_days ?? ''} onChange={(e) => set({ winter_interval_days: e.target.value ? Number(e.target.value) : null })} aria-invalid={!!fieldErr('winter_interval_days')} /></div>
          )}
          <div className="setrow" style={{ borderBottom: 0 }}>
            <span id="season-label">Nur in bestimmten Monaten</span>
            <button className="switch" role="switch" aria-checked={season} aria-labelledby="season-label" onClick={() => setSeason(!season)}><span /></button>
          </div>
          {season && (
            <div className="grid2">
              {monthSelect('Von', v.month_from, (m) => set({ month_from: m }), 'imfrom')}
              {monthSelect('Bis', v.month_to, (m) => set({ month_to: m }), 'imto')}
            </div>
          )}
        </>
      )}
      {v.recurrence === 'once' && (
        <div className="field"><label htmlFor="due">Datum</label><input id="due" type="date" className="input" min="2000-01-01" max="2100-12-31" value={v.due_date ?? ''} onChange={(e) => set({ due_date: e.target.value || null })} aria-invalid={!!fieldErr('due_date')} /></div>
      )}
      {(fieldErr('interval_days') || fieldErr('due_date')) && <span className="small" style={{ color: 'var(--urgent)' }}>{fieldErr('interval_days') || fieldErr('due_date')}</span>}
      <span className="small muted">{timingText({ ...v, month_from: v.recurrence !== 'interval' || season ? v.month_from : null, month_to: v.recurrence !== 'interval' || season ? v.month_to : null })}</span>
      <LegalPreview task={{ ...v, winter_interval_days: v.recurrence === 'interval' ? v.winter_interval_days ?? null : null, month_from: v.recurrence !== 'interval' || season ? v.month_from : null, month_to: v.recurrence !== 'interval' || season ? v.month_to : null }} />
      {fromPlan && (fromPlan.why || fromPlan.products.length > 0) && (
        <div className="box stack" style={{ gap: 6 }}>
          {fromPlan.why && <span><strong>Warum:</strong> {fromPlan.why}</span>}
          {fromPlan.products.map((pr, i) => (
            <span key={i} className="small"><strong>{pr.name}</strong>{pr.npk ? ` (NPK ${pr.npk})` : ''}{pr.dose ? ` · ${pr.dose}` : ''}{pr.brands.length ? ` · z. B. ${pr.brands.join(', ')}` : ''}</span>
          ))}
        </div>
      )}
      {fromPlan?.source === 'plan' && <span className="tiny">Aus dem Pflegeplan. Nach dem Speichern ist es deine eigene Aufgabe und bleibt auch bei einem neuen Plan erhalten.</span>}
      <div className="setrow" style={{ borderBottom: 0 }}>
        <span id="urgent-label">Dringend (oben in der Liste)</span>
        <button className="switch" role="switch" aria-checked={v.urgent} aria-labelledby="urgent-label" onClick={() => set({ urgent: !v.urgent })}><span /></button>
      </div>
      <div className="field">
        <label htmlFor="instr">Anleitung (optional)</label>
        <textarea id="instr" className="input" rows={5} maxLength={4000} value={v.instructions} onChange={(e) => set({ instructions: e.target.value })} placeholder="Schritte, Material, worauf achten …" />
      </div>
      {error && (Object.keys(error.fields).length === 0 || Object.keys(error.fields).some((f) => !(f in FIELD_TEXT))) && <p className="box" role="alert" style={{ color: 'var(--urgent)' }}>{error.message}</p>}
      <button className="btn primary" onClick={save} disabled={saving || !v.title.trim()}>{saving ? <Waiting text="Speichert …" /> : 'Speichern'}</button>
      {id && <button className="btn" onClick={toggleEnabled}>{enabled ? 'Aufgabe pausieren (aus der Liste nehmen)' : 'Aufgabe wieder aktivieren'}</button>}
    </div>
  );
}

// A whole number that may be negative: typed as text (so "-" can be typed), stored when it parses.
function NumberField({ id, value, min, max, onChange, invalid }: { id: string; value: number; min: number; max: number; onChange: (n: number) => void; invalid: boolean }) {
  const [raw, setRaw] = useState(String(value));
  useEffect(() => { setRaw((r) => (Number(r) === value ? r : String(value))); }, [value]);
  const n = Number(raw);
  const bad = raw.trim() === '' || !Number.isInteger(n) || n < min || n > max;
  return (
    <>
      <input id={id} className="input" inputMode="text" value={raw} aria-invalid={invalid || bad}
        onChange={(e) => { setRaw(e.target.value); const x = Number(e.target.value); if (e.target.value.trim() !== '' && Number.isInteger(x) && x >= min && x <= max) onChange(x); }} />
      {bad && <span className="small" style={{ color: 'var(--urgent)' }}>Ganze Zahl von {min} bis {max}.</span>}
    </>
  );
}

// Live § preview while the form changes (debounced; only the newest answer counts).
function LegalPreview({ task }: { task: TaskIn }) {
  const [p, setP] = useState<{ notes: LegalNote[]; next: { due_from: string; due_to: string; reason: string } | null } | null>(null);
  const key = JSON.stringify([task.category, task.cut_type, task.plant_id, task.recurrence, task.due_date, task.month_from, task.month_to, task.interval_days, task.start_date]);
  useEffect(() => {
    let current = true;
    const t = window.setTimeout(() => {
      api.legalPreview({ ...task, title: task.title.trim() || 'Vorschau' }).then((x) => { if (current) setP(x); }, () => { if (current) setP(null); });
    }, 300);
    return () => { current = false; window.clearTimeout(t); };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!p || (!p.notes.length && !p.next?.reason)) return <div aria-live="polite" />;
  return (
    <div className="stack" style={{ gap: 8 }} aria-live="polite">
      {p.next?.reason && <Legal><strong>{p.next.reason}</strong> Nächster Termin: {deDate(p.next.due_from)} – {deDate(p.next.due_to)}.</Legal>}
      <LegalNotes notes={p.notes} />
    </div>
  );
}
