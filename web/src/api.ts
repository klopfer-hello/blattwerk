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
  notifications: { weather_push: boolean };
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
};
