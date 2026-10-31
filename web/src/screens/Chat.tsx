// Fragen (M8): the garden chat. A list of chats, and a chat whose answer streams in
// (server-sent events from the api while the worker writes it). Claude only proposes
// to-dos, notes and diagnoses; they become real with "Ja" here. Plant doctor (M9): up to
// three photos per question, and #/fragen-pflanze/<id> starts a chat about one plant.
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { ApiError, api, type Ask, type ChatAction, type ChatFull, type ChatSummary } from '../api';
import { Back, Icon, deDate, Waiting } from '../components/ui';
import { PhotoThumbs } from '../components/Photos';
import { photoUrl, uploadPhoto } from '../photos';

const MAX_PHOTOS = 3;
const PHOTO_QUESTION = 'Was hat meine Pflanze?';

const ASK_ERR: Record<number, string> = {
  409: 'Die vorige Antwort wird noch geschrieben.',
  429: 'Für heute sind genug Fragen gestellt. Morgen geht es weiter.',
};
const ACTION_ERR: Record<string, string> = {
  'already decided': 'Schon entschieden.', 'proposal expired': 'Der Vorschlag ist älter als eine Woche – bitte neu fragen.',
  'plant archived or deleted': 'Die Pflanze gibt es nicht mehr.', 'plant notes are full': 'Die Notizen der Pflanze sind voll.',
};
const ASK_422 = 'Ein Foto ist abgelaufen oder schon verschickt – bitte neu auswählen.';
const errText = (e: unknown) => (e instanceof ApiError ? ASK_ERR[e.status] ?? (e.status === 422 && e.fields.photo_ids ? ASK_422 : e.message) : 'Server nicht erreichbar.');
const actionErr = (e: unknown) => (e instanceof ApiError ? ACTION_ERR[e.message] ?? (e.status === 409 ? 'Das geht so nicht mehr (Datum vorbei?).' : e.message) : 'Server nicht erreichbar.');
const CATEGORY_DE: Record<string, string> = { schnitt: 'Schnitt', duengen: 'Düngen', ernte: 'Ernte', pflanzenschutz: 'Pflanzenschutz', winterschutz: 'Winterschutz', aussaat: 'Aussaat', sonstiges: 'Sonstiges', giessen: 'Gießen', bespruehen: 'Besprühen', entstauben: 'Entstauben' };

