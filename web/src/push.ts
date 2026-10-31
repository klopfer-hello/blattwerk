// Web push on this device (M3b): state detection, subscribe / unsubscribe, test.
// iPhone/iPad only support push for apps added to the home screen (iOS 16.4+).
import { api } from './api';

export type PushState = 'unsupported' | 'ios-install' | 'denied' | 'off' | 'on' | 'no-key';

// iPadOS reports a Mac user agent; a Mac with a touch screen is an iPad.
const isIos = () => /iPad|iPhone|iPod/.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);
const standalone = () => window.matchMedia('(display-mode: standalone)').matches || (navigator as unknown as { standalone?: boolean }).standalone === true;

export function registerServiceWorker(): void {
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => undefined);
}

async function registration(): Promise<ServiceWorkerRegistration | null> {
  if (!('serviceWorker' in navigator)) return null;
  return navigator.serviceWorker.ready;
}

export async function pushState(): Promise<PushState> {
  if (isIos() && !standalone()) return 'ios-install';
  if (!('PushManager' in window) || !('Notification' in window) || !('serviceWorker' in navigator)) return 'unsupported';
  if (Notification.permission === 'denied') return 'denied';
  const reg = await registration();
  return (await reg?.pushManager.getSubscription()) ? 'on' : 'off';
}

function keyBytes(b64url: string): Uint8Array {
  const b64 = (b64url + '='.repeat((4 - (b64url.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/');
  return Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0));
}

function deviceLabel(): string {
  if (isIos()) return 'iPhone/iPad';
  if (/Android/.test(navigator.userAgent)) return 'Android';
  return 'Browser';
}

/** Fetch this once when the screen opens: on iOS the permission request must come
 *  straight from the tap, with no network wait in between. */
export const pushKey = async (): Promise<string | null> => (await api.pushKey()).public_key;

export async function enablePush(key: string | null): Promise<PushState> {
  const permission = Notification.requestPermission();  // first, inside the user gesture
  if (!key) return 'no-key';
  if ((await permission) !== 'granted') return 'denied';
  const reg = await registration();
  if (!reg) return 'unsupported';
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) });
  const json = sub.toJSON();
  await api.pushSubscribe({ endpoint: sub.endpoint, keys: { p256dh: json.keys?.p256dh ?? '', auth: json.keys?.auth ?? '' }, label: deviceLabel() });
  return 'on';
}

export async function disablePush(): Promise<PushState> {
  const sub = await (await registration())?.pushManager.getSubscription();
  if (sub) {
    await api.pushUnsubscribe(sub.endpoint).catch(() => undefined);
    await sub.unsubscribe();
  }
  return 'off';
}

export async function testPush(): Promise<void> {
  const sub = await (await registration())?.pushManager.getSubscription();
  if (sub) await api.pushTest(sub.endpoint);
}
