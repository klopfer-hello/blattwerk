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
  gewaechshaus: 'Gewächshaus', sonstiges: 'Sonstiges', zimmer: 'Zimmer',
} as const;
export type StandortType = keyof typeof STANDORT_TYPES;
export const INDOOR_TYPE = 'zimmer';  // the one indoor type (M11): watering yes, weather rules no
export const WINDOWS = { N: 'N', O: 'O', S: 'S', W: 'W', keins: 'keins' } as const;
export const DISTANCES = { fensterbank: 'Fensterbank', bis_1m: 'bis 1 m', '1_2m': '1–2 m', raum: 'Raummitte' } as const;
export const POT_MATERIALS = { kunststoff: 'Kunststoff', ton: 'Ton', keramik: 'Keramik', glas: 'Glas' } as const;
export type Direction = 'N' | 'O' | 'S' | 'W';
export const DIRECTIONS: Record<Direction, string> = { N: 'Nord', O: 'Ost', S: 'Süd', W: 'West' };
export interface StandortIn { name: string; light: Light | null; type: StandortType; windows?: Direction[]; notes: string }  // light: outdoors only, windows: rooms only
export interface Standort extends StandortIn { id: string; plant_count: number }

export const FORMS = ['Säule', 'Halbstamm', 'Hochstamm', 'Busch', 'Spindel', 'Spalier', 'Strauch', 'Hecke', 'Solitär', 'Kübel', 'Kletterer', 'Horst', 'Knolle'] as const;
export type Form = (typeof FORMS)[number];
export interface PlantIn {
  species_id: string; cultivar_id: string | null; standort_id: string; nickname: string | null; form: Form | null;
  rootstock: string | null; planted_year: number | null; girth_cm: number | null; in_container: boolean; notes: string;
  window_dir?: keyof typeof WINDOWS | null; window_distance?: keyof typeof DISTANCES | null;  // indoor only (M11)
  pot_cm?: number | null; pot_material?: keyof typeof POT_MATERIALS | null; height_cm?: number | null;
}
export interface Plant extends Omit<PlantIn, 'species_id' | 'cultivar_id' | 'standort_id'> {
  id: string;
  species: { id: string; latin: string; german: string; growth: string; woody: boolean };
  cultivar: { id: string; name: string } | null;
  standort: { id: string; name: string; light: Light | null; type?: StandortType | null; indoor?: boolean; windows?: Direction[] };  // light null: Standort deleted
  archived: boolean;
}
export interface Candidate {
  species_id: string; latin: string; german: string; cultivar_id: string | null; cultivar_name: string | null;
  unmatched: string; form_hint: Form | null; score: number;
}
export interface Species { id: string; latin: string; german: string[]; growth: string; woody: boolean; hardiness_c: number | null; source: 'seed' | 'user'; cultivars: { id: string; name: string }[] }
export const GROWTH = { baum: 'Baum', strauch: 'Strauch', hecke: 'Hecke', kletterpflanze: 'Kletterpflanze', kuebel: 'Kübelpflanze', staude: 'Staude', gras: 'Gras', knolle: 'Knolle', gemuese: 'Gemüse', kraut: 'Kraut', einjaehrig: 'Einjährig' } as const;

