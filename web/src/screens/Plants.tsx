// Plants (M2: real data). List by Standort, detail with facts, add/edit form
// with live name suggestions. The care plan (M5) is made by Claude in the worker;
// the detail polls while a job runs. Demo
// plants (links from the still-demo Heute/Kalender) render as DemoPlantDetail.
import { useEffect, useRef, useState } from 'react';
import {
  ApiError, DISTANCES, FORMS, GROWTH, INDOOR_TYPE, POT_MATERIALS, STANDORT_TYPES, WINDOWS, api, type AiCandidate, type Candidate, type NameJob, type Form, type Light, type Plant, type PlantIn, type Species,
  type HistoryItem, type PlanState, type Standort, type Task,
} from '../api';
import { PhotoThumbs } from '../components/Photos';
import { uploadPhoto } from '../photos';
import { MONTHS, plantById, standortById } from '../mock/data';
import { Back, Chip, Icon, Legal, TaskChip, timingText, Waiting } from '../components/ui';

const LIGHT: Record<Light, { bg: string; fg: string }> = {
  sonnig: { bg: '#FDF1CF', fg: '#6B4A00' }, halbschattig: { bg: '#E9EEF0', fg: '#2F4550' }, schattig: { bg: '#E1E4EA', fg: '#2B3244' },
};
export const LightChip = ({ light }: { light: Light | null }) => (light ? <span className="chip" style={{ background: LIGHT[light].bg, color: LIGHT[light].fg }}>{light}</span> : null);
const plantTitle = (p: Plant) => p.nickname || `${p.species.german}${p.cultivar ? ` ‘${p.cultivar.name}’` : ''}`;
const fail = (e: unknown) => (e instanceof ApiError ? e : new ApiError(0, 'Unbekannter Fehler'));

export function Plants() {
  const [plants, setPlants] = useState<Plant[] | null>(null);
  const [archived, setArchived] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [q, setQ] = useState('');
  useEffect(() => {   // ignore answers for a tab that is no longer shown
    let current = true;
    setPlants(null); setError(null);
    api.plants(archived).then((x) => { if (current) setPlants(x); }, (e) => { if (current) setError(fail(e)); });
    return () => { current = false; };
  }, [archived]);

  const needle = q.trim().toLowerCase();
  const shown = (plants ?? []).filter((p) => !needle || `${plantTitle(p)} ${p.species.latin} ${p.species.german} ${p.cultivar?.name ?? ''}`.toLowerCase().includes(needle));
  const groups = new Map<string, { name: string; light: Light | null; items: Plant[] }>();
  for (const p of shown) {
    const g = groups.get(p.standort.id) ?? { name: p.standort.name, light: p.standort.light, items: [] };
    g.items.push(p);
    groups.set(p.standort.id, g);
  }
  return (
    <div className="page">
      <header className="stack" style={{ gap: 12 }}>
        <div className="between">
          <h1 className="title">Pflanzen</h1>
          <a href="#/neu" className="btn primary" style={{ minHeight: 44, fontSize: 16, borderRadius: 22 }}><Icon name="plus" size={18} stroke={2.5} />Neu</a>
        </div>
        <label className="sr-only" htmlFor="q">Pflanze suchen</label>
        <input id="q" type="search" className="input" placeholder="Suchen: deutsch, lateinisch, Sorte" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="row" role="group" aria-label="Anzeige">
          <button className="seg" aria-pressed={!archived} onClick={() => setArchived(false)}>Im Garten</button>
          <button className="seg" aria-pressed={archived} onClick={() => setArchived(true)}>Archiv</button>
        </div>
      </header>
      {error && <p className="box" role="alert">{error.message}</p>}
      {!plants && !error && <p className="muted"><Waiting /></p>}
      {plants && plants.length === 0 && !archived && (
        <div className="box stack">
          <strong>Noch keine eigenen Pflanzen.</strong>
          <span>Leg deine erste Pflanze an – deutscher oder lateinischer Name, auch mit Tippfehlern.</span>
          <a href="#/neu" className="btn primary">Erste Pflanze anlegen</a>
        </div>
      )}
      {plants && plants.length === 0 && archived && <p className="box">Keine archivierten Pflanzen.</p>}
      {plants && plants.length > 0 && shown.length === 0 && <p className="box">Nichts gefunden.</p>}
      {[...groups.entries()].map(([id, g]) => (
        <section key={id} className="stack">
          <div className="between"><h2 style={{ fontSize: 18 }}>{g.name}</h2><LightChip light={g.light} /></div>
          {g.items.map((p) => (
            <a key={p.id} href={`#/pflanze/${p.id}`} className="card between" style={{ textDecoration: 'none', color: 'var(--ink)' }}>
              <span className="stack" style={{ gap: 3, minWidth: 0 }}>
                <strong style={{ fontSize: 17 }}>{plantTitle(p)}</strong>
                <span className="small muted" style={{ fontStyle: 'italic' }}>{p.species.latin}{p.cultivar ? ` ‘${p.cultivar.name}’` : ''}</span>
                {p.form && <span className="small muted">{p.form}{p.planted_year ? ` · seit ${p.planted_year}` : ''}</span>}
              </span>
              <span aria-hidden="true" style={{ fontSize: 22, color: 'var(--muted)' }}>›</span>
            </a>
          ))}
        </section>
      ))}
    </div>
  );
}

