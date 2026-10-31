// Invented demo garden for the UI prototype. Shapes follow the planned data
// model (requirements 06) so the screens can later switch to the API one by
// one. Species/Sorte names are public knowledge; places and dates are made up.

export type Category = 'Schnitt' | 'Düngen' | 'Ernte' | 'Pflanzenschutz' | 'Winterschutz' | 'Aussaat';
export type Light = 'sonnig' | 'halbschattig' | 'schattig';

export interface Standort { id: string; name: string; light: Light; type: string }
export interface PlanTask { month: number; category: Category; title: string; detail: string }
export interface Pest { name: string; time: string; prevent: string; treat: string }
export interface HistoryEntry { date: string; title: string; note?: string }
export interface Plant {
  id: string; name: string; latin: string; standortId: string; form: string; planted: number; hardy: string;
  woody: boolean; next: string; plan: PlanTask[]; pests: Pest[]; history: HistoryEntry[];
}
export interface Todo {
  id: string; title: string; category: Category; urgent?: boolean; plantIds: string[]; plantText: string;
  when: string; done?: boolean; doneNote?: string;
}
export interface TaskDetail {
  why: string; steps: string[]; material?: { name: string; brands: string; shops: string }; legal: string; timing: string;
}

export const TODAY = { weekday: 'Montag', date: '2. November', month: 10 };
export const MONTHS = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'];
export const isBirdProtection = (m: number) => m >= 2 && m <= 8;

export const SEASON = { name: 'Spätherbst', index: 8, since: '28.10.', delayDays: 4 };
export const SEASONS = [
  'Vorfrühling · Hasel blüht', 'Erstfrühling · Forsythie', 'Vollfrühling · Apfelblüte', 'Frühsommer · Holunderblüte',
  'Hochsommer · Sommerlinde', 'Spätsommer · Frühäpfel reif', 'Frühherbst · Holunderfrüchte', 'Vollherbst · Eicheln',
  'Spätherbst · Laubfall', 'Winter · Vegetationsruhe',
];

export const SENSORS = [
  { label: 'Luft', value: '7,4 °C' }, { label: 'Boden', value: '8,1 °C' }, { label: 'Gewächshaus', value: '11,2 °C' },
  { label: 'Sonne', value: '18 klx' }, { label: 'Regen 24 h', value: '2,1 mm' }, { label: 'Wind', value: '12 km/h' },
];
export const NIGHTS = [
  { day: 'Mo', t: 2 }, { day: 'Di', t: -4 }, { day: 'Mi', t: -6 }, { day: 'Do', t: -5 }, { day: 'Fr', t: 1 }, { day: 'Sa', t: 3 }, { day: 'So', t: 4 },
];
export const ALERT = {
  title: 'Frühe Kältewelle',
  short: 'Frühe Kältewelle ab Di 3.11.',
  text: 'Drei Frostnächte ab Dienstag, tiefster Wert −6 °C. Hier ist der erste Frost unter −2 °C sonst erst ab Mitte November zu erwarten.',
  forecastAt: 'So 17:00',
  push: { time: 'So 18:02', title: 'Kältewelle ab Dienstag: bis −6 °C', body: '2 Aufgaben bis Montagabend: Dahlien ausgraben, Oleander reinstellen.' },
  notAffected: 'Säulenobst, Felsenbirne, Hirse und Ramblerrose sind bis −20 °C winterhart. Das Gewächshaus bleibt laut Sensor frostfrei (min. +3 °C).',
};

export const STANDORTE: Standort[] = [
  { id: 'weg', name: 'Weg', light: 'sonnig', type: 'Beet' },
  { id: 'zaun', name: 'Zaun Süd', light: 'sonnig', type: 'Beet' },
  { id: 'hecke', name: 'Hecke Nord', light: 'halbschattig', type: 'Hecke' },
  { id: 'kies', name: 'Kiesbeet', light: 'sonnig', type: 'Beet' },
  { id: 'haus', name: 'Beet am Haus', light: 'halbschattig', type: 'Beet' },
  { id: 'terrasse', name: 'Kübelplatz Terrasse', light: 'sonnig', type: 'Kübelplatz' },
  { id: 'gemuese', name: 'Gemüsebeete', light: 'sonnig', type: 'Gemüsebeet' },
  { id: 'gewaechshaus', name: 'Gewächshaus', light: 'sonnig', type: 'Gewächshaus' },
];

