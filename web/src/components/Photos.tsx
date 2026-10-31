// Photo thumbnails with an in-app large view (plant doctor, M9). No new window: in the
// installed app a new window has no way back. The large view closes with ✕, a tap, Escape
// or the phone's back button (one history entry while it is open).
import { useCallback, useEffect, useState } from 'react';
import { photoUrl } from '../photos';

function Lightbox({ id, label, onClose }: { id: string; label: string; onClose: () => void }) {
  useEffect(() => {
    history.pushState({ photo: id }, '');
    const onPop = () => onClose();
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') history.back(); };
    window.addEventListener('popstate', onPop);
    window.addEventListener('keydown', onKey);
    return () => { window.removeEventListener('popstate', onPop); window.removeEventListener('keydown', onKey); };
  }, [id, onClose]);
  return (
    <div role="dialog" aria-modal="true" aria-label={label} onClick={() => history.back()}
      style={{ position: 'fixed', inset: 0, zIndex: 100, background: 'rgba(0, 0, 0, 0.92)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 'env(safe-area-inset-top) 0 env(safe-area-inset-bottom)' }}>
      <img src={photoUrl(id)} alt={label} style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }} />
      <button className="btn" aria-label="Schließen" autoFocus onClick={(e) => { e.stopPropagation(); history.back(); }}
        style={{ position: 'absolute', top: 'calc(12px + env(safe-area-inset-top))', right: 12, width: 48, minHeight: 48, padding: 0, borderRadius: 24, fontSize: 24, background: 'rgba(255, 255, 255, 0.9)', color: '#111', border: 0 }}>✕</button>
    </div>
  );
}

export function PhotoThumbs({ ids, width = 96, label = 'Foto' }: { ids: string[]; width?: number; label?: string }) {
  const [open, setOpen] = useState<number | null>(null);
  const close = useCallback(() => setOpen(null), []);  // stable: the history entry is pushed once
  return (
    <span className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
      {ids.map((id, i) => (
        <button key={id} type="button" aria-label={`${label} ${i + 1} groß ansehen`} onClick={() => setOpen(i)}
          style={{ padding: 0, border: 0, background: 'none', borderRadius: 10, cursor: 'zoom-in', minHeight: 44 }}>
          <img src={photoUrl(id)} alt={`${label} ${i + 1}`} width={width} height={Math.round(width * 0.75)} style={{ borderRadius: 10, objectFit: 'cover', display: 'block' }} />
        </button>
      ))}
      {open !== null && <Lightbox id={ids[open]} label={`${label} ${open + 1}`} onClose={close} />}
    </span>
  );
}