export function PlantDetail({ id }: { id: string }) {
  const [p, setP] = useState<Plant | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [tab, setTab] = useState<'plan' | 'pests' | 'history'>('plan');
  const [busy, setBusy] = useState(false);
  const [plan, setPlan] = useState<PlanState | null>(null);
  const [planFailed, setPlanFailed] = useState(false);
  const [tick, setTick] = useState(0);  // bump = load the plan state again (after a request, "neu laden")
  const [tasksKey, setTasksKey] = useState(0);  // reload the task list when a plan arrives
  const lastStatus = useRef<string | undefined>(undefined);
  useEffect(() => { api.plant(id).then(setP, (e) => setError(fail(e))); }, [id]);
  useEffect(() => { setPlan(null); setPlanFailed(false); lastStatus.current = undefined; }, [id]);
  useEffect(() => {  // poll while Claude works; retry a few times on errors; stop when the screen goes away
    let current = true;
    let timer = 0;
    let errors = 0;
    const load = () => api.plan(id).then((s) => {
      if (!current) return;
      errors = 0; setPlan(s); setPlanFailed(false);
      const st = s.job?.status;
      if (st === 'done' && lastStatus.current && lastStatus.current !== 'done') setTasksKey((k) => k + 1);
      lastStatus.current = st;
      if (st === 'queued' || st === 'running') timer = window.setTimeout(load, 4000);
    }, () => {
      if (!current) return;
      errors += 1;
      if (errors <= 5) timer = window.setTimeout(load, 4000 * errors); else setPlanFailed(true);
    });
    load();
    return () => { current = false; window.clearTimeout(timer); };
  }, [id, tick]);

  if (error?.status === 404 && plantById(id)) return <DemoPlantDetail id={id} />;
  if (!p) return <div className="page"><Back href="#/pflanzen" label="Pflanzen" /><p className="box">{error ? error.message : <Waiting />}</p></div>;

  async function makePlan() {
    setError(null);
    try { await api.requestPlan(id); } catch (e) {
      const err = fail(e);
      setError(err.status === 409 ? new ApiError(409, 'Für diese Pflanze wird gerade schon ein Plan erstellt.')
        : err.status === 429 ? new ApiError(429, 'Heute wurden schon viele Pläne erstellt. Morgen geht es wieder.') : err);
    }
    setTick((t) => t + 1);
  }
  async function toggleArchive() {
    if (!p) return;
    setBusy(true); setError(null);
    try { setP(await (p.archived ? api.restorePlant(p.id) : api.archivePlant(p.id))); } catch (e) { setError(fail(e)); } finally { setBusy(false); }
  }
  const facts = p.standort.indoor ? [
    ['Zimmer', `${p.standort.name} · ${p.standort.light}`],
    ['Fenster', p.window_dir ? (p.window_dir === 'keins' ? 'keins' : `${p.window_dir}${p.window_distance ? `, ${DISTANCES[p.window_distance]}` : ''}`) : '–'],
    ['Topf', p.pot_cm || p.pot_material ? [p.pot_cm ? `${p.pot_cm} cm` : '', p.pot_material ? POT_MATERIALS[p.pot_material] : ''].filter(Boolean).join(' ') : '–'],
    ['Seit', p.planted_year?.toString() ?? '–'],
  ] : [
    ['Standort', `${p.standort.name} · ${p.standort.light}`], ['Form', p.form ?? '–'], ['Gepflanzt', p.planted_year?.toString() ?? '–'],
    ['Im Kübel', p.in_container ? 'ja' : 'nein'], ...(p.rootstock ? [['Unterlage', p.rootstock]] : []),
    ...(p.girth_cm ? [['Stammumfang', `${p.girth_cm} cm`]] : []),
  ];
  return (
    <div className="page">
      <Back href="#/pflanzen" label="Pflanzen" />
      <div className="stack" style={{ gap: 4 }}>
        {p.archived && <span className="chip" style={{ background: 'var(--surface)', color: 'var(--muted)' }}>archiviert</span>}
        <h1 className="title-s">{plantTitle(p)}</h1>
        <span className="muted" style={{ fontStyle: 'italic' }}>{p.species.latin}{p.cultivar ? ` ‘${p.cultivar.name}’` : ' · Sorte unbekannt'}</span>
        {p.nickname && <span className="small muted">{p.species.german}</span>}
      </div>
      <div className="grid2" style={{ gap: 8 }}>
        {facts.map(([k, v]) => <div key={k} className="box" style={{ padding: '10px 12px' }}><div className="tiny">{k}</div><strong style={{ fontSize: 15 }}>{v}</strong></div>)}
      </div>
      {p.notes && <p className="box" style={{ whiteSpace: 'pre-wrap' }}>{p.notes}</p>}
      {error && <p className="box" role="alert" style={{ color: 'var(--urgent)' }}>{error.message}</p>}
      <div className="grid2">
        <a className="btn" href={`#/pflanze/${p.id}/bearbeiten`}>Bearbeiten</a>
        <button className="btn" onClick={toggleArchive} disabled={busy}>{p.archived ? 'Wiederherstellen' : 'Archivieren'}</button>
      </div>
      {!p.archived && (
        <a className="btn" href={`#/fragen-pflanze/${p.id}`} style={{ borderColor: 'var(--urgent)', color: 'var(--urgent)', fontWeight: 700 }}>
          <Icon name="camera" size={20} />Pflanze krank? Foto zeigen
        </a>
      )}
      <div className="tabs" role="tablist">
        {([['plan', 'Aufgaben'], ['pests', 'Schädlinge'], ['history', 'Verlauf']] as const).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>
      {tab === 'plan' && <CarePlanBox state={plan} failed={planFailed} archived={p.archived} onMake={makePlan} onReload={() => setTick((t) => t + 1)} />}
      {tab === 'plan' && <PlantTasks key={tasksKey} plantId={p.id} />}
      {tab === 'pests' && (plan?.plan?.pests.length
        ? [...plan.plan.pests.map((x, i) => (
          <div key={i} className="outline stack" style={{ gap: 6 }}>
            <div className="between"><strong style={{ fontSize: 17 }}>{x.name}</strong><span className="tiny">{x.time}</span></div>
            {x.prevent && <span><strong>Vorbeugen:</strong> {x.prevent}</span>}
            {x.treat && <span><strong>Bei Befall:</strong> {x.treat}</span>}
          </div>
        )), <span key="note" className="tiny">Vorschläge der KI. Pflanzenschutzmittel nur mit Zulassung für Haus- und Kleingarten verwenden – Etikett und Anwendungsbestimmungen beachten.</span>]
        : <p className="box">Typische Schädlinge und Krankheiten stehen hier, sobald es einen Pflegeplan gibt.</p>)}
      {tab === 'history' && <PlantHistory plantId={p.id} />}
      {p.species.woody && !p.standort.indoor && <span className="tiny">Gehölz: starke Rückschnitte nur 1.10.–28.2. (§ 39 BNatSchG).</span>}
      <SpeciesTraitsBox id={p.species.id} onSaved={() => api.plant(id).then(setP, () => undefined)} />
    </div>
  );
}

const CONFIDENCE = { high: 'sicher', medium: 'ziemlich sicher', low: 'unsicher – bitte prüfen' } as const;
const deDay = (iso: string) => new Date(iso).toLocaleDateString('de-DE', { day: 'numeric', month: 'short', year: 'numeric' });

function CarePlanBox({ state, failed, archived, onMake, onReload }: {
  state: PlanState | null; failed: boolean; archived: boolean; onMake: () => void; onReload: () => void;
}) {
  if (!state) {
    return failed
      ? <div className="box stack" style={{ gap: 8 }}><span role="alert">Pflegeplan konnte nicht geladen werden.</span><button className="btn" onClick={onReload}>Neu laden</button></div>
      : null;
  }
  const { plan, job } = state;
  const running = job?.status === 'queued' || job?.status === 'running';
  return (
    <div className="box stack" style={{ gap: 8 }} aria-live="polite">
      {plan && (
        <>
          <div className="between"><strong>Pflegeplan</strong><span className="tiny">{deDay(plan.created_at)} · {CONFIDENCE[plan.confidence]}</span></div>
          <span>{plan.summary}</span>
          {plan.caveats && <span className="small muted">Hinweis: {plan.caveats}</span>}
          {plan.prompt_version === 'plan-1' && <span className="small">Dieser Plan ist älter: neu erstellen, damit Termine der echten Jahreszeit folgen (z. B. „zur Forsythienblüte“).</span>}
          <span className="tiny">Erstellt von der KI und geprüft gegen die Regeln (§ 39 BNatSchG). Eigene Aufgaben bleiben beim Neu-Erstellen erhalten; bearbeitete Plan-Aufgaben werden zu eigenen.</span>
        </>
      )}
      {!plan && !running && <span>Noch kein Pflegeplan. Die KI erstellt Schnitt, Düngung, Ernte und Pflanzenschutz passend zu Sorte und Standort.</span>}
      {running && <span className="stack" style={{ gap: 4 }}><Waiting text="Die KI erstellt den Pflegeplan …" /><span className="small muted">Das dauert etwa eine Minute. Du kannst die Seite verlassen.</span></span>}
      {job?.status === 'failed' && <span role="alert" style={{ color: 'var(--urgent)' }}>{job.error ?? 'Der Plan konnte nicht erstellt werden.'}</span>}
      {!archived && !running && <button className={plan ? 'btn' : 'btn primary'} onClick={onMake}>{plan ? 'Pflegeplan neu erstellen' : 'Pflegeplan erstellen'}</button>}
    </div>
  );
}

// Species the app added (AI name search) can be corrected: woodiness decides § 39 and the
// alerts. Built-in species are reviewed data and are not offered here.
function SpeciesTraitsBox({ id, onSaved }: { id: string; onSaved: () => void }) {
  const [sp, setSp] = useState<Species | null>(null);
  const [open, setOpen] = useState(false);
  const [names, setNames] = useState('');
  const [growth, setGrowth] = useState('strauch');
  const [woody, setWoody] = useState(false);
  const [hardy, setHardy] = useState('');
  const [msg, setMsg] = useState('');
  useEffect(() => { api.species(id).then(setSp, () => undefined); }, [id]);
  if (!sp || sp.source !== 'user') return null;
  function start() { setNames(sp!.german.join(', ')); setGrowth(sp!.growth); setWoody(sp!.woody); setHardy(sp!.hardiness_c === null ? '' : String(sp!.hardiness_c)); setMsg(''); setOpen(true); }
  async function save() {
    const german = names.split(',').map((n) => n.trim()).filter(Boolean).slice(0, 5);
    if (!german.length) { setMsg('Mindestens ein deutscher Name.'); return; }
    const h = hardy.trim() === '' ? null : Number(hardy.trim().replace('\u2212', '-'));  // the app shows "−20" 
    if (h !== null && (!Number.isInteger(h) || h < -45 || h > 15)) { setMsg('Winterhärte: ganze Zahl von −45 bis 15 °C, oder leer.'); return; }
    try { setSp(await api.updateSpecies(id, { german, growth, woody, hardiness_c: h })); setOpen(false); onSaved(); } catch { setMsg('Konnte nicht gespeichert werden.'); }
  }
  return (
    <div className="box stack" style={{ gap: 8 }}>
      <span className="small">Diese Art hat die KI angelegt: {GROWTH[sp.growth as keyof typeof GROWTH] ?? sp.growth}, {sp.woody ? 'Gehölz' : 'kein Gehölz'}, winterhart bis {sp.hardiness_c === null ? '? (unbekannt)' : `${sp.hardiness_c} °C`}. Bitte prüfen – davon hängen Schnittregeln (§ 39) und Frostwarnungen ab.</span>
      {!open && <button className="btn" onClick={start}>Art-Angaben korrigieren</button>}
      {open && (
        <>
          <div className="field"><label htmlFor="sp-names">Deutsche Namen (mit Komma)</label><input id="sp-names" className="input" maxLength={300} value={names} onChange={(e) => setNames(e.target.value)} /></div>
          <div className="field">
            <label htmlFor="sp-growth">Wuchs</label>
            <select id="sp-growth" className="input" value={growth} onChange={(e) => setGrowth(e.target.value)}>
              {Object.entries(GROWTH).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </div>
          <div className="field"><label htmlFor="sp-hardy">Winterhart bis (°C, ausgepflanzt)</label><input id="sp-hardy" className="input" inputMode="text" placeholder="z. B. -20, leer = unbekannt" value={hardy} onChange={(e) => setHardy(e.target.value)} /></div>
          <div className="setrow" style={{ borderBottom: 0 }}>
            <span id="sp-woody">Gehölz (verholzt: Baum, Strauch, Rose …)</span>
            <button className="switch" role="switch" aria-checked={woody} aria-labelledby="sp-woody" onClick={() => setWoody(!woody)}><span /></button>
          </div>
          {msg && <span className="small" role="alert" style={{ color: 'var(--urgent)' }}>{msg}</span>}
          <div className="grid2"><button className="btn" onClick={() => setOpen(false)}>Abbrechen</button><button className="btn primary" onClick={save}>Speichern</button></div>
        </>
      )}
    </div>
  );
}

function PlantTasks({ plantId }: { plantId: string }) {
  const [list, setList] = useState<Task[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => { api.tasks(plantId).then(setList, () => setFailed(true)); }, [plantId]);
  return (
    <div className="stack" style={{ gap: 8 }}>
      {failed && <p className="box" role="alert">Aufgaben konnten nicht geladen werden.</p>}
      {list?.length === 0 && <p className="box">Noch keine Aufgaben für diese Pflanze. Pflegeplan erstellen lassen oder selbst anlegen.</p>}
      {list?.map((t) => (
        <a key={t.id} href={`#/aufgabe-bearbeiten/${t.id}`} className="card stack" style={{ gap: 4, textDecoration: 'none', color: 'var(--ink)', opacity: t.enabled ? 1 : 0.6 }}>
          <span className="row" style={{ gap: 6 }}><TaskChip category={t.category} />{t.source === 'plan' && <span className="tiny">Pflegeplan</span>}{!t.enabled && <span className="tiny">pausiert</span>}</span>
          <strong>{t.title}</strong>
          <span className="small muted">{timingText(t)}</span>
        </a>
      ))}
      <a className="btn" href={`#/aufgabe-neu/${plantId}`}>+ Aufgabe für diese Pflanze</a>
    </div>
  );
}

// ----- add / edit -----------------------------------------------------------

const EMPTY: PlantIn = { species_id: '', cultivar_id: null, standort_id: '', nickname: null, form: null, rootstock: null, planted_year: null, girth_cm: null, in_container: false, notes: '' };
const FIELD_TEXT: Record<string, string> = {
  species_id: 'Bitte eine Pflanze aus den Vorschlägen wählen.', standort_id: 'Bitte einen Standort wählen.',
  planted_year: 'Jahr zwischen 1900 und heute.', girth_cm: 'Stammumfang 1–1000 cm.',
};
// Field errors shown next to their input; any other invalid field shows the general box.
const INLINE = new Set(Object.keys(FIELD_TEXT));

export function PlantForm({ id }: { id?: string }) {
  const [v, setV] = useState<PlantIn>(EMPTY);
  const [query, setQuery] = useState('');
  const [cands, setCands] = useState<Candidate[]>([]);
  const [picked, setPicked] = useState<{ label: string; latin: string } | null>(null);
  const [species, setSpecies] = useState<Species | null>(null);
  const [newSorte, setNewSorte] = useState('');
  const [standorte, setStandorte] = useState<Standort[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);
  const seq = useRef(0);
  const [ai, setAi] = useState<NameJob | null>(null);  // AI lookup for the current query (F-AI-3)
  const [aiError, setAiError] = useState<string | null>(null);
  const [aiAsking, setAiAsking] = useState(false);
  const typed = query.trim();
  const typedRef = useRef(typed);  // the text now, for answers that arrive later
  typedRef.current = typed;

  useEffect(() => { api.standorte().then(setStandorte, (e) => setError(fail(e))); }, []);
  useEffect(() => {
    if (!id) return;
    api.plant(id).then((p) => {
      setV({ species_id: p.species.id, cultivar_id: p.cultivar?.id ?? null, standort_id: p.standort.id, nickname: p.nickname, form: p.form, rootstock: p.rootstock, planted_year: p.planted_year, girth_cm: p.girth_cm, in_container: p.in_container, notes: p.notes, window_dir: p.window_dir ?? null, window_distance: p.window_distance ?? null, pot_cm: p.pot_cm ?? null, pot_material: p.pot_material ?? null });
      setPicked({ label: p.species.german, latin: p.species.latin });
    }, (e) => setError(fail(e)));
  }, [id]);
  useEffect(() => {   // Sorten of the chosen species only; drop answers for an earlier choice
    let current = true;
    setSpecies(null);
    if (v.species_id) api.species(v.species_id).then((x) => { if (current) setSpecies(x); }, () => undefined);
    return () => { current = false; };
  }, [v.species_id]);
  useEffect(() => {   // debounced suggestions; only the newest answer counts
    const q = typed;
    setAi(null); setAiError(null);  // a new text makes an earlier AI answer stale
    if (!q) { setCands([]); return; }
    const n = ++seq.current;
    const t = window.setTimeout(() => api.resolve(q).then((r) => { if (n === seq.current) setCands(r.candidates); }, () => undefined), 250);
    return () => window.clearTimeout(t);
  }, [typed]);

  useEffect(() => {   // poll the AI lookup until it is finished; a few network errors are retried
    if (!ai || ai.status === 'done' || ai.status === 'failed') return;
    let current = true;
    let timer = 0;
    let tries = 0;
    let errors = 0;
    const poll = () => api.nameJob(ai.id).then((j) => {
      if (!current) return;
      errors = 0;
      if (j.status === 'done' || j.status === 'failed') { setAi(j); return; }
      if (++tries < 60) timer = window.setTimeout(poll, 2000);
      else setAiError('Die KI braucht gerade länger. Bitte später nochmal versuchen.');
    }, () => {
      if (!current) return;
      if (++errors <= 3) timer = window.setTimeout(poll, 3000 * errors);
      else setAiError('KI-Suche nicht erreichbar. Bitte nochmal versuchen.');
    });
    timer = window.setTimeout(poll, 2000);
    return () => { current = false; window.clearTimeout(timer); };
  }, [ai?.id]);  // eslint-disable-line react-hooks/exhaustive-deps

  async function askAi() {
    const q = typed;
    if (aiAsking) return;
    setAiAsking(true); setAiError(null);
    try {
      const { job_id } = await api.askNames(q);
      if (typedRef.current === q) setAi({ id: job_id, query: q, status: 'queued', error: null, candidates: [] });
    } catch (e) {
      setAiError(fail(e).status === 429 ? 'Gerade oder heute schon sehr viele KI-Suchen. Bitte später nochmal.' : fail(e).message);
    } finally { setAiAsking(false); }
  }
  async function identify(files: FileList | null) {   // plant ID by photo (M11): same AI lookup, with a photo
    const f = files?.[0];
    if (!f || aiAsking) return;
    setAiAsking(true); setAiError(null); setQuery('');
    try {
      const pid = await uploadPhoto(f);
      const { job_id } = await api.askNames('', [pid]);
      setAi({ id: job_id, query: '', status: 'queued', error: null, candidates: [] });
    } catch (e) {
      setAiError(fail(e).status === 429 ? 'Gerade oder heute schon sehr viele KI-Suchen. Bitte später nochmal.' : fail(e).message);
    } finally { setAiAsking(false); }
  }
  async function pickAi(index: number) {
    if (!ai) return;
    try {
      const r = await api.pickName(ai.id, index);
      set({ species_id: r.species_id, cultivar_id: r.cultivar_id, form: r.form_hint ?? v.form });
      setPicked({ label: r.german, latin: r.latin });
      setNewSorte(''); setQuery(''); setCands([]);
    } catch (e) { setAiError(fail(e).message); }
  }

  const set = (patch: Partial<PlantIn>) => setV((x) => ({ ...x, ...patch }));
  function pick(c: Candidate) {
    set({ species_id: c.species_id, cultivar_id: c.cultivar_id, form: c.form_hint ?? v.form });
    setPicked({ label: c.german, latin: c.latin });
    setNewSorte(c.cultivar_id ? '' : c.unmatched);
    setQuery(''); setCands([]);
  }

  async function save() {
    setSaving(true); setError(null);
    try {
      let cultivarId = v.cultivar_id;
      if (!cultivarId && newSorte.trim() && v.species_id) {   // the API returns an existing Sorte in any spelling
        cultivarId = (await api.createCultivar(v.species_id, newSorte.trim())).id;
      }
      const body = indoor ? { ...v, cultivar_id: cultivarId, in_container: true }
        : { ...v, cultivar_id: cultivarId, window_dir: null, window_distance: null, pot_cm: null, pot_material: null };
      const p = id ? await api.updatePlant(id, body) : await api.createPlant(body);
      window.location.hash = `#/pflanze/${p.id}`;
    } catch (e) { setError(fail(e)); } finally { setSaving(false); }
  }
  const fieldError = (f: string) => (error?.fields[f] ? FIELD_TEXT[f] ?? 'Ungültig.' : null);
  const indoor = standorte.find((s) => s.id === v.standort_id)?.type === INDOOR_TYPE;
  const num = (s: string) => (s.trim() === '' ? null : Number.isFinite(Number(s)) ? Number(s) : -1);

  return (
    <div className="page">
      <Back href={id ? `#/pflanze/${id}` : '#/pflanzen'} label="Abbrechen" />
      <h1 className="title-s">{id ? 'Pflanze bearbeiten' : 'Pflanze hinzufügen'}</h1>

      <div className="field">
        <label htmlFor="name">Name (deutsch oder lateinisch, gern mit Sorte)</label>
        <input id="name" className="input" autoComplete="off" placeholder="z. B. Säulenapfel Sonate" value={query}
          onChange={(e) => setQuery(e.target.value)} style={{ border: '2px solid var(--green)' }} />
        {picked && !query && <span className="small">Gewählt: <strong>{picked.label}</strong> <i className="muted">{picked.latin}</i></span>}
        {fieldError('species_id') && <span className="small" style={{ color: 'var(--urgent)' }}>{fieldError('species_id')}</span>}
      </div>
      <PhotoIdButton busy={aiAsking} onPick={identify} />
      {!query.trim() && ai && <AiSuggestions ai={ai} error={aiError} canAsk={false} onAsk={askAi} onPick={pickAi} />}
      {!query.trim() && !ai && aiError && <span className="small" role="alert" style={{ color: 'var(--urgent)' }}>{aiError}</span>}
      <span className="sr-only" aria-live="polite">{query.trim() ? `${cands.length} Vorschläge` : ''}</span>
      {query.trim() && (
        <div className="stack" aria-label="Vorschläge">
          {cands.length === 0 && <span className="small muted">Keine Vorschläge. Anders schreiben – oder die KI fragen.</span>}
          {cands.map((c) => (
            <button key={`${c.species_id}-${c.cultivar_id}`} className="option" onClick={() => pick(c)}>
              <span className="stack" style={{ gap: 3 }}>
                <strong style={{ fontSize: 17 }}>{c.german}{c.cultivar_name ? ` ‘${c.cultivar_name}’` : ''}</strong>
                <span className="small muted" style={{ fontStyle: 'italic' }}>{c.latin}</span>
                {c.unmatched && <span className="small">Sorte ‘{c.unmatched}’ noch unbekannt – wird neu angelegt</span>}
                {c.form_hint && <span className="small">Form: {c.form_hint}</span>}
              </span>
              <span className="radio" />
            </button>
          ))}
          <AiSuggestions ai={ai} error={aiError} canAsk={typed.length >= 2 && !aiAsking} onAsk={askAi} onPick={pickAi} />
        </div>
      )}

      {v.species_id && (
        <div className="field">
          <label htmlFor="sorte">Sorte</label>
          <select id="sorte" className="input" value={v.cultivar_id ?? (newSorte ? '__new' : '')}
            onChange={(e) => { const x = e.target.value; set({ cultivar_id: x && x !== '__new' ? x : null }); if (x !== '__new') setNewSorte(''); else setNewSorte(newSorte || ' '); }}>
            <option value="">unbekannt</option>
            {species?.cultivars.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            <option value="__new">+ andere Sorte …</option>
          </select>
          {!v.cultivar_id && newSorte !== '' && (
            <input className="input" aria-label="Neue Sorte" placeholder="Name der Sorte" value={newSorte.trimStart()} onChange={(e) => setNewSorte(e.target.value)} />
          )}
        </div>
      )}

      <StandortPicker standorte={standorte} value={v.standort_id} onChange={(sid) => set({ standort_id: sid })}
        onCreated={(s) => { setStandorte((xs) => [...xs, s].sort((a, b) => a.name.localeCompare(b.name))); set({ standort_id: s.id }); }} />
      {fieldError('standort_id') && <span className="small" style={{ color: 'var(--urgent)' }}>{fieldError('standort_id')}</span>}
      {indoor && <IndoorFields v={v} set={set} num={num} />}

      <div className="grid2">
        <div className="field">
          <label htmlFor="form">Wuchsform</label>
          <select id="form" className="input" value={v.form ?? ''} onChange={(e) => set({ form: (e.target.value || null) as Form | null })}>
            <option value="">–</option>
            {FORMS.map((f) => <option key={f}>{f}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="year">Gepflanzt (Jahr)</label>
          <input id="year" className="input" inputMode="numeric" value={v.planted_year ?? ''} onChange={(e) => set({ planted_year: num(e.target.value) })} aria-invalid={!!fieldError('planted_year')} />
        </div>
      </div>
      {fieldError('planted_year') && <span className="small" style={{ color: 'var(--urgent)' }}>{fieldError('planted_year')}</span>}
      <div className="field">
        <label htmlFor="nick">Spitzname (optional)</label>
        <input id="nick" className="input" maxLength={60} placeholder="z. B. Apfel am Weg" value={v.nickname ?? ''} onChange={(e) => set({ nickname: e.target.value || null })} />
      </div>
      {!indoor && <div className="setrow" style={{ borderBottom: 0 }}>
        <span id="kuebel-label">Im Kübel</span>
        <button className="switch" role="switch" aria-checked={v.in_container} aria-labelledby="kuebel-label" onClick={() => set({ in_container: !v.in_container })}><span /></button>
      </div>}
      <details>
        <summary style={{ minHeight: 44, display: 'flex', alignItems: 'center', cursor: 'pointer', fontWeight: 700 }}>Mehr Angaben (Unterlage, Stammumfang, Notizen)</summary>
        <div className="stack" style={{ gap: 12 }}>
          <div className="grid2">
            <div className="field"><label htmlFor="root">Unterlage</label><input id="root" className="input" maxLength={40} placeholder="z. B. M9" value={v.rootstock ?? ''} onChange={(e) => set({ rootstock: e.target.value || null })} /></div>
            <div className="field"><label htmlFor="girth">Stammumfang (cm)</label><input id="girth" className="input" inputMode="numeric" value={v.girth_cm ?? ''} onChange={(e) => set({ girth_cm: num(e.target.value) })} /></div>
          </div>
          {fieldError('girth_cm') && <span className="small" style={{ color: 'var(--urgent)' }}>{fieldError('girth_cm')}</span>}
          <div className="field"><label htmlFor="notes">Notizen</label><textarea id="notes" className="input" maxLength={1000} rows={3} value={v.notes} onChange={(e) => set({ notes: e.target.value })} /></div>
        </div>
      </details>

      {error && (Object.keys(error.fields).length === 0 || Object.keys(error.fields).some((f) => !INLINE.has(f))) && (
        <p className="box" role="alert" style={{ color: 'var(--urgent)' }}>{error.message}</p>
      )}
      <button className="btn primary" onClick={save} disabled={saving || !v.species_id || !v.standort_id}>
        {saving ? <Waiting text="Speichert …" /> : id ? 'Speichern' : 'Pflanze anlegen'}
      </button>
      {!id && <span className="tiny" style={{ textAlign: 'center' }}>Den Pflegeplan erstellt die KI danach von selbst{indoor ? ' – mit Gieß-Rhythmus' : ''}.</span>}
    </div>
  );
}

function PhotoIdButton({ busy, onPick }: { busy: boolean; onPick: (files: FileList | null) => void }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <input ref={input} type="file" accept="image/*" hidden onChange={(e) => { onPick(e.target.files); e.target.value = ''; }} />
      <button className="btn" disabled={busy} onClick={() => input.current?.click()}>
        {busy ? <Waiting text="Foto wird geladen …" /> : <><Icon name="camera" size={20} />Per Foto bestimmen</>}
      </button>
    </>
  );
}

function Segments<K extends string>({ label, options, value, onChange }: { label: string; options: Record<K, string>; value: K | null | undefined; onChange: (k: K | null) => void }) {
  return (
    <div className="stack" style={{ gap: 6 }}>
      <span className="label">{label}</span>
      <div className="row" role="group" aria-label={label}>
        {(Object.entries(options) as [K, string][]).map(([k, text]) => (
          <button key={k} className="seg" aria-pressed={value === k} onClick={() => onChange(value === k ? null : k)}>{text}</button>
        ))}
      </div>
    </div>
  );
}

function IndoorFields({ v, set, num }: { v: PlantIn; set: (p: Partial<PlantIn>) => void; num: (s: string) => number | null }) {
  return (
    <div className="stack" style={{ gap: 12 }}>
      <Segments label="Fenster in Richtung" options={WINDOWS} value={v.window_dir} onChange={(k) => set({ window_dir: k })} />
      <Segments label="Abstand zum Fenster" options={DISTANCES} value={v.window_distance} onChange={(k) => set({ window_distance: k })} />
      <div className="grid2">
        <div className="field"><label htmlFor="pot">Topf Ø (cm)</label><input id="pot" className="input" inputMode="numeric" value={v.pot_cm ?? ''} onChange={(e) => set({ pot_cm: num(e.target.value) })} /></div>
        <div className="field"><label htmlFor="mat">Topf-Material</label>
          <select id="mat" className="input" value={v.pot_material ?? ''} onChange={(e) => set({ pot_material: (e.target.value || null) as PlantIn['pot_material'] })}>
            <option value="">–</option>
            {Object.entries(POT_MATERIALS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
        </div>
      </div>
      <span className="tiny">Licht, Topf und Jahreszeit bestimmen den Gieß-Rhythmus. Frostwarnungen und Schnittregeln gelten drinnen nicht.</span>
    </div>
  );
}

function InOut({ indoor, onChange }: { indoor: boolean; onChange: (indoor: boolean) => void }) {
  return (
    <div className="row" role="group" aria-label="Drinnen oder draußen">
      <button className="seg" aria-pressed={!indoor} onClick={() => onChange(false)}>Draußen</button>
      <button className="seg" aria-pressed={indoor} onClick={() => onChange(true)}>Drinnen</button>
    </div>
  );
}

function AiSuggestions({ ai, error, canAsk, onAsk, onPick }: {
  ai: NameJob | null; error: string | null; canAsk: boolean; onAsk: () => void; onPick: (index: number) => void;
}) {
  const busy = ai?.status === 'queued' || ai?.status === 'running';
  const label = (c: AiCandidate) => `${c.german[0]}${c.cultivar ? ` ‘${c.cultivar}’` : ''}`;
  return (
    <div className="stack" style={{ gap: 8 }} aria-live="polite">
      {!ai && canAsk && <button className="btn" onClick={onAsk}>Nicht dabei? Mit KI suchen</button>}
      {busy && <Waiting className="small" text="Die KI sucht … (etwa 10–20 Sekunden)" />}
      {ai?.status === 'failed' && <span className="small" role="alert" style={{ color: 'var(--urgent)' }}>{ai.error}</span>}
      {ai?.status === 'done' && ai.candidates.length === 0 && <span className="small muted">Die KI kennt diese Pflanze auch nicht. Anders schreiben?</span>}
      {ai?.status === 'done' && ai.candidates.map((c, i) => (
        <button key={i} className="option" onClick={() => onPick(i)}>
          <span className="stack" style={{ gap: 3 }}>
            <span className="row" style={{ gap: 6 }}><span className="chip" style={{ background: 'var(--legal-tint)', color: 'var(--legal-ink)' }}>KI</span><strong style={{ fontSize: 17 }}>{label(c)}</strong></span>
            <span className="small muted" style={{ fontStyle: 'italic' }}>{c.latin}{c.family ? ` · ${c.family}` : ''}</span>
            {c.note && <span className="small">{c.note}</span>}
            {!c.known_species_id && <span className="small">Neue Art – wird angelegt</span>}
            {c.form_hint && <span className="small">Form: {c.form_hint}</span>}
          </span>
          <span className="radio" />
        </button>
      ))}
      {error && <span className="small" role="alert" style={{ color: 'var(--urgent)' }}>{error}</span>}
    </div>
  );
}

function StandortPicker({ standorte, value, onChange, onCreated }: { standorte: Standort[]; value: string; onChange: (id: string) => void; onCreated: (s: Standort) => void }) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('');
  const [light, setLight] = useState<Light>('sonnig');
  const [inside, setInside] = useState(false);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  async function add() {
    if (busy) return;
    setErr(''); setBusy(true);
    try { onCreated(await api.createStandort({ name, light, type: inside ? INDOOR_TYPE : 'beet', notes: '' })); setAdding(false); setName(''); }
    catch (e) { setErr(e instanceof ApiError && e.status === 409 ? 'Diesen Standort gibt es schon.' : e instanceof ApiError && e.status === 422 ? 'Bitte einen Namen (max. 60 Zeichen) eingeben.' : fail(e).message); }
    finally { setBusy(false); }
  }
  return (
    <div className="stack">
      <span className="label">Standort</span>
      <div className="row" role="group" aria-label="Standort">
        {standorte.map((s) => <button key={s.id} className="seg" aria-pressed={value === s.id} onClick={() => onChange(s.id)}>{s.name}{s.type === INDOOR_TYPE ? ' (drinnen)' : ''}</button>)}
        <button className="seg" aria-pressed={adding} onClick={() => setAdding(!adding)}>+ Neuer Standort</button>
      </div>
      {adding && (
        <div className="outline stack" style={{ gap: 10 }}>
          <InOut indoor={inside} onChange={setInside} />
          <div className="field"><label htmlFor="sname">Name</label><input id="sname" className="input" maxLength={60} value={name} onChange={(e) => setName(e.target.value)} placeholder={inside ? 'z. B. Wohnzimmer' : 'z. B. Beet am Zaun'} /></div>
          <div className="row" role="group" aria-label="Licht">
            {(['sonnig', 'halbschattig', 'schattig'] as Light[]).map((l) => <button key={l} className="seg" aria-pressed={light === l} onClick={() => setLight(l)}>{l}</button>)}
          </div>
          {err && <span className="small" style={{ color: 'var(--urgent)' }}>{err}</span>}
          <button className="btn" onClick={add} disabled={busy}>{busy ? 'Legt an …' : 'Standort anlegen'}</button>
          <span className="tiny">Art und Notizen später unter Mehr → Standorte.</span>
        </div>
      )}
    </div>
  );
}

// ----- Standorte (Mehr → Standorte) --------------------------------------------

export function Standorte() {
  const [list, setList] = useState<Standort[] | null>(null);
  const [edit, setEdit] = useState<Standort | 'new' | null>(null);
  const [msg, setMsg] = useState('');
  const load = () => api.standorte().then(setList, (e) => setMsg(fail(e).message));
  useEffect(() => { load(); }, []);
  async function remove(s: Standort) {
    setMsg('');
    try { await api.deleteStandort(s.id); load(); }
    catch (e) { setMsg(e instanceof ApiError && e.status === 409 ? `„${s.name}“ hat noch Pflanzen (auch archivierte) und kann nicht gelöscht werden.` : fail(e).message); }
  }
  return (
    <div className="page">
      <Back href="#/mehr" label="Mehr" />
      <div className="between"><h1 className="title-s">Standorte</h1><button className="btn" onClick={() => setEdit('new')}>+ Neu</button></div>
      <span className="small muted">Orte im Garten und Zimmer im Haus, mit Licht – wichtig für Pflege, Gießen und Wetterwarnungen.</span>
      {msg && <p className="box" role="alert">{msg}</p>}
      {edit && <StandortEditor s={edit === 'new' ? null : edit} onDone={() => { setEdit(null); load(); }} />}
      {list?.length === 0 && !edit && <p className="box">Noch keine Standorte. Sie entstehen auch beim Anlegen einer Pflanze.</p>}
      {list?.map((s) => (
        <div key={s.id} className="card stack" style={{ gap: 6 }}>
          <div className="between"><strong style={{ fontSize: 17 }}>{s.name}</strong><LightChip light={s.light} /></div>
          <span className="small muted">{s.type === INDOOR_TYPE ? 'Drinnen' : `Draußen · ${STANDORT_TYPES[s.type]}`} · {s.plant_count} {s.plant_count === 1 ? 'Pflanze' : 'Pflanzen'}{s.notes ? ` · ${s.notes}` : ''}</span>
          <div className="grid2"><button className="btn" onClick={() => setEdit(s)}>Bearbeiten</button><button className="btn" onClick={() => remove(s)}>Löschen</button></div>
        </div>
      ))}
    </div>
  );
}

function StandortEditor({ s, onDone }: { s: Standort | null; onDone: () => void }) {
  const [v, setV] = useState({ name: s?.name ?? '', light: s?.light ?? ('sonnig' as Light), type: s?.type ?? ('beet' as Standort['type']), notes: s?.notes ?? '' });
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  async function save() {
    if (busy) return;
    setErr(''); setBusy(true);
    try { if (s) await api.updateStandort(s.id, v); else await api.createStandort(v); onDone(); }
    catch (e) { setErr(e instanceof ApiError && e.status === 409 ? (e.message.includes('indoor') ? 'Mit Pflanzen kann ein Standort nicht zwischen drinnen und draußen wechseln.' : 'Diesen Namen gibt es schon.') : e instanceof ApiError && e.status === 422 ? 'Bitte Eingaben prüfen (Name 1–60 Zeichen).' : fail(e).message); }
    finally { setBusy(false); }
  }
  return (
    <div className="outline stack" style={{ gap: 12 }}>
      <div className="field"><label htmlFor="sn">Name</label><input id="sn" className="input" maxLength={60} value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} /></div>
      <div className="row" role="group" aria-label="Licht">
        {(['sonnig', 'halbschattig', 'schattig'] as Light[]).map((l) => <button key={l} className="seg" aria-pressed={v.light === l} onClick={() => setV({ ...v, light: l })}>{l}</button>)}
      </div>
      <InOut indoor={v.type === INDOOR_TYPE} onChange={(inside) => setV({ ...v, type: inside ? INDOOR_TYPE : 'beet' })} />
      {v.type === INDOOR_TYPE
        ? <span className="small muted">Ein Zimmer: Pflanzen hier bekommen Gieß-Erinnerungen, aber keine Frost- und Wetterwarnungen.</span>
        : (
          <div className="field"><label htmlFor="st">Art</label>
            <select id="st" className="input" value={v.type} onChange={(e) => setV({ ...v, type: e.target.value as Standort['type'] })}>
              {Object.entries(STANDORT_TYPES).filter(([k]) => k !== INDOOR_TYPE).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </select>
          </div>
        )}
      <div className="field"><label htmlFor="sno">Notizen</label><input id="sno" className="input" maxLength={500} value={v.notes} onChange={(e) => setV({ ...v, notes: e.target.value })} /></div>
      {err && <span className="small" style={{ color: 'var(--urgent)' }}>{err}</span>}
      <div className="grid2"><button className="btn" onClick={onDone}>Abbrechen</button><button className="btn" style={{ background: 'var(--green)', color: 'var(--green-ink)', border: 0, fontWeight: 700 }} onClick={save} disabled={busy}>{busy ? 'Speichert …' : 'Speichern'}</button></div>
    </div>
  );
}

// ----- history: done/skipped to-dos and saved diagnoses (M9) -----------------

function PlantHistory({ plantId }: { plantId: string }) {
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  const [error, setError] = useState('');
  useEffect(() => { api.history(plantId).then(setItems, (e) => setError(fail(e).message)); }, [plantId]);
  if (error) return <p className="box" role="alert" style={{ color: 'var(--urgent)' }}>{error}</p>;
  if (!items) return <p className="muted"><Waiting /></p>;
  if (!items.length) return <p className="box">Noch nichts erledigt. Hier stehen später erledigte Aufgaben und gespeicherte Diagnosen.</p>;
  const day = (iso: string) => new Date(iso).toLocaleDateString('de-DE', { day: 'numeric', month: 'numeric', year: '2-digit' });
  return (
    <div className="stack" style={{ gap: 4 }}>
      {items.map((h) => (
        <div key={h.kind + h.id} className="planrow" style={{ gridTemplateColumns: '72px minmax(0, 1fr)' }}>
          <span className="small muted">{day(h.at)}</span>
          {h.kind === 'diagnose' ? (
            <span className="stack" style={{ gap: 4 }}>
              <TaskChip category="pflanzenschutz" />
              <strong>Diagnose: {h.title}</strong>
              <span className="small muted">{h.confidence}{h.cause ? ` · ${h.cause}` : ''}</span>
              {h.photos.length > 0 && <PhotoThumbs ids={h.photos} width={80} label="Foto der Diagnose" />}
            </span>
          ) : (
            <span className="stack" style={{ gap: 2 }}>
              <strong>{h.status === 'done' ? '✓' : '–'} {h.title}{h.status === 'skipped' ? ' (übersprungen)' : ''}</strong>
              {h.note && <span className="small muted">„{h.note}“</span>}
            </span>
          )}
        </div>
      ))}
      <span className="tiny">Die KI sieht den Verlauf bei späteren Fragen zu dieser Pflanze.</span>
    </div>
  );
}

// ----- demo plant (links from the demo Heute / Kalender until M3) ------------

function DemoPlantDetail({ id }: { id: string }) {
  const p = plantById(id)!;
  const [tab, setTab] = useState<'plan' | 'pests' | 'history'>('plan');
  const site = standortById(p.standortId);
  return (
    <div className="page">
      <Back href="#/heute" label="Heute" />
      <span className="chip" style={{ background: 'var(--legal-tint)', color: 'var(--legal-ink)' }}>Beispiel aus der Vorschau</span>
      <div className="stack" style={{ gap: 4 }}>
        <h1 className="title-s">{p.name}</h1>
        <span className="muted" style={{ fontStyle: 'italic' }}>{p.latin}</span>
      </div>
      <div className="grid2" style={{ gap: 8 }}>
        {[['Standort', `${site?.name} · ${site?.light}`], ['Form', p.form], ['Gepflanzt', String(p.planted)], ['Winterhart', p.hardy]].map(([k, v]) => (
          <div key={k} className="box" style={{ padding: '10px 12px' }}><div className="tiny">{k}</div><strong style={{ fontSize: 15 }}>{v}</strong></div>
        ))}
      </div>
      <div className="tabs" role="tablist">
        {([['plan', 'Pflegeplan'], ['pests', 'Schädlinge'], ['history', 'Verlauf']] as const).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>
      {tab === 'plan' && (
        <div className="stack" style={{ gap: 4 }}>
          {p.id === 'rhapsodie' && <Legal>Regelprüfung: 1 Aufgabe angepasst. „Starker Verjüngungsschnitt“ von April auf Februar verschoben (§ 39 BNatSchG).</Legal>}
          {p.plan.map((t) => (
            <div key={t.title} className="planrow">
              <strong style={{ color: 'var(--green)' }}>{MONTHS[t.month].slice(0, 3)}</strong>
              <span className="stack" style={{ gap: 3 }}><Chip category={t.category} /><strong>{t.title}</strong><span className="small muted">{t.detail}</span></span>
            </div>
          ))}
        </div>
      )}
      {tab === 'pests' && p.pests.map((x) => (
        <div key={x.name} className="outline stack" style={{ gap: 6 }}>
          <div className="between"><strong style={{ fontSize: 17 }}>{x.name}</strong><span className="tiny">{x.time}</span></div>
          <span><strong>Vorbeugen:</strong> {x.prevent}</span>
          <span><strong>Bei Befall:</strong> {x.treat}</span>
        </div>
      ))}
      {tab === 'history' && p.history.map((h) => (
        <div key={h.date + h.title} className="planrow" style={{ gridTemplateColumns: '72px minmax(0, 1fr)' }}>
          <span className="small muted">{h.date}</span>
          <span className="stack" style={{ gap: 2 }}><strong>✓ {h.title}</strong>{h.note && <span className="small muted">{h.note}</span>}</span>
        </div>
      ))}
    </div>
  );
}