const applePests: Pest[] = [
  { name: 'Apfelwickler', time: 'Mai–Aug', prevent: 'Pheromonfalle ab Mai, Wellpappe-Gürtel ab Juli.', treat: 'Befallene Früchte früh abnehmen; Granulosevirus-Präparat (Haus- und Kleingarten zugelassen).' },
  { name: 'Frostspanner', time: 'Okt–Apr', prevent: 'Leimring an Stamm und Pfahl ab Oktober.', treat: 'Raupen im April absammeln.' },
  { name: 'Apfelsägewespe', time: 'Blüte', prevent: 'Weißtafel zur Blüte in die Krone hängen.', treat: 'Befallene Jungfrüchte (Bohrloch) entfernen.' },
  { name: 'Apfelschorf', time: 'Apr–Jun', prevent: 'Falllaub im Herbst entfernen, Krone luftig halten.', treat: 'Befallene Blätter entsorgen; Netzschwefel nur nach Packungsangabe.' },
];

export const PLANTS: Plant[] = [
  {
    id: 'rhapsodie', name: 'Säulenapfel ‘Rhapsodie’', latin: 'Malus domestica ‘Rhapsodie’®', standortId: 'weg', form: 'Säule, im Boden', planted: 2022, hardy: 'bis ca. −25 °C', woody: true,
    next: 'Leimring prüfen · diese Woche',
    plan: [
      { month: 1, category: 'Schnitt', title: 'Verjüngung: 1 alten Fruchtast entfernen', detail: 'Nur alle 3–4 Jahre, auf Zapfen schneiden. Nächstes Mal 2028.' },
      { month: 2, category: 'Düngen', title: 'Organischer Volldünger, 80 g', detail: 'z. B. Oscorna Animalin, Neudorff Azet Obst- & Beerendünger, Compo Bio Obstdünger.' },
      { month: 3, category: 'Pflanzenschutz', title: 'Weißtafel gegen Apfelsägewespe', detail: 'Zur Blüte in die Krone hängen, wöchentlich zählen.' },
      { month: 5, category: 'Schnitt', title: 'Sommerschnitt Seitentriebe', detail: 'Auf 2–3 Blätter einkürzen. Schonender Pflegeschnitt: in der Vogelschutzzeit erlaubt.' },
      { month: 5, category: 'Ernte', title: 'Junifruchtfall abwarten, dann ausdünnen', detail: 'Auf 1 Frucht je Büschel, ca. 20 cm Abstand.' },
      { month: 9, category: 'Ernte', title: 'Ernte ‘Rhapsodie’', detail: 'Pflückreife Anfang Oktober (je nach Jahr ±10 Tage). Lagerfähig bis Januar.' },
      { month: 9, category: 'Pflanzenschutz', title: 'Leimring anlegen', detail: 'Stamm und Pfahl, bis Mitte Dezember wöchentlich prüfen.' },
      { month: 10, category: 'Pflanzenschutz', title: 'Fruchtmumien + Falllaub entfernen', detail: 'Gegen Schorf und Monilia.' },
    ],
    pests: applePests,
    history: [
      { date: '1.11.26', title: 'Letzte Äpfel geerntet', note: '12 Stück, eingelagert' },
      { date: '12.10.26', title: 'Leimring angelegt' },
      { date: '28.6.26', title: 'Sommerschnitt', note: 'Viele Seitentriebe' },
      { date: '14.3.26', title: 'Gedüngt', note: 'Oscorna Animalin, 80 g' },
    ],
  },
  {
    id: 'sonate', name: 'Säulenapfel ‘Sonate’', latin: 'Malus domestica ‘Sonate’®', standortId: 'weg', form: 'Säule, im Boden', planted: 2022, hardy: 'bis ca. −25 °C', woody: true,
    next: 'Fruchtmumien abnehmen · Nov',
    plan: [
      { month: 2, category: 'Düngen', title: 'Organischer Volldünger, 80 g', detail: 'z. B. Oscorna Animalin oder Compo Bio Obstdünger.' },
      { month: 3, category: 'Pflanzenschutz', title: 'Weißtafel gegen Apfelsägewespe', detail: 'Zur Blüte.' },
      { month: 5, category: 'Schnitt', title: 'Sommerschnitt Seitentriebe', detail: 'Auf 2–3 Blätter einkürzen.' },
      { month: 8, category: 'Ernte', title: 'Ernte ‘Sonate’', detail: 'Pflückreife prüfen: Kerne braun, Frucht löst sich leicht.' },
      { month: 9, category: 'Pflanzenschutz', title: 'Leimring anlegen', detail: 'Stamm und Pfahl.' },
      { month: 10, category: 'Pflanzenschutz', title: 'Fruchtmumien + Falllaub entfernen', detail: 'Gegen Schorf.' },
    ],
    pests: applePests,
    history: [{ date: '18.9.26', title: 'Geerntet', note: '20 Äpfel' }],
  },
  {
    id: 'celeste', name: 'Süßkirsche ‘Celeste’', latin: 'Prunus avium ‘Celeste’', standortId: 'weg', form: 'Säule, im Boden', planted: 2023, hardy: 'bis ca. −25 °C', woody: true,
    next: 'Leimring prüfen · diese Woche',
    plan: [
      { month: 2, category: 'Düngen', title: 'Organischer Volldünger, 60 g', detail: 'z. B. Neudorff Azet Obst- & Beerendünger.' },
      { month: 5, category: 'Pflanzenschutz', title: 'Gelbtafeln gegen Kirschfruchtfliege', detail: 'Aufhängen, wenn die Früchte von Grün nach Gelb wechseln.' },
      { month: 6, category: 'Ernte', title: 'Kirschen ernten', detail: 'Früchte mit Stiel pflücken.' },
      { month: 6, category: 'Schnitt', title: 'Schnitt direkt nach der Ernte', detail: 'Steinobst im Sommer schneiden (heilt besser). Schonend – Vogelschutzzeit.' },
      { month: 9, category: 'Pflanzenschutz', title: 'Leimring anlegen', detail: 'Stamm und Pfahl.' },
    ],
    pests: [
      { name: 'Kirschfruchtfliege', time: 'Mai–Jul', prevent: 'Gelbtafeln bei Farbumschlag der Früchte, Boden im Juni mit Netz abdecken.', treat: 'Alle Früchte ernten, befallene entsorgen.' },
      { name: 'Schwarze Kirschenblattlaus', time: 'Apr–Jun', prevent: 'Nützlinge fördern.', treat: 'Triebspitzen abschneiden, Kaliseife nach Packungsangabe.' },
    ],
    history: [{ date: '8.7.26', title: 'Kirschen geerntet', note: '1,5 kg' }],
  },
  {
    id: 'obelisk', name: 'Felsenbirne ‘Obelisk’', latin: 'Amelanchier alnifolia ‘Obelisk’', standortId: 'hecke', form: 'Säulenstrauch', planted: 2021, hardy: 'bis ca. −30 °C', woody: true,
    next: 'Auslichten · Feb (bis 28.2.)',
    plan: [
      { month: 0, category: 'Winterschutz', title: 'Schneelast abschütteln', detail: 'Schmale Säulenform bricht bei nassem Schnee auseinander.' },
      { month: 1, category: 'Schnitt', title: 'Auslichten', detail: '1–2 alte Triebe bodennah entfernen. Stärkerer Schnitt nur bis 28.2. (§ 39 BNatSchG).' },
      { month: 6, category: 'Ernte', title: 'Beeren ernten', detail: 'Wenn sie dunkelblau sind – vor den Vögeln.' },
    ],
    pests: [{ name: 'Feuerbrand (selten)', time: 'Mai–Jul', prevent: 'Pflanze beobachten.', treat: 'Meldepflichtig: verdorrte Triebspitzen tief zurückschneiden, Pflanzenschutzamt informieren.' }],
    history: [],
  },
  {
    id: 'rambler', name: 'Ramblerrose ‘Ghislaine de Féligonde’', latin: 'Rosa ‘Ghislaine de Féligonde’', standortId: 'zaun', form: 'Rambler am Zaun', planted: 2020, hardy: 'bis ca. −20 °C', woody: true,
    next: 'Anhäufeln · Nov',
    plan: [
      { month: 2, category: 'Schnitt', title: 'Nur tote Triebe entfernen', detail: 'Rambler blühen am alten Holz – im Frühjahr nicht einkürzen.' },
      { month: 2, category: 'Düngen', title: 'Rosendünger, 60 g/m²', detail: 'z. B. Compo Rosendünger, Neudorff Azet RosenDünger.' },
      { month: 6, category: 'Schnitt', title: 'Nach der Blüte auslichten', detail: 'Alle 3 Jahre 1–2 alte Triebe bodennah. Schonend – vorher auf Nester prüfen.' },
      { month: 10, category: 'Winterschutz', title: 'Veredelungsstelle anhäufeln', detail: '15 cm Erde oder Kompost.' },
    ],
    pests: [
      { name: 'Sternrußtau', time: 'Jun–Sep', prevent: 'Laub im Herbst entfernen, morgens gießen statt abends.', treat: 'Befallene Blätter entsorgen.' },
      { name: 'Rosenblattlaus', time: 'Apr–Jun', prevent: 'Nützlinge fördern.', treat: 'Mit Wasserstrahl abspritzen.' },
    ],
    history: [{ date: '20.7.26', title: 'Ausgelichtet', note: '2 alte Triebe' }],
  },
  {
    id: 'hirse', name: 'Ruten-Hirse ‘Heavy Metal’', latin: 'Panicum virgatum ‘Heavy Metal’', standortId: 'kies', form: 'Horst', planted: 2021, hardy: 'bis ca. −28 °C', woody: false,
    next: 'Zusammenbinden · Nov',
    plan: [
      { month: 1, category: 'Schnitt', title: 'Auf 10 cm zurückschneiden und abbinden', detail: 'Zum Vorfrühling, bevor der Neuaustrieb kommt. Erst bündeln, dann schneiden.' },
      { month: 3, category: 'Düngen', title: 'Kompost, 2 l', detail: 'Mehr braucht die Hirse nicht.' },
      { month: 10, category: 'Winterschutz', title: 'Locker zusammenbinden', detail: 'Halme stehen lassen: Schutz für Insekten, schöner Winteraspekt.' },
    ],
    pests: [],
    history: [{ date: '24.2.26', title: 'Zurückgeschnitten' }],
  },
  {
    id: 'dahlie', name: 'Dahlie ‘Café au Lait’', latin: 'Dahlia ‘Café au Lait’', standortId: 'haus', form: 'Knolle', planted: 2025, hardy: 'nicht frosthart', woody: false,
    next: 'Ausgraben · dringend',
    plan: [
      { month: 4, category: 'Aussaat', title: 'Knollen pflanzen – nach dem letzten Frost', detail: 'Wetterabhängig, meist nach den Eisheiligen.' },
      { month: 6, category: 'Düngen', title: 'Kaliumbetonter Blühdünger', detail: 'z. B. Compo Blühpflanzendünger, alle 3 Wochen bis August.' },
      { month: 10, category: 'Winterschutz', title: 'Knollen ausgraben', detail: 'Nach dem ersten leichten Frost oder vor starkem Frost.' },
    ],
    pests: [{ name: 'Schnecken', time: 'Mai–Jun', prevent: 'Austrieb mit Schneckenkragen schützen.', treat: 'Absammeln; Eisen-III-Phosphat-Korn nach Packungsangabe.' }],
    history: [],
  },
  {
    id: 'oleander', name: 'Oleander', latin: 'Nerium oleander', standortId: 'terrasse', form: 'Kübel', planted: 2019, hardy: 'kurz bis −5 °C', woody: true,
    next: 'Ins Winterquartier · dringend',
    plan: [
      { month: 3, category: 'Winterschutz', title: 'Ausräumen', detail: 'Wenn keine Nachtfröste unter −2 °C mehr kommen.' },
      { month: 4, category: 'Düngen', title: 'Kübelpflanzendünger, wöchentlich', detail: 'z. B. Compo Kübelpflanzendünger, bis August.' },
      { month: 10, category: 'Winterschutz', title: 'Ins Winterquartier', detail: 'Hell, 5–10 °C.' },
    ],
    pests: [{ name: 'Schildläuse', time: 'ganzjährig', prevent: 'Im Winterquartier regelmäßig kontrollieren.', treat: 'Abstreifen, Rapsöl-Präparat nach Packungsangabe.' }],
    history: [],
  },
];

