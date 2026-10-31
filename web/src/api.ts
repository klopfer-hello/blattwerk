// Typed client for the garten-planer API (same origin, /api/...). Errors come
// back as ApiError with the HTTP status and, for 422, the invalid fields.

export const BUNDESLAENDER = [
  'Baden-Württemberg', 'Bayern', 'Berlin', 'Brandenburg', 'Bremen', 'Hamburg', 'Hessen', 'Mecklenburg-Vorpommern',
  'Niedersachsen', 'Nordrhein-Westfalen', 'Rheinland-Pfalz', 'Saarland', 'Sachsen', 'Sachsen-Anhalt',
  'Schleswig-Holstein', 'Thüringen',
] as const;

export type Fertiliser = 'gemischt' | 'organisch' | 'mineralisch';
export interface GardenSettings {
  location: { ort: string | null; plz: string | null; bundesland: (typeof BUNDESLAENDER)[number] | null };
  preferences: { fertiliser: Fertiliser; eco_defaults: boolean };
  legal: { baumschutz_girth_cm: number | null; fruit_trees_exempt: boolean };
  notifications: { weather_push: boolean; digest_mode: 'daily' | 'weekly' | 'off'; digest_time: string; digest_weekday: number };
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public fields: Record<string, string> = {}) {
    super(message);
  }
}

// The API answers in English (for logs and tools); the UI shows German.
const GERMAN: Record<number, string> = {
  400: 'Ungültige Anfrage.', 403: 'Nicht erlaubt.', 404: 'Nicht gefunden – vielleicht inzwischen gelöscht?',
  409: 'Gibt es schon oder wird noch verwendet.', 413: 'Zu viele Daten auf einmal.', 415: 'Ungültiges Format.',
  422: 'Bitte die Eingaben prüfen.', 502: 'Server startet gerade neu. Bitte gleich nochmal versuchen.',
  503: 'Datenbank gerade nicht erreichbar. Bitte gleich nochmal versuchen.',
};

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, 'Server nicht erreichbar. Bist du im Heimnetz?');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, GERMAN[res.status] ?? `Fehler ${res.status} – bitte nochmal versuchen.`, data.fields ?? {});
  return data as T;
}

export type Light = 'sonnig' | 'halbschattig' | 'schattig';
export const STANDORT_TYPES = {
  beet: 'Beet', gemuesebeet: 'Gemüsebeet', rasen: 'Rasen', hecke: 'Hecke', kuebelplatz: 'Kübelplatz',
  gewaechshaus: 'Gewächshaus', sonstiges: 'Sonstiges',
} as const;
export type StandortType = keyof typeof STANDORT_TYPES;
export interface StandortIn { name: string; light: Light; type: StandortType; notes: string }
export interface Standort extends StandortIn { id: string; plant_count: number }

export const FORMS = ['Säule', 'Halbstamm', 'Hochstamm', 'Busch', 'Spindel', 'Spalier', 'Strauch', 'Hecke', 'Solitär', 'Kübel', 'Kletterer', 'Horst', 'Knolle'] as const;
export type Form = (typeof FORMS)[number];
export interface PlantIn {
  species_id: string; cultivar_id: string | null; standort_id: string; nickname: string | null; form: Form | null;
  rootstock: string | null; planted_year: number | null; girth_cm: number | null; in_container: boolean; notes: string;
}
export interface Plant extends Omit<PlantIn, 'species_id' | 'cultivar_id' | 'standort_id'> {
  id: string;
  species: { id: string; latin: string; german: string; growth: string; woody: boolean };
  cultivar: { id: string; name: string } | null;
  standort: { id: string; name: string; light: Light | null };  // null: Standort deleted meanwhile
  archived: boolean;
}
export interface Candidate {
  species_id: string; latin: string; german: string; cultivar_id: string | null; cultivar_name: string | null;
  unmatched: string; form_hint: Form | null; score: number;
}
export interface Species { id: string; latin: string; german: string[]; growth: string; woody: boolean; cultivars: { id: string; name: string }[] }

