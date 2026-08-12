// src/lib/serviceTypes.ts
//
// Single source of truth for film service-type labels (shown in the UI)
// mapped to the backend's ServiceType enum values (backend/app/models/schemas.py).
// IntakePage.tsx and ProntoOrderSummary.tsx both import from here so the two
// can never drift apart again — do not redeclare either list locally.
//
// If you add/rename a service type, update SERVICE_TYPE_MAP here AND the
// ServiceType enum in backend/app/models/schemas.py. scripts/check_service_types.mjs
// diffs the two and fails if they disagree — run it (or let CI run it) after
// any change here.

export const SERVICE_TYPE_MAP: Record<string, string> = {
  "Develop only":           "Dev only",
  "Develop + Scan":         "Dev+Scan",
  "Develop + Scan + Print": "Dev+Scan+Print",
  "Develop + Print":        "Dev+Print",
  "Scan only":              "Scan only",
  "Print only":             "Print only",
};

export const SERVICE_TYPES = Object.keys(SERVICE_TYPE_MAP);

/**
 * Hard lookup from display label to backend enum value.
 * Returns null (never the raw label) when the label isn't recognised —
 * callers must treat null as "block the booking", not fall back to
 * sending the label itself. An unmapped value must never reach the API.
 */
export function toBackendServiceType(label: string): string | null {
  return Object.prototype.hasOwnProperty.call(SERVICE_TYPE_MAP, label)
    ? SERVICE_TYPE_MAP[label]
    : null;
}
