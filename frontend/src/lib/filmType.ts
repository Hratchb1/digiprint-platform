// Film-type colour-coding for OrdersPage — lets staff scan the list
// visually by process rather than reading each order.
//
// order.film_type is a live join to pronto_cache (see
// order_service._attach_film_types / api/orders.py::_enrich), not a stored
// column — it's None for manual entries and any order without a matching
// Pronto sales order. Live values today (pronto_cache.film_type) are one of
// "C41 35mm" / "C41 120mm" / "B&W 35mm" / "B&W 120mm" — colour keys off the
// leading process token (C41 / B&W / E6) since that's the visually
// meaningful distinction for staff; format (35mm/120mm) doesn't get its own
// colour. E6 has zero rows in production today but is kept here so slide
// film gets a sensible colour the moment it shows up rather than falling
// through to the neutral default.
//
// Colours are chosen to stay clear of StatusPill's existing palette
// (yellow/blue/purple/green/red — see lib/status.ts) so the two badges
// sitting in the same row never get confused for one another.

export interface FilmTypeMeta {
  label: string
  dot: string        // small colour swatch (status-pill-style bg)
  border: string      // row left-border accent
}

const FILM_TYPE_META: Record<string, FilmTypeMeta> = {
  C41: {
    label: 'C41',
    dot: 'bg-teal-500/10 text-teal-400 border-teal-500/20',
    border: 'border-l-teal-500/60',
  },
  'B&W': {
    label: 'B&W',
    dot: 'bg-slate-400/10 text-slate-300 border-slate-400/20',
    border: 'border-l-slate-400/60',
  },
  E6: {
    label: 'E6',
    dot: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20',
    border: 'border-l-indigo-500/60',
  },
}

const FALLBACK_BORDER = 'border-l-transparent'

/** Leading process token, e.g. "C41 35mm" -> "C41", "B&W 120mm" -> "B&W". */
function processKey(filmType: string): string {
  return filmType.trim().split(/\s+/)[0].toUpperCase()
}

export function filmTypeMeta(filmType: string | null | undefined): FilmTypeMeta | null {
  if (!filmType) return null
  return FILM_TYPE_META[processKey(filmType)] ?? null
}

/** Row left-border accent class — transparent (not omitted) when unknown, so
 *  every row reserves the same 2px so the list doesn't visually jump. */
export function filmTypeBorder(filmType: string | null | undefined): string {
  return filmTypeMeta(filmType)?.border ?? FALLBACK_BORDER
}