export const plantById = (id: string) => PLANTS.find((p) => p.id === id);
export const standortById = (id: string) => STANDORTE.find((s) => s.id === id);

export const TODOS: Todo[] = [
  { id: 'dahlie', urgent: true, category: 'Winterschutz', title: 'Dahlienknollen ausgraben und frostfrei einlagern', plantIds: ['dahlie'], plantText: 'Dahlie ‘Café au Lait’ · Beet am Haus', when: 'Dringend · bis Mo 2.11. abends' },
  { id: 'oleander', urgent: true, category: 'Winterschutz', title: 'Oleander ins Winterquartier räumen', plantIds: ['oleander'], plantText: 'Oleander · Kübelplatz Terrasse', when: 'Dringend · bis Mo 2.11. abends' },
  { id: 'mumien', category: 'Pflanzenschutz', title: 'Fruchtmumien abnehmen, Falllaub entsorgen', plantIds: ['sonate'], plantText: 'Säulenapfel ‘Sonate’ · Weg (gegen Schorf)', when: 'November' },
  { id: 'leimringe', category: 'Pflanzenschutz', title: 'Leimringe auf Frostspanner prüfen', plantIds: ['rhapsodie', 'celeste'], plantText: 'Säulenapfel ‘Rhapsodie’, Süßkirsche ‘Celeste’', when: 'Wöchentlich bis Mitte Dezember', done: true, doneNote: 'Erledigt am 30.10.' },
  { id: 'rose', category: 'Winterschutz', title: 'Veredelungsstelle 15 cm hoch anhäufeln', plantIds: ['rambler'], plantText: 'Ramblerrose ‘Ghislaine de Féligonde’ · Zaun Süd', when: 'November' },
  { id: 'hirse', category: 'Winterschutz', title: 'Hirse locker zusammenbinden – noch nicht schneiden', plantIds: ['hirse'], plantText: 'Ruten-Hirse ‘Heavy Metal’ · Kiesbeet', when: 'November · Rückschnitt im Februar' },
  { id: 'knoblauch', category: 'Aussaat', title: 'Knoblauch stecken', plantIds: [], plantText: 'Gemüsebeet 2 · Fruchtfolge passt (nach Kartoffeln)', when: 'Bis Mitte November' },
  { id: 'ernte', category: 'Ernte', title: 'Letzte Äpfel ernten', plantIds: ['rhapsodie'], plantText: 'Säulenapfel ‘Rhapsodie’', when: '', done: true, doneNote: 'Erledigt am 1.11. · „12 Stück, eingelagert“' },
];