export const CATEGORIES = {
  schnitt: 'Schnitt', duengen: 'Düngen', ernte: 'Ernte', pflanzenschutz: 'Pflanzenschutz',
  winterschutz: 'Winterschutz', aussaat: 'Aussaat', sonstiges: 'Sonstiges',
} as const;
export type Category = keyof typeof CATEGORIES;
export type Recurrence = 'once' | 'yearly' | 'interval';
export type CutType = 'pflege' | 'stark';
export interface LegalNote { code: string; severity: 'info' | 'warn'; text: string; ref: string }
export interface TaskIn {
  plant_id: string | null; title: string; category: Category; cut_type: CutType | null; instructions: string; recurrence: Recurrence;
  due_date: string | null; month_from: number | null; month_to: number | null; interval_days: number | null;
  start_date: string | null; urgent: boolean;
}
export interface Task extends TaskIn { id: string; plant: { id: string; title: string } | null; source: string; enabled: boolean; notes: LegalNote[] }
export interface Todo {
  id: string; status: 'open' | 'done' | 'skipped'; due_from: string; due_to: string; overdue: boolean; postponed: boolean;
  note: string; done_at: string | null; legal_adjustment: string | null; notes: LegalNote[];
  blocked_until: string | null;  // strong cut not allowed today (§ 39): first allowed day
  task: { id: string; title: string; category: Category; urgent: boolean; instructions: string; recurrence: Recurrence };
  plant: { id: string; title: string } | null;
}
export interface Heute { year: number; month: number; open: Todo[]; done: Todo[] }
export interface CalendarEntry { task_id: string; title: string; category: Category; urgent: boolean; moved: boolean; plant: { id: string; title: string } | null }

const enc = encodeURIComponent;

export const api = {
  settings: () => request<GardenSettings>('GET', '/settings'),
  saveSettings: (s: GardenSettings) => request<GardenSettings>('PUT', '/settings', s),
  standorte: () => request<Standort[]>('GET', '/standorte'),
  createStandort: (s: StandortIn) => request<Standort>('POST', '/standorte', s),
  updateStandort: (id: string, s: StandortIn) => request<Standort>('PUT', `/standorte/${enc(id)}`, s),
  deleteStandort: (id: string) => request<unknown>('DELETE', `/standorte/${enc(id)}`),
  resolve: (q: string) => request<{ candidates: Candidate[] }>('GET', `/species/resolve?q=${enc(q)}`),
  species: (id: string) => request<Species>('GET', `/species/${enc(id)}`),
  createCultivar: (speciesId: string, name: string) => request<{ id: string; name: string }>('POST', `/species/${enc(speciesId)}/cultivars`, { name }),
  plants: (archived = false) => request<Plant[]>('GET', `/plants${archived ? '?archived=true' : ''}`),
  plant: (id: string) => request<Plant>('GET', `/plants/${enc(id)}`),
  createPlant: (p: PlantIn) => request<Plant>('POST', '/plants', p),
  updatePlant: (id: string, p: PlantIn) => request<Plant>('PUT', `/plants/${enc(id)}`, p),
  archivePlant: (id: string) => request<Plant>('POST', `/plants/${enc(id)}/archive`),
  restorePlant: (id: string) => request<Plant>('POST', `/plants/${enc(id)}/restore`),
  tasks: (plantId?: string) => request<Task[]>('GET', `/tasks${plantId ? `?plant_id=${enc(plantId)}` : ''}`),
  task: (id: string) => request<Task>('GET', `/tasks/${enc(id)}`),
  createTask: (t: TaskIn) => request<Task>('POST', '/tasks', t),
  updateTask: (id: string, t: TaskIn) => request<Task>('PUT', `/tasks/${enc(id)}`, t),
  setTaskEnabled: (id: string, on: boolean) => request<Task>('POST', `/tasks/${enc(id)}/${on ? 'enable' : 'disable'}`),
  heute: () => request<Heute>('GET', '/todos/heute'),
  todo: (id: string) => request<Todo>('GET', `/todos/${enc(id)}`),
  done: (id: string, note?: string) => request<Todo>('POST', `/todos/${enc(id)}/done`, note === undefined ? {} : { note }),
  skip: (id: string, note?: string) => request<Todo>('POST', `/todos/${enc(id)}/skip`, note === undefined ? {} : { note }),
  undo: (id: string) => request<Todo>('POST', `/todos/${enc(id)}/undo`),
  postpone: (id: string, to: string) => request<Todo>('POST', `/todos/${enc(id)}/postpone`, { to }),
  pushKey: () => request<{ public_key: string | null }>('GET', '/push/key'),
  pushSubscribe: (s: { endpoint: string; keys: { p256dh: string; auth: string }; label: string }) => request<{ id: string }>('POST', '/push/subscriptions', s),
  pushUnsubscribe: (endpoint: string) => request<unknown>('POST', '/push/unsubscribe', { endpoint }),
  pushTest: (endpoint: string) => request<unknown>('POST', '/push/test', { endpoint }),
  legalPreview: (t: TaskIn) => request<{ notes: LegalNote[]; next: { due_from: string; due_to: string; reason: string } | null }>('POST', '/legal/preview', t),
  calendar: (year: number) => request<{ year: number; months: CalendarEntry[][] }>('GET', `/calendar?year=${year}`),
};
