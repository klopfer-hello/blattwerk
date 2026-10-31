// Preview of the plant doctor (M9) for approval: static example data, nothing is sent or
// stored. Shows the three new pieces: the entry on the plant, photos in the chat with a
// diagnosis card, and the diagnosis in the plant's history.
import { Back, Icon, TaskChip } from '../components/ui';

const LEAF = 'data:image/svg+xml;utf8,' + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 90"><rect width="120" height="90" fill="#cfe3c4"/>'
  + '<path d="M20 70 C35 15 95 10 105 25 C95 70 50 85 20 70Z" fill="#4f8a3b"/>'
  + '<circle cx="62" cy="45" r="6" fill="#e9e7d8"/><circle cx="78" cy="38" r="4" fill="#e9e7d8"/>'
  + '<circle cx="50" cy="56" r="5" fill="#e9e7d8"/><path d="M22 70 L100 26" stroke="#2f5a24" stroke-width="2"/></svg>',
);

function Section({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <section className="stack" style={{ gap: 10, borderTop: '1px solid var(--line)', paddingTop: 14 }}>
      <span className="eyebrow">{n}. {title}</span>
      {children}
    </section>
  );
}

export function DoctorPreview() {
  return (
    <div className="page">
      <Back href="#/mehr" label="Mehr" />
      <span className="chip" style={{ background: 'var(--legal-tint)', color: 'var(--legal-ink)' }}>Vorschau Pflanzendoktor (M9) – Beispieldaten, nichts wird gesendet</span>
      <h1 className="title-s">Pflanze krank?</h1>
      <span className="small muted">So würde es aussehen. Bitte sag, was passt und was anders sein soll.</span>

      <Section n={1} title="Auf der Seite der Pflanze">
        <div className="stack" style={{ gap: 4 }}>
          <strong style={{ fontSize: 22 }}>Apfel ‘Topaz’</strong>
          <span className="muted" style={{ fontStyle: 'italic' }}>Malus domestica ‘Topaz’</span>
        </div>
        <div className="grid2">
          <button className="btn">Bearbeiten</button>
          <button className="btn">Archivieren</button>
        </div>
        <button className="btn" style={{ borderColor: 'var(--urgent)', color: 'var(--urgent)', fontWeight: 700 }}>
          <Icon name="camera" size={20} />Pflanze krank? Foto zeigen
        </button>
        <span className="tiny">Öffnet „Fragen“ mit dieser Pflanze und der Kamera.</span>
      </Section>

      <Section n={2} title="Im Chat: Fotos und Diagnose">
        <div className="bubble-me stack" style={{ gap: 8 }}>
          <div className="row" style={{ gap: 6 }}>
            <img src={LEAF} alt="Beispielfoto Blatt" width={96} height={72} style={{ borderRadius: 10, objectFit: 'cover' }} />
            <img src={LEAF} alt="Beispielfoto Blatt, näher" width={96} height={72} style={{ borderRadius: 10, objectFit: 'cover', transform: 'scaleX(-1)' }} />
          </div>
          <span>Weiße Flecken auf den Blättern, seit ungefähr einer Woche.</span>
          <span className="tiny" style={{ color: 'inherit', opacity: 0.85 }}>Zu: Apfel ‘Topaz’</span>
        </div>
        <div className="bubble-ai">
          <span>Das sieht nach <strong>Echtem Mehltau</strong> aus: mehlig-weißer Belag, der sich abwischen lässt, vor allem an jungen Blättern. ‘Topaz’ ist dafür eher wenig anfällig – die feuchte Woche und der halbschattige Platz begünstigen ihn aber.</span>
          <span>• Befallene Triebspitzen jetzt herausschneiden und in den Restmüll.</span>
          <span>• In einer Woche nachsehen, ob neue Flecken kommen.</span>
        </div>
        <div className="outline stack" style={{ alignSelf: 'flex-start', maxWidth: '92%', border: '2px solid var(--green)', gap: 8 }}>
          <span className="eyebrow">Diagnose speichern?</span>
          <strong style={{ fontSize: 18 }}>Echter Mehltau</strong>
          <span className="small">Sicherheit: <strong>ziemlich sicher</strong> · Ursache: feuchte Witterung, wenig Luft</span>
          <span className="small muted">Kommt in den Verlauf der Pflanze – mit den Fotos.</span>
          <div className="grid2" style={{ gap: 8 }}>
            <button className="btn" style={{ background: 'var(--green)', color: 'var(--green-ink)', border: 0, fontWeight: 700 }}>Ja, speichern</button>
            <button className="btn">Nein</button>
          </div>
        </div>
        <div className="outline stack" style={{ alignSelf: 'flex-start', maxWidth: '92%', border: '2px solid var(--green)', gap: 8 }}>
          <span>Aufgabe anlegen?<br /><strong>„Mehltau-Triebe herausschneiden“</strong> heute</span>
          <span className="small muted">Pflanzenschutz · Apfel ‘Topaz’</span>
          <div className="grid2" style={{ gap: 8 }}>
            <button className="btn" style={{ background: 'var(--green)', color: 'var(--green-ink)', border: 0, fontWeight: 700 }}>Ja, anlegen</button>
            <button className="btn">Nein</button>
          </div>
        </div>
        <div className="bubble-ai">
          <span>Wenn sie unsicher ist, fragt die KI nach: <em>„Kannst du die Blattunterseite fotografieren?“</em> – und schlägt dann keine Diagnose vor.</span>
        </div>
        <div className="chatbar" style={{ position: 'static' }}>
          <button className="btn" aria-label="Foto aufnehmen oder auswählen" style={{ width: 48, padding: 0, borderRadius: 24 }}><Icon name="camera" size={20} /></button>
          <input className="input" style={{ borderRadius: 24 }} placeholder="Was fällt dir auf?" disabled />
          <button className="btn" aria-label="Senden" disabled style={{ width: 48, padding: 0, borderRadius: 24 }}><Icon name="send" size={20} /></button>
        </div>
        <span className="tiny">1–3 Fotos pro Frage. Standort-Daten (EXIF) werden vor dem Senden entfernt, die Bilder verkleinert.</span>
      </Section>

      <Section n={3} title="Im Verlauf der Pflanze">
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={false}>Aufgaben</button>
          <button role="tab" aria-selected={false}>Schädlinge</button>
          <button role="tab" aria-selected>Verlauf</button>
        </div>
        <div className="planrow" style={{ gridTemplateColumns: '72px minmax(0, 1fr)' }}>
          <span className="small muted">31.10.</span>
          <span className="stack" style={{ gap: 4 }}>
            <TaskChip category="pflanzenschutz" />
            <strong>Diagnose: Echter Mehltau</strong>
            <span className="small muted">ziemlich sicher · feuchte Witterung, wenig Luft</span>
            <img src={LEAF} alt="Foto der Diagnose" width={80} height={60} style={{ borderRadius: 8 }} />
          </span>
        </div>
        <div className="planrow" style={{ gridTemplateColumns: '72px minmax(0, 1fr)' }}>
          <span className="small muted">31.10.</span>
          <span className="stack" style={{ gap: 2 }}><strong>✓ Mehltau-Triebe herausschneiden</strong><span className="small muted">„Drei Triebe, Rest sieht gut aus.“</span></span>
        </div>
        <div className="planrow" style={{ gridTemplateColumns: '72px minmax(0, 1fr)' }}>
          <span className="small muted">12.10.</span>
          <span className="stack" style={{ gap: 2 }}><strong>✓ Leimringe anbringen</strong></span>
        </div>
        <span className="tiny">Der Verlauf zeigt Erledigtes und Diagnosen; die KI sieht ihn bei späteren Fragen zur Pflanze.</span>
      </Section>
    </div>
  );
}