// Proposed by the garden chat; only in the list after the user says yes.
export const CHAT_TODO: Todo = { id: 'vlies', urgent: true, category: 'Winterschutz', title: 'Gemüsebeet 1 mit Vlies abdecken', plantIds: [], plantText: 'Feldsalat (3 Wochen alt) · Gemüsebeet 1', when: 'Dringend · bis Mo 2.11. abends' };

export const TASK_DETAILS: Record<string, TaskDetail> = {
  leimringe: {
    timing: 'Wöchentlich bis Mitte Dezember',
    why: 'Die flugunfähigen Weibchen des Frostspanners klettern nach den ersten Frostnächten (Oktober bis Dezember) den Stamm hinauf und legen Eier in die Krone. Die Raupen fressen im Frühjahr Knospen und junge Früchte.',
    steps: [
      'Ring rundum ansehen: Sitzt er dicht am Stamm? Keine Lücken an Rinde oder Stützpfahl.',
      'Auch den Stützpfahl beringen – sonst klettern die Weibchen dort hoch.',
      'Laub und Zweige, die am Leim kleben, entfernen (Brücken).',
      'Ist die Leimfläche voll oder verschmutzt: Ring ersetzen.',
      'Gefangene Tiere zählen und als Notiz festhalten – zeigt, wie stark der Befall ist.',
    ],
    material: { name: 'Leimring, insektizidfrei, 3–5 m Rolle', brands: 'z. B. Neudorff Raupenleimring, Compo Raupen-Leimring, Schacht Leimgürtel', shops: 'Erhältlich u. a. bei OBI, Hornbach, Dehner, Raiffeisen-Markt · ca. 8–12 €' },
    legal: 'Kein Schnitt, keine rechtlichen Einschränkungen. Beim Arbeiten am Baum auf überwinternde Tiere achten (§ 44 BNatSchG).',
  },
  dahlie: {
    timing: 'Dringend wegen Frost · bis Mo 2.11. abends',
    why: 'Dahlienknollen sind nicht frosthart und erfrieren ab etwa −2 °C im Boden. Ab Dienstag sind drei Frostnächte bis −6 °C angesagt.',
    steps: [
      'Stängel auf 10–15 cm einkürzen und Namensschild anbringen.',
      'Knollen mit der Grabegabel großzügig ausheben – nicht mit dem Spaten, sonst werden sie verletzt.',
      'Erde grob abschütteln, Knollen 1–2 Tage kopfüber frostfrei abtrocknen lassen.',
      'In Kiste mit trockenem Sand oder Zeitungspapier lagern: dunkel, 5–8 °C.',
    ],
    material: { name: 'Grabegabel, Kiste, trockener Sand', brands: 'Sand z. B. Spielsand aus dem Baumarkt', shops: 'OBI, Hornbach, Bauhaus' },
    legal: 'Keine rechtlichen Einschränkungen.',
  },
  hirse: {
    timing: 'November · Rückschnitt erst im Februar',
    why: 'Die Halme schützen das Herz der Pflanze vor Nässe und bieten Insekten ein Winterquartier. Zusammengebunden knicken sie unter Schnee nicht auseinander.',
    steps: ['Halme mit einer Kordel locker auf halber Höhe zusammenbinden.', 'Nicht zu fest – Luft muss durchkommen.', 'Im Februar (Vorfrühling) auf 10 cm zurückschneiden.'],
    material: { name: 'Kokos- oder Jutekordel', brands: '', shops: 'Jeder Baumarkt' },
    legal: 'Gräser sind keine Gehölze – § 39 BNatSchG gilt nicht. Ökologische Empfehlung: stehen lassen bis zum Vorfrühling.',
  },
};

