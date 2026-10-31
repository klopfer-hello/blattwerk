// Plant doctor (M9): photos are shrunk in the browser before upload (max 1600 px, JPEG 0.85).
// Drawing into a canvas drops all metadata (EXIF, GPS); the server re-encodes again anyway.
// HEIC from iPhones is decoded by the phone's own image decoder.
import { ApiError } from './api';

const MAX_SIDE = 1600;

async function decode(file: File): Promise<{ img: CanvasImageSource; w: number; h: number }> {
  try {
    const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' });
    return { img: bmp, w: bmp.width, h: bmp.height };
  } catch {  // older Safari: through an <img> (data URL: the CSP allows no blob: images)
    const url = await new Promise<string>((ok, bad) => {
      const r = new FileReader();
      r.onload = () => ok(String(r.result));
      r.onerror = () => bad(r.error);
      r.readAsDataURL(file);
    });
    const el = new Image();
    el.src = url;
    await el.decode();
    return { img: el, w: el.naturalWidth, h: el.naturalHeight };
  }
}

export async function shrink(file: File): Promise<Blob> {
  const { img, w, h } = await decode(file);
  const scale = Math.min(1, MAX_SIDE / Math.max(w, h));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(w * scale);
  canvas.height = Math.round(h * scale);
  canvas.getContext('2d')!.drawImage(img, 0, 0, canvas.width, canvas.height);
  return new Promise((ok, bad) => canvas.toBlob((b) => (b ? ok(b) : bad(new Error('encode'))), 'image/jpeg', 0.85));
}

export async function uploadPhoto(file: File): Promise<string> {
  let body: Blob;
  try { body = await shrink(file); } catch { throw new ApiError(422, 'Das Foto lässt sich nicht lesen.'); }
  let res: Response;
  try {
    res = await fetch('/api/photos', { method: 'POST', headers: { 'Content-Type': 'image/jpeg' }, body });
  } catch {
    throw new ApiError(0, 'Server nicht erreichbar. Bist du im Heimnetz?');
  }
  if (!res.ok) {
    const why = res.status === 413 ? 'Das Foto ist zu groß.' : res.status === 429 ? 'Zu viele unverschickte Fotos – bitte morgen wieder.' : 'Das Foto lässt sich nicht hochladen.';
    throw new ApiError(res.status, why);
  }
  return (await res.json()).id as string;
}

export const photoUrl = (id: string) => `/api/photos/${encodeURIComponent(id)}`;
