// Fragen (M8): the garden chat. A list of chats, and a chat whose answer streams in
// (server-sent events from the api while the worker writes it). Claude only proposes
// to-dos and notes; they become real with "Ja" here.
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { ApiError, api, type ChatAction, type ChatFull, type ChatSummary } from '../api';
import { Back, Icon, deDate, Waiting } from '../components/ui';

const ASK_ERR: Record<number, string> = {
  409: 'Die vorige Antwort wird noch geschrieben.',
  429: 'Für heute sind genug Fragen gestellt. Morgen geht es weiter.',
};
const ACTION_ERR: Record<string, string> = {
  'already decided': 'Schon entschieden.', 'proposal expired': 'Der Vorschlag ist älter als eine Woche – bitte neu fragen.',
  'plant archived or deleted': 'Die Pflanze gibt es nicht mehr.', 'plant notes are full': 'Die Notizen der Pflanze sind voll.',
};
const errText = (e: unknown) => (e instanceof ApiError ? ASK_ERR[e.status] ?? e.message : 'Server nicht erreichbar.');
const actionErr = (e: unknown) => (e instanceof ApiError ? ACTION_ERR[e.message] ?? (e.status === 409 ? 'Das geht so nicht mehr (Datum vorbei?).' : e.message) : 'Server nicht erreichbar.');
const CATEGORY_DE: Record<string, string> = { schnitt: 'Schnitt', duengen: 'Düngen', ernte: 'Ernte', pflanzenschutz: 'Pflanzenschutz', winterschutz: 'Winterschutz', aussaat: 'Aussaat', sonstiges: 'Sonstiges' };

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
  ) : <>Notiz speichern bei <strong>{a.plant ?? 'unbekannter Pflanze'}</strong>?<br />„{String(p.text)}“</>;
  async function decide(yes: boolean) {
    setBusy(true); setError('');
    try { await (yes ? api.confirmAction(a.id) : api.rejectAction(a.id)); onDecided(); } catch (e) { setError(actionErr(e)); } finally { setBusy(false); }
  }
  return (
    <div className="outline stack" style={{ alignSelf: 'flex-start', maxWidth: '88%', border: `2px solid ${a.status === 'proposed' ? 'var(--green)' : 'var(--line)'}`, gap: 10 }}>
      <span>{what}</span>
      {a.status === 'proposed' ? (
        <div className="grid2" style={{ gap: 8 }}>
          <button className="btn" style={{ background: 'var(--green)', color: 'var(--green-ink)', border: 0, fontWeight: 700 }} disabled={busy} onClick={() => decide(true)}>Ja, anlegen</button>
          <button className="btn" disabled={busy} onClick={() => decide(false)}>Nein</button>
        </div>
      ) : <span className="muted">{a.status === 'done' ? (a.kind === 'aufgabe' ? 'Angelegt – steht in deinen Aufgaben.' : 'Gespeichert.') : 'Nicht angelegt.'}</span>}
      {error && <span className="small" role="alert" style={{ color: 'var(--urgent)' }}>{error}</span>}
    </div>
  );
}

function ChatBar({ onSend, busy, placeholder }: { onSend: (t: string) => Promise<boolean>; busy: boolean; placeholder: string }) {
  const [text, setText] = useState('');
  async function send() {
    const t = text.trim();
    if (!t || busy) return;
    if (await onSend(t)) setText('');
  }
  return (
    <div className="chatbar">
      <label className="sr-only" htmlFor="msg">Frage</label>
      <input id="msg" className="input" style={{ borderRadius: 24 }} placeholder={placeholder} maxLength={2000} value={text}
        onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') send(); }} />
      <button className="btn" aria-label="Senden" disabled={busy || !text.trim()} onClick={send} style={{ width: 48, padding: 0, borderRadius: 24 }}><Icon name="send" size={20} /></button>
    </div>
  );
}

export function Chats() {
  const [list, setList] = useState<ChatSummary[] | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.chats().then(setList, (e) => setError(errText(e))); }, []);
  async function start(text: string) {
    setBusy(true); setError('');
    try { const r = await api.newChat(text); window.location.hash = `#/fragen/${r.chat_id}`; return true; } catch (e) { setError(errText(e)); return false; } finally { setBusy(false); }
  }
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

  async function send(text: string) {
    setError('');
    try { await api.ask(id, text); await load(); return true; } catch (e) { setError(errText(e)); return false; }
  }
  async function remove() {
    if (!window.confirm('Diesen Chat löschen?')) return;
    try { await api.deleteChat(id); window.location.hash = '#/fragen'; } catch (e) { setError(errText(e)); }
  }
  return (
    <div className="page">
      <div className="between"><Back href="#/fragen" label="Fragen" /><button className="btn small" style={{ minHeight: 44 }} disabled={!!pending} onClick={remove}>Löschen</button></div>
      {chat && <h1 className="title-s" style={{ fontSize: 20 }}>{chat.title}</h1>}
      {!chat && !error && <p className="muted"><Waiting /></p>}
      {chat?.messages.map((m) => m.role === 'user' ? <div key={m.id} className="bubble-me" style={{ whiteSpace: 'pre-wrap' }}>{m.text}</div> : (
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