export const genericDetail = (todo: Todo): TaskDetail => ({
  timing: todo.when || 'Diesen Monat',
  why: 'Im fertigen Programm steht hier die Begründung aus dem Pflegeplan der Pflanze.',
  steps: ['Im Prototyp ist die vollständige Anleitung nur für drei Aufgaben ausgefüllt: Leimringe, Dahlien und Hirse.'],
  legal: 'Rechtliche Prüfung: keine Einschränkungen.',
});

export type CalEntry = [Category, string, string, string?];
export const CALENDAR: Record<number, CalEntry[]> = {
  0: [['Winterschutz', 'Schneelast von Hirse und Felsenbirne abschütteln', 'Kiesbeet, Hecke Nord'], ['Aussaat', 'Fruchtfolge planen: was kommt wohin?', 'Gemüsebeet 1–3']],
  1: [['Schnitt', 'Hirse auf 10 cm zurückschneiden und abbinden', 'Ruten-Hirse ‘Heavy Metal’ · zum Vorfrühling'], ['Schnitt', 'Felsenbirne auslichten', 'Felsenbirne ‘Obelisk’', 'Starker Schnitt nur bis 28.2. (§ 39)'], ['Aussaat', 'Paprika im Gewächshaus vorziehen', 'Gewächshaus · ab 20 °C Bodenwärme']],
  2: [['Düngen', 'Organischer Volldünger, 80 g je Säule', 'Säulenäpfel, Kirsche ‘Celeste’ · z. B. Oscorna Animalin'], ['Pflanzenschutz', 'Leimringe abnehmen', 'Säulenobst'], ['Schnitt', 'Ramblerrose: nur tote Triebe entfernen', 'Ramblerrose ‘Ghislaine de Féligonde’', 'Nur schonend – Vogelschutzzeit']],
  3: [['Pflanzenschutz', 'Weißtafeln gegen Apfelsägewespe aufhängen', 'Säulenäpfel · zur Blüte'], ['Aussaat', 'Tomaten pikieren', 'Gewächshaus']],
  4: [['Aussaat', 'Dahlien pflanzen – nach dem letzten Frost', 'Beet am Haus · wetterabhängig'], ['Aussaat', 'Tomaten auspflanzen', 'Gewächshaus']],
  5: [['Schnitt', 'Sommerschnitt: Seitentriebe auf 2–3 Blätter', 'Säulenäpfel', 'Schonender Pflegeschnitt – erlaubt'], ['Pflanzenschutz', 'Gelbtafeln gegen Kirschfruchtfliege', 'Kirsche ‘Celeste’ · wenn die Früchte gelb werden']],
  6: [['Ernte', 'Kirschen ernten', 'Kirsche ‘Celeste’'], ['Schnitt', 'Ramblerrose nach der Blüte auslichten', 'Ramblerrose ‘Ghislaine de Féligonde’', 'Nur schonend – vorher auf Nester prüfen']],
  7: [['Aussaat', 'Feldsalat säen', 'Gemüsebeet 1 · nach Frühkartoffeln']],
  8: [['Ernte', 'Äpfel ernten (Pflückreife prüfen)', 'Säulenapfel ‘Sonate’']],
  9: [['Pflanzenschutz', 'Leimringe anlegen', 'Säulenobst + Stützpfähle'], ['Ernte', 'Äpfel ernten', 'Säulenapfel ‘Rhapsodie’'], ['Düngen', 'Kein Stickstoff mehr – Holz ausreifen lassen', 'alle Gehölze']],
  10: [['Winterschutz', 'Dahlienknollen ausgraben', 'Dahlie ‘Café au Lait’'], ['Pflanzenschutz', 'Fruchtmumien abnehmen', 'Säulenäpfel'], ['Aussaat', 'Knoblauch stecken', 'Gemüsebeet 2']],
  11: [['Winterschutz', 'Winterquartier der Kübel kontrollieren', 'Oleander'], ['Schnitt', 'Gehölzschnitt möglich (frostfreie Tage)', 'Hecke Nord']],
};

export const NAME_SUGGESTIONS = [
  { de: 'Felsenbirne ‘Obelisk’', latin: 'Amelanchier alnifolia ‘Obelisk’', hint: 'Säulenförmig, essbare Früchte, Gehölz (§ 39 gilt)' },
  { de: 'Kupfer-Felsenbirne', latin: 'Amelanchier lamarckii', hint: 'Keine Sorte ‘Obelisk’ bekannt – Sorte unbekannt' },
  { de: 'Andere Pflanze …', latin: 'Name genauer eingeben', hint: '' },
];