export const CATEGORIES = {
  schnitt: 'Schnitt', duengen: 'Düngen', ernte: 'Ernte', pflanzenschutz: 'Pflanzenschutz',
  winterschutz: 'Winterschutz', aussaat: 'Aussaat', sonstiges: 'Sonstiges',
  giessen: 'Gießen', bespruehen: 'Besprühen', entstauben: 'Entstauben',
} as const;
export const INDOOR_CATEGORIES: readonly Category[] = ['giessen', 'bespruehen', 'entstauben'];  // indoor plants only
export type Category = keyof typeof CATEGORIES;
export type Recurrence = 'once' | 'yearly' | 'interval';
export type CutType = 'pflege' | 'stark';
export interface LegalNote { code: string; severity: 'info' | 'warn'; text: string; ref: string }
export interface TaskIn {
  plant_id: string | null; title: string; category: Category; cut_type: CutType | null; instructions: string; recurrence: Recurrence;
  due_date: string | null; month_from: number | null; month_to: number | null; interval_days: number | null;
  winter_interval_days?: number | null;  // Nov–Feb (interval only, M11)
  amount_ml?: number | null;  // watering: how much each time
  start_date: string | null; urgent: boolean;
  pheno_phase?: PhaseKey | null; pheno_offset?: number; pheno_window?: number;  // follow the season (yearly only)
}
// The phenological clock (DWD): a season starts when its indicator plant gets there.
export const PHASES = [
  ['vorfruehling', 'Vorfrühling', 'Haselblüte'], ['erstfruehling', 'Erstfrühling', 'Forsythienblüte'],
  ['vollfruehling', 'Vollfrühling', 'Apfelblüte'], ['fruehsommer', 'Frühsommer', 'Holunderblüte'],
  ['hochsommer', 'Hochsommer', 'Lindenblüte'], ['spaetsommer', 'Spätsommer', 'Frühapfel-Reife'],
  ['fruehherbst', 'Frühherbst', 'Holunderbeeren-Reife'], ['vollherbst', 'Vollherbst', 'Eichel-Reife'],
  ['spaetherbst', 'Spätherbst', 'Laubfärbung'], ['winter', 'Winter', 'Laubfall'],
] as const;
export type PhaseKey = (typeof PHASES)[number][0];
export interface Product { name: string; kind: string; npk: string | null; dose: string; brands: string[] }
export interface Task extends TaskIn {
  id: string; plant: { id: string; title: string } | null; source: string; enabled: boolean; notes: LegalNote[];
  products: Product[]; why: string;  // filled for tasks from the care plan
  next_due?: string | null;  // the next open to-do
}
export interface Pest { name: string; time: string; prevent: string; treat: string }
export interface CarePlan {
  id: string; created_at: string; model: string; prompt_version: string; summary: string;
  confidence: 'low' | 'medium' | 'high'; caveats: string; pests: Pest[]; dropped: number;
}
export interface PlanJob { id: string; status: 'queued' | 'running' | 'done' | 'failed'; error: string | null; created_at: string; finished_at: string | null }
export interface PlanState { plan: CarePlan | null; job: PlanJob | null }
export interface AiCandidate {
  latin: string; german: string[]; family: string | null; growth: string; woody: boolean; cultivar: string | null;
  form_hint: Form | null; note: string; known_species_id: string | null;
}
export interface NameJob { id: string; query: string; status: 'queued' | 'running' | 'done' | 'failed'; error: string | null; candidates: AiCandidate[] }
export interface Reading { value: number; at: string; stale: boolean }
export interface WeatherDay { date: string; source: 'dwd' | 'openmeteo'; t_min: number | null; t_max: number | null; ground_min: number | null; precip: number | null; gust_max: number | null; frost: boolean }
export interface WeatherAlert { kind: 'frost' | 'strong_frost' | 'late_frost' | 'heat' | 'storm'; label: string; day: string; value: number; text: string; tasks: number }
export interface Weather {
  available: boolean;
  alerts: WeatherAlert[];
  current?: { outdoor?: Reading; greenhouse?: Reading; rain_day?: Reading; rain_rate?: Reading; wind?: Reading; gust?: Reading; solar?: Reading; soil: (Reading & { label: string })[] };
  days?: WeatherDay[];
  stale?: { sensors: string | null; forecast: string | null };  // null = fresh, ISO time = since then, 'unbekannt'
}
export interface SeasonPhase {
  key: string; name: string; indicator: string; date: string | null; source: 'dwd' | 'garten' | null; reports: number;
  normal: string | null; expected: string | null;
}
export interface Season {
  current: { key: string; name: string; since: string; source: 'dwd' | 'garten' | 'mittel'; reports: number; delay_days: number | null } | null;
  phases: SeasonPhase[];
  next: SeasonPhase | null;
  gdd: { sum: number; as_of: string; normal: number; days_ahead: number | null } | null;
  region_ready: boolean;
}
export interface ChatSummary { id: string; title: string; updated_at: string }
export interface ChatAction { id: string; kind: 'aufgabe' | 'notiz' | 'diagnose'; payload: Record<string, unknown>; status: 'proposed' | 'done' | 'rejected'; plant: string | null }
export interface ChatMessage { id: string; role: 'user' | 'assistant'; text: string; status: 'queued' | 'running' | 'done' | 'failed'; error: string | null; photos: string[]; actions: ChatAction[] }
export interface ChatFull { id: string; title: string; plant: { id: string; name: string } | null; messages: ChatMessage[] }
export interface Ask { photo_ids?: string[]; plant_id?: string }
export type HistoryItem =
  | { kind: 'aufgabe'; id: string; at: string; title: string; category: Category; status: 'done' | 'skipped'; note: string }
  | { kind: 'diagnose'; id: string; at: string; title: string; confidence: string; cause: string; photos: string[] };
