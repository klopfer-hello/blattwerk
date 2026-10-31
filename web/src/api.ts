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
  if (!res.ok) throw new ApiError(res.status, data.error ?? `Fehler ${res.status}`, data.fields ?? {});
  return data as T;
}

export const api = {
  settings: () => request<GardenSettings>('GET', '/settings'),
  saveSettings: (s: GardenSettings) => request<GardenSettings>('PUT', '/settings', s),
};
