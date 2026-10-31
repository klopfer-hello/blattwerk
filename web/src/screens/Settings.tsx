import { useEffect, useState } from 'react';
import { ApiError, BUNDESLAENDER, api, type Fertiliser, type GardenSettings } from '../api';
import { Back } from '../components/ui';

export const FERTILISER: Record<Fertiliser, string> = { gemischt: 'Gemischt', organisch: 'Organisch', mineralisch: 'Mineralisch' };

const FIELD_TEXT: Record<string, string> = {
  'location.plz': 'Die PLZ hat 5 Ziffern.',
  'location.ort': 'Ort: höchstens 80 Zeichen',
  'location.bundesland': 'Bundesland',
  'legal.baumschutz_girth_cm': 'Zwischen 10 und 500 cm – oder leer lassen.',
};

export function Settings() {
  const [s, setS] = useState<GardenSettings | null>(null);
  const [girth, setGirth] = useState('');
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.settings().then((v) => { setS(v); setGirth(v.legal.baumschutz_girth_cm?.toString() ?? ''); }, setError);
  }, []);

  if (!s) {
    return (
      <div className="page">
        <Back href="#/wetter" label="Wetter & Jahreszeit" />
        <h1 className="title-s">Einstellungen</h1>
        <p className="box">{error ? error.message : 'Lädt …'}</p>
      </div>
    );
  }

  const set = <K extends keyof GardenSettings>(k: K, v: Partial<GardenSettings[K]>) => { setSaved(false); setS({ ...s, [k]: { ...s[k], ...v } }); };
  const fieldError = (f: string) => (error?.fields[f] ? FIELD_TEXT[f] ?? 'Ungültig.' : null);

  async function save() {
    if (!s) return;
    const n = girth.trim() === '' ? null : Number(girth);
    setSaving(true); setError(null);
    try {
      // A non-number is sent as -1 so the server answers with the field error.
      const girthCm = n === null ? null : Number.isFinite(n) ? n : -1;
      const v = await api.saveSettings({ ...s, legal: { ...s.legal, baumschutz_girth_cm: girthCm } });
      setS(v); setSaved(true);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, 'Unbekannter Fehler'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page">
      <Back href="#/wetter" label="Wetter & Jahreszeit" />
      <div className="stack" style={{ gap: 4 }}>
        <h1 className="title-s">Einstellungen</h1>
        <span className="small muted">Gelten für alle im Haushalt. Werden nur auf eurem Server gespeichert.</span>
      </div>

      <section className="stack" style={{ gap: 12 }}>
        <h2 className="eyebrow">Garten</h2>
        <div className="grid2" style={{ gridTemplateColumns: '120px minmax(0, 1fr)' }}>
          <div className="field">
            <label htmlFor="plz">PLZ</label>
            <input id="plz" className="input" inputMode="numeric" maxLength={5} autoComplete="off" value={s.location.plz ?? ''}
              aria-invalid={!!fieldError('location.plz')} onChange={(e) => set('location', { plz: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="ort">Ort</label>
            <input id="ort" className="input" maxLength={80} autoComplete="off" value={s.location.ort ?? ''}
              onChange={(e) => set('location', { ort: e.target.value })} />
          </div>
        </div>
        {fieldError('location.plz') && <span className="small" style={{ color: 'var(--urgent)' }}>{fieldError('location.plz')}</span>}
        <div className="field">
          <label htmlFor="land">Bundesland</label>
          <select id="land" className="input" value={s.location.bundesland ?? ''}
            onChange={(e) => set('location', { bundesland: (e.target.value || null) as GardenSettings['location']['bundesland'] })}>
            <option value="">– bitte wählen –</option>
            {BUNDESLAENDER.map((b) => <option key={b}>{b}</option>)}
          </select>
          <span className="tiny">Für Wetter, Jahreszeit und die Regeln deines Bundeslands.</span>
        </div>
      </section>

      <section className="stack" style={{ gap: 12 }}>
        <h2 className="eyebrow">Pflege</h2>
        <div className="stack">
          <span className="label">Dünger</span>
          <div className="row" role="group" aria-label="Dünger">
            {(['gemischt', 'organisch', 'mineralisch'] as Fertiliser[]).map((f) => (
              <button key={f} className="seg" aria-pressed={s.preferences.fertiliser === f} onClick={() => set('preferences', { fertiliser: f })}>{FERTILISER[f]}</button>
            ))}
          </div>
        </div>
        <Toggle id="eco" label="Ökologische Empfehlungen" hint="z. B. Samenstände über den Winter stehen lassen" checked={s.preferences.eco_defaults}
          onChange={(v) => set('preferences', { eco_defaults: v })} />
      </section>

      <section className="stack" style={{ gap: 12 }}>
        <h2 className="eyebrow">Baumschutzsatzung der Gemeinde</h2>
        <div className="field">
          <label htmlFor="girth">Geschützt ab Stammumfang (cm)</label>
          <input id="girth" className="input" inputMode="numeric" placeholder="leer = keine Satzung" value={girth}
            aria-invalid={!!fieldError('legal.baumschutz_girth_cm')} onChange={(e) => { setSaved(false); setGirth(e.target.value); }} />
          {fieldError('legal.baumschutz_girth_cm') && <span className="small" style={{ color: 'var(--urgent)' }}>{fieldError('legal.baumschutz_girth_cm')}</span>}
        </div>
        <Toggle id="fruit" label="Obstbäume ausgenommen" checked={s.legal.fruit_trees_exempt} onChange={(v) => set('legal', { fruit_trees_exempt: v })} />
      </section>

      <section className="stack" style={{ gap: 12 }}>
        <h2 className="eyebrow">Benachrichtigungen</h2>
        <Toggle id="push" label="Push bei Wetter-Warnungen" hint="Kommt mit dem Wetter-Modul" checked={s.notifications.weather_push}
          onChange={(v) => set('notifications', { weather_push: v })} />
      </section>

      {error && <ErrorBox error={error} />}
      <button className={saved ? 'btn primary done' : 'btn primary'} onClick={save} disabled={saving}>
        {saving ? 'Speichert …' : saved ? '✓ Gespeichert' : 'Speichern'}
      </button>
    </div>
  );
}

// Fields shown inline next to their input; any other invalid field is listed here.
const INLINE = new Set(['location.plz', 'legal.baumschutz_girth_cm']);

function ErrorBox({ error }: { error: ApiError }) {
  const other = Object.keys(error.fields).filter((f) => !INLINE.has(f));
  if (Object.keys(error.fields).length > 0 && other.length === 0) return null;
  return (
    <div className="box" role="alert" style={{ color: 'var(--urgent)' }}>
      {other.length > 0 ? <>Bitte prüfen: {other.map((f) => FIELD_TEXT[f] ?? f).join(', ')}</> : error.message}
    </div>
  );
}

function Toggle({ id, label, hint, checked, onChange }: { id: string; label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="setrow" style={{ borderBottom: 0 }}>
      <span className="stack" style={{ gap: 2 }}>
        <span id={`${id}-label`}>{label}</span>
        {hint && <span className="tiny">{hint}</span>}
      </span>
      <button className="switch" role="switch" aria-checked={checked} aria-labelledby={`${id}-label`} onClick={() => onChange(!checked)}><span /></button>
    </div>
  );
}