// **fett** and "- " lists, nothing else: the answer is text from the AI, rendered as text (no HTML).
function Rich({ text }: { text: string }) {
  const inline = (s: string, key: string): ReactNode[] =>
    s.split(/(\*\*[^*]+\*\*)/g).map((part, i) => (part.startsWith('**') && part.endsWith('**') && part.length > 4
      ? <strong key={`${key}-${i}`}>{part.slice(2, -2)}</strong> : <span key={`${key}-${i}`}>{part}</span>));
  return (
    <>
      {text.split('\n').filter((l, i, all) => l.trim() || (i > 0 && all[i - 1].trim())).map((line, i) => {
        const bullet = /^\s*[-*•]\s+/.test(line);
        const body = line.replace(/^\s*[-*•]\s+/, '').replace(/^#+\s*/, '');
        return line.trim() ? <span key={i}>{bullet ? '• ' : ''}{inline(body, String(i))}</span> : <span key={i} style={{ height: 4 }} />;
      })}
    </>
  );
}

function ActionCard({ a, onDecided }: { a: ChatAction; onDecided: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const p = a.payload;
  const instructions = String(p.instructions ?? '');
  const what = a.kind === 'aufgabe' ? (
    <>
      Aufgabe anlegen?<br /><strong>„{String(p.title)}“</strong> am {deDate(String(p.due_date))}
      <span className="small muted" style={{ display: 'block' }}>
        {CATEGORY_DE[String(p.category)] ?? String(p.category)}{p.cut_type === 'stark' ? ' (starker Schnitt)' : ''}{a.plant ? ` · ${a.plant}` : ''}
      </span>
      {instructions && <span className="small" style={{ display: 'block', whiteSpace: 'pre-wrap' }}>{instructions.length > 240 ? `${instructions.slice(0, 240)} …` : instructions}</span>}
    </>
  ) : a.kind === 'diagnose' ? (
    <span className="stack" style={{ gap: 6 }}>
      <span className="eyebrow">Diagnose speichern?</span>
      <strong style={{ fontSize: 18 }}>{String(p.title)}</strong>
      <span className="small">Sicherheit: <strong>{String(p.confidence)}</strong>{p.cause ? ` · Ursache: ${String(p.cause)}` : ''}</span>
      <span className="small muted">Kommt in den Verlauf{a.plant ? ` von ${a.plant}` : ''} – mit den Fotos.</span>
    </span>
  ) : <>Notiz speichern bei <strong>{a.plant ?? 'unbekannter Pflanze'}</strong>?<br />„{String(p.text)}“</>;
  const yes = a.kind === 'aufgabe' ? 'Ja, anlegen' : 'Ja, speichern';
  const doneText = a.kind === 'aufgabe' ? 'Angelegt – steht in deinen Aufgaben.' : a.kind === 'diagnose' ? 'Gespeichert – steht im Verlauf der Pflanze.' : 'Gespeichert.';
  async function decide(yes: boolean) {
    setBusy(true); setError('');
    try { await (yes ? api.confirmAction(a.id) : api.rejectAction(a.id)); onDecided(); } catch (e) { setError(actionErr(e)); } finally { setBusy(false); }
  }
  return (
    <div className="outline stack" style={{ alignSelf: 'flex-start', maxWidth: '88%', border: `2px solid ${a.status === 'proposed' ? 'var(--green)' : 'var(--line)'}`, gap: 10 }}>
      <span>{what}</span>
      {a.status === 'proposed' ? (
        <div className="grid2" style={{ gap: 8 }}>
          <button className="btn" style={{ background: 'var(--green)', color: 'var(--green-ink)', border: 0, fontWeight: 700 }} disabled={busy} onClick={() => decide(true)}>{yes}</button>
          <button className="btn" disabled={busy} onClick={() => decide(false)}>Nein</button>
        </div>
      ) : <span className="muted">{a.status === 'done' ? doneText : a.kind === 'aufgabe' ? 'Nicht angelegt.' : 'Nicht gespeichert.'}</span>}
      {error && <span className="small" role="alert" style={{ color: 'var(--urgent)' }}>{error}</span>}
    </div>
  );
}

function ChatBar({ onSend, busy, placeholder }: { onSend: (t: string, photoIds: string[]) => Promise<boolean>; busy: boolean; placeholder: string }) {
  const [text, setText] = useState('');
  const [photos, setPhotos] = useState<string[]>([]);
  const [uploading, setUploading] = useState(0);
  const [error, setError] = useState('');
  const picker = useRef<HTMLInputElement>(null);
  const taken = useRef(0);  // photos plus uploads still waiting (state lags behind a second pick)
  async function pick(files: FileList | null) {
    const all = Array.from(files ?? []);
    const chosen = all.slice(0, Math.max(0, MAX_PHOTOS - taken.current));
    if (picker.current) picker.current.value = '';
    setError(all.length > chosen.length ? `Höchstens ${MAX_PHOTOS} Fotos pro Frage.` : '');
    taken.current += chosen.length;
    setUploading((n) => n + chosen.length);
    for (const f of chosen) {
      try { const id = await uploadPhoto(f); setPhotos((p) => [...p, id]); } catch (e) { taken.current -= 1; setError(errText(e)); } finally { setUploading((n) => n - 1); }
    }
  }
  function removePhoto(id: string) { taken.current -= 1; setPhotos((p) => p.filter((x) => x !== id)); }
  async function send() {
    const t = text.trim() || (photos.length ? PHOTO_QUESTION : '');
    if (!t || busy || uploading) return;
    if (await onSend(t, photos)) { setText(''); setPhotos([]); taken.current = 0; }
  }
  return (
    <div className="chatbar" style={{ flexDirection: 'column' }}>
      {(photos.length > 0 || uploading > 0) && (
        <div className="row" style={{ gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
          {photos.map((id, i) => (
            <span key={id} className="row" style={{ gap: 2, alignItems: 'center' }}>
              <img src={photoUrl(id)} alt={`Foto ${i + 1}`} width={64} height={48} style={{ borderRadius: 8, objectFit: 'cover', display: 'block' }} />
              <button className="btn" aria-label={`Foto ${i + 1} entfernen`} onClick={() => removePhoto(id)}
                style={{ width: 44, minHeight: 44, padding: 0, border: 0, background: 'transparent', fontSize: 22 }}>×</button>
            </span>
          ))}
          {uploading > 0 && <Waiting text="Foto wird geladen …" />}
        </div>
      )}
      {error && <span className="small" role="alert" style={{ color: 'var(--urgent)' }}>{error}</span>}
      <div className="row" style={{ gap: 8 }}>
        <input ref={picker} type="file" accept="image/*" multiple hidden onChange={(e) => pick(e.target.files)} />
        <button className="btn" aria-label="Foto aufnehmen oder auswählen" disabled={busy || photos.length + uploading >= MAX_PHOTOS}
          onClick={() => picker.current?.click()} style={{ width: 48, flex: 'none', padding: 0, borderRadius: 24 }}><Icon name="camera" size={20} /></button>
        <label className="sr-only" htmlFor="msg">Frage</label>
        <input id="msg" className="input" style={{ borderRadius: 24, minWidth: 0, flex: 1 }} placeholder={photos.length ? 'Was fällt dir auf? Seit wann?' : placeholder} maxLength={2000} value={text}
          onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') send(); }} />
        <button className="btn" aria-label="Senden" disabled={busy || uploading > 0 || (!text.trim() && !photos.length)} onClick={send} style={{ width: 48, flex: 'none', padding: 0, borderRadius: 24 }}><Icon name="send" size={20} /></button>
      </div>
    </div>
  );
}

export function Chats({ plantId }: { plantId?: string }) {
  const [list, setList] = useState<ChatSummary[] | null>(null);
  const [plant, setPlant] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (!plantId) api.chats().then(setList, (e) => setError(errText(e))); }, [plantId]);
  useEffect(() => {
    if (plantId) api.plant(plantId).then((p) => setPlant(p.nickname || `${p.species.german}${p.cultivar ? ` ‘${p.cultivar.name}’` : ''}`), (e) => setError(errText(e)));
  }, [plantId]);
  async function start(text: string, photoIds: string[] = []) {
    setBusy(true); setError('');
    const extra: Ask = { photo_ids: photoIds, ...(plantId ? { plant_id: plantId } : {}) };
    try { const r = await api.newChat(text, extra); window.location.hash = `#/fragen/${r.chat_id}`; return true; } catch (e) { setError(errText(e)); return false; } finally { setBusy(false); }
  }
  if (plantId) return (
    <div className="page">
      <Back href={`#/pflanze/${plantId}`} label="Pflanze" />
      <header className="stack" style={{ gap: 6 }}>
        <h1 className="title-s">Pflanze krank?</h1>
        <span className="chip" style={{ alignSelf: 'flex-start' }}>Zu: {plant ?? '…'}</span>
        <span className="small muted">Mach 1–3 Fotos – die kranke Stelle nah und einmal die ganze Pflanze – und schreib dazu, was dir auffällt. Standort-Daten (EXIF) werden entfernt, die Bilder verkleinert.</span>
      </header>
      {error && <p className="box" role="alert" style={{ color: 'var(--urgent)' }}>{error}</p>}
      <ChatBar onSend={start} busy={busy} placeholder="Was fällt dir auf?" />
    </div>
  );
  return (
    <div className="page">
      <header className="stack" style={{ gap: 6 }}>
        <h1 className="title-s">Fragen</h1>
        <span className="small muted">Frag nach deinem Garten – die KI kennt deine Pflanzen, Aufgaben, das Wetter und die Jahreszeit. Aufgaben legt sie nur an, wenn du „Ja“ sagst.</span>
      </header>
      {error && <p className="box" role="alert" style={{ color: 'var(--urgent)' }}>{error}</p>}
      {list && list.length === 0 && (
        <div className="stack" style={{ gap: 8 }}>
          {['Was muss diese Woche im Garten passieren?', 'Wann schneide ich meine Hecke?', 'Was mache ich vor dem nächsten Frost?'].map((q) => (
            <button key={q} className="option" disabled={busy} onClick={() => start(q)}><span>{q}</span><Icon name="send" size={18} /></button>
          ))}
        </div>
      )}
      {list?.map((c) => (
        <a key={c.id} href={`#/fragen/${c.id}`} className="card stack" style={{ gap: 2, textDecoration: 'none', color: 'var(--ink)' }}>
          <strong>{c.title}</strong>
          <span className="tiny">{new Date(c.updated_at).toLocaleString('de-DE', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</span>
        </a>
      ))}
      <ChatBar onSend={start} busy={busy} placeholder="Frag deinen Garten …" />
    </div>
  );
}

export function ChatView({ id }: { id: string }) {
  const [chat, setChat] = useState<ChatFull | null>(null);
  const [error, setError] = useState('');
  const [live, setLive] = useState<{ id: string; text: string } | null>(null);
  const [attempt, setAttempt] = useState(0);  // a new stream after a dropped connection (phone asleep, network switch)
  const end = useRef<HTMLDivElement>(null);
  const load = useCallback(() => api.chat(id).then(setChat, (e) => setError(errText(e))), [id]);
  useEffect(() => { load(); }, [load]);

  const pending = chat?.messages.find((m) => m.role === 'assistant' && (m.status === 'queued' || m.status === 'running'));
  useEffect(() => {   // stream the answer that is being written; reconnect with back-off, the DB text is the truth
    if (!pending) return;
    let retry = 0;
    const src = new EventSource(`/api/chats/${encodeURIComponent(id)}/stream?message_id=${encodeURIComponent(pending.id)}`);
    src.addEventListener('text', (e) => setLive({ id: pending.id, text: JSON.parse((e as MessageEvent).data).text }));
    src.addEventListener('done', (e) => {
      src.close(); setLive(null); load();
      const status = JSON.parse((e as MessageEvent).data).status;
      if (status !== 'done' && status !== 'failed') retry = window.setTimeout(() => setAttempt((n) => n + 1), 3000);
    });
    src.onerror = () => {
      src.close(); setLive(null); load();
      retry = window.setTimeout(() => setAttempt((n) => n + 1), Math.min(30000, 2000 * 2 ** Math.min(attempt, 4)));
    };
    const onVisible = () => { if (document.visibilityState === 'visible') { load(); setAttempt((n) => n + 1); } };
    document.addEventListener('visibilitychange', onVisible);
    return () => { src.close(); window.clearTimeout(retry); document.removeEventListener('visibilitychange', onVisible); };
  }, [id, pending?.id, attempt, load]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }); }, [chat, live]);

  async function send(text: string, photoIds: string[]) {
    setError('');
    try { await api.ask(id, text, { photo_ids: photoIds }); await load(); return true; } catch (e) { setError(errText(e)); return false; }
  }
  async function remove() {
    if (!window.confirm('Diesen Chat löschen?')) return;
    try { await api.deleteChat(id); window.location.hash = '#/fragen'; } catch (e) { setError(errText(e)); }
  }
  return (
    <div className="page">
      <div className="between"><Back href="#/fragen" label="Fragen" /><button className="btn small" style={{ minHeight: 44 }} disabled={!!pending} onClick={remove}>Löschen</button></div>
      {chat && <h1 className="title-s" style={{ fontSize: 20 }}>{chat.title}</h1>}
      {chat?.plant && <a className="chip" href={`#/pflanze/${chat.plant.id}`} style={{ alignSelf: 'flex-start', minHeight: 44, display: 'inline-flex', alignItems: 'center' }}>Zu: {chat.plant.name}</a>}
      {!chat && !error && <p className="muted"><Waiting /></p>}
      {chat?.messages.map((m) => m.role === 'user' ? (
        <div key={m.id} className="bubble-me stack" style={{ whiteSpace: 'pre-wrap', gap: 8 }}>{m.photos.length > 0 && <PhotoThumbs ids={m.photos} />}<span>{m.text}</span></div>
      ) : (
        <div key={m.id} className="stack" style={{ gap: 8 }}>
          <div className="bubble-ai" aria-live={m.id === pending?.id ? 'polite' : undefined}>
            {(live?.id === m.id ? live.text : m.text) ? <Rich text={live?.id === m.id ? live.text : m.text} /> : <span className="muted">{m.status === 'failed' ? '' : <Waiting text="Schaut im Garten nach …" />}</span>}
            {m.status === 'failed' && <span className="small" role="alert" style={{ color: 'var(--urgent)' }}>{m.error ?? 'Die Antwort ist abgebrochen.'}</span>}
          </div>
          {m.actions.map((a) => <ActionCard key={a.id} a={a} onDecided={load} />)}
        </div>
      ))}
      {error && <p className="box" role="alert" style={{ color: 'var(--urgent)' }}>{error}</p>}
      <div ref={end} />
      <ChatBar onSend={send} busy={!!pending} placeholder={pending ? 'Antwort wird geschrieben …' : 'Weiter fragen …'} />
    </div>
  );
}
