// All data comes from the local FastAPI backend, which reads only from
// committed snapshots. Nothing here reaches the public internet -- that's
// the Phase 8 airplane-mode exit criterion, not an accident.
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

export type CriPoint = {
  date: string;
  CRI: number | null;
  O: number | null;
  S: number | null;
  E: number | null;
  X: number | null;
  components_used: string;
};

export type CriSeries = {
  corridor_id: string;
  weights: Record<string, number>;
  as_of: string | null;
  series: CriPoint[];
};

export type TwinNode = {
  id: string;
  kind: "Source" | "Port" | "Refinery" | "Corridor";
  name?: string;
  lat?: number;
  lon?: number;
  capacity_kbd?: number;
  country?: string;
  operator?: string;
};

export type TwinGraph = {
  nodes: TwinNode[];
  edges: { source: string; target: string; key: string; distance_km?: number }[];
};

export type Allocation = {
  source: string;
  refinery: string;
  country: string;
  corridor_id: string;
  kbd: number;
};

export type ProcurementResult = {
  status: string;
  lambda_risk: number;
  total_allocated_kbd: number;
  total_shortfall_kbd: number;
  corridor_cri_used: Record<string, number>;
  concentration_cap_pct: number | null;
  country_shares: Record<string, number>;
  allocation: Allocation[];
  shortfall_by_refinery: Record<string, number>;
  caveat: string;
};

export type ScenarioResult = {
  scenario: Record<string, unknown>;
  total_shortfall_kbd: number;
  run_cuts: Record<string, number>;
  product_shortfall_kbd: Record<string, number>;
  price_usd_bbl: number;
  price_baseline_usd_bbl: number;
  macro: {
    import_bill_delta_annualized_usd: number;
    import_bill_delta_over_scenario_usd: number;
    pct_of_gdp: number;
    cpi_impact_pct: number;
  };
  method: Record<string, string>;
  confidence: Record<string, string>;
  calibration: { value: number; confidence: string };
};

export type ReserveResult = {
  daily_gap_kbd: number;
  duration_days: number;
  capacity_bbl: number;
  max_pumpout_rate_kbd: number;
  days_to_exhaustion: number | null;
  days_of_cover_at_start: number;
  total_unserved_kbd_days: number;
  schedule: {
    day: number;
    stock_kbd_equiv: number;
    draw_kbd: number;
    unserved_kbd: number;
    days_of_cover_remaining: number;
  }[];
  caveat: string;
};

export type BacktestResult = {
  fit_window: string;
  validation_window: string;
  caveat: string;
  horizons: {
    horizon: number;
    auc: number | null;
    n_fit: number;
    n_valid: number;
    fit_positive_rate: number;
    valid_positive_rate: number;
    fit_components: string;
    valid_components: string;
    reliability: { mean_predicted: number; observed_rate: number; n: number }[];
  }[];
};

export type Corridors = {
  corridors: {
    corridor_id: string;
    name: string;
    india_crude_import_share_pct: number | null;
    normal_capacity_kbd: number | null;
    note: string;
  }[];
};

export type BypassRoutes = {
  routes: {
    route_name: string;
    bypasses_corridor: string;
    capacity_kbd: number | null;
    discharge_corridor: string;
    status: string;
    note: string;
  }[];
};

// Shared semantic risk ramp. Must match globals.css -- one colour, one
// meaning, everywhere on the dashboard.
export function riskColor(cri: number | null | undefined): string {
  if (cri == null || Number.isNaN(cri)) return "#4a5568";
  if (cri < 20) return "#2dd4a7";
  if (cri < 40) return "#a3d13a";
  if (cri < 60) return "#f0b429";
  if (cri < 80) return "#f2762e";
  return "#e5484d";
}

export function riskRgb(cri: number | null | undefined): [number, number, number] {
  const hex = riskColor(cri).replace("#", "");
  return [
    parseInt(hex.slice(0, 2), 16),
    parseInt(hex.slice(2, 4), 16),
    parseInt(hex.slice(4, 6), 16),
  ];
}

/** Recharts hands formatters `ValueType | undefined` (string | number |
 *  array). Narrow once here instead of casting at every call site. */
export function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

export function fmt(n: number | null | undefined, digits = 1): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}