export interface Picked { species_id: string; cultivar_id: string | null; latin: string; german: string; form_hint: Form | null }
export interface Todo {
  id: string; status: 'open' | 'done' | 'skipped'; due_from: string; due_to: string; overdue: boolean; postponed: boolean;
  note: string; done_at: string | null; legal_adjustment: string | null; notes: LegalNote[];
  soil?: Soil | null;  // watering: how the soil was (once)
  blocked_until: string | null;  // strong cut not allowed today (§ 39): first allowed day
  task: { id: string; title: string; category: Category; urgent: boolean; instructions: string; recurrence: Recurrence; amount_ml?: number | null };
  plant: { id: string; title: string } | null;
}
export type Soil = 'feucht' | 'passt' | 'trocken';
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
  weather: () => request<Weather>('GET', '/weather'),
  alerts: () => request<WeatherAlert[]>('GET', '/alerts'),
  season: () => request<Season>('GET', '/season'),
  observe: (phase: string, day: string) => request<Season>('POST', '/season/observations', { phase, day }),
  unobserve: (phase: string) => request<unknown>('DELETE', `/season/observations/${enc(phase)}`),
  chats: () => request<ChatSummary[]>('GET', '/chats'),
  chat: (id: string) => request<ChatFull>('GET', `/chats/${enc(id)}`),
  newChat: (text: string, extra: Ask = {}) => request<{ chat_id: string; message_id: string }>('POST', '/chats', { text, ...extra }),
  ask: (id: string, text: string, extra: Ask = {}) => request<{ chat_id: string; message_id: string }>('POST', `/chats/${enc(id)}/messages`, { text, ...extra }),
  deleteChat: (id: string) => request<unknown>('DELETE', `/chats/${enc(id)}`),
  confirmAction: (id: string) => request<unknown>('POST', `/chat-actions/${enc(id)}/confirm`),
  rejectAction: (id: string) => request<unknown>('POST', `/chat-actions/${enc(id)}/reject`),
  askNames: (q: string, photo_ids: string[] = []) => request<{ job_id: string }>('POST', '/species/ai', { q, photo_ids }),
  nameJob: (id: string) => request<NameJob>('GET', `/species/ai/${enc(id)}`),
  pickName: (id: string, index: number) => request<Picked>('POST', `/species/ai/${enc(id)}/pick`, { index }),
  species: (id: string) => request<Species>('GET', `/species/${enc(id)}`),
  updateSpecies: (id: string, t: { german: string[]; growth: string; woody: boolean; hardiness_c: number | null }) => request<Species>('PUT', `/species/${enc(id)}`, t),
  createCultivar: (speciesId: string, name: string) => request<{ id: string; name: string }>('POST', `/species/${enc(speciesId)}/cultivars`, { name }),
  plants: (archived = false) => request<Plant[]>('GET', `/plants${archived ? '?archived=true' : ''}`),
  plant: (id: string) => request<Plant>('GET', `/plants/${enc(id)}`),
  createPlant: (p: PlantIn) => request<Plant>('POST', '/plants', p),
  updatePlant: (id: string, p: PlantIn) => request<Plant>('PUT', `/plants/${enc(id)}`, p),
  archivePlant: (id: string) => request<Plant>('POST', `/plants/${enc(id)}/archive`),
  restorePlant: (id: string) => request<Plant>('POST', `/plants/${enc(id)}/restore`),
  history: (id: string) => request<HistoryItem[]>('GET', `/plants/${enc(id)}/history`),
  tasks: (plantId?: string) => request<Task[]>('GET', `/tasks${plantId ? `?plant_id=${enc(plantId)}` : ''}`),
  task: (id: string) => request<Task>('GET', `/tasks/${enc(id)}`),
  plan: (plantId: string) => request<PlanState>('GET', `/plants/${enc(plantId)}/plan`),
  requestPlan: (plantId: string) => request<{ job_id: string }>('POST', `/plants/${enc(plantId)}/plan`),
  createTask: (t: TaskIn) => request<Task>('POST', '/tasks', t),
  updateTask: (id: string, t: TaskIn) => request<Task>('PUT', `/tasks/${enc(id)}`, t),
  setTaskEnabled: (id: string, on: boolean) => request<Task>('POST', `/tasks/${enc(id)}/${on ? 'enable' : 'disable'}`),
  heute: () => request<Heute>('GET', '/todos/heute'),
  todo: (id: string) => request<Todo>('GET', `/todos/${enc(id)}`),
  done: (id: string, note?: string) => request<Todo>('POST', `/todos/${enc(id)}/done`, note === undefined ? {} : { note }),
  skip: (id: string, note?: string) => request<Todo>('POST', `/todos/${enc(id)}/skip`, note === undefined ? {} : { note }),
  later: (id: string) => request<Todo>('POST', `/todos/${enc(id)}/later`),  // still moist: look again soon
  doneNow: (taskId: string, note?: string) => request<Todo>('POST', `/tasks/${enc(taskId)}/done-now`, note ? { note } : {}),
  soil: (id: string, soil: Soil) => request<Todo>('POST', `/todos/${enc(id)}/soil`, { soil }),
  undo: (id: string) => request<Todo>('POST', `/todos/${enc(id)}/undo`),
  postpone: (id: string, to: string) => request<Todo>('POST', `/todos/${enc(id)}/postpone`, { to }),
  pushKey: () => request<{ public_key: string | null }>('GET', '/push/key'),
  pushSubscribe: (s: { endpoint: string; keys: { p256dh: string; auth: string }; label: string }) => request<{ id: string }>('POST', '/push/subscriptions', s),
  pushUnsubscribe: (endpoint: string) => request<unknown>('POST', '/push/unsubscribe', { endpoint }),
  pushTest: (endpoint: string) => request<unknown>('POST', '/push/test', { endpoint }),
  legalPreview: (t: TaskIn) => request<{ notes: LegalNote[]; next: { due_from: string; due_to: string; reason: string } | null }>('POST', '/legal/preview', t),
  calendar: (year: number) => request<{ year: number; months: CalendarEntry[][] }>('GET', `/calendar?year=${year}`),
};
