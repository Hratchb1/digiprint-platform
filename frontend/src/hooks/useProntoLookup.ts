// src/hooks/useProntoLookup.ts
import { useState, useCallback } from "react";
import { api } from "../lib/api";

export interface RollSummaryLine {
  label: string;
  qty: number;
}

export interface ProcessMixEntry {
  process_code: string | null;
  count: number;
}

export interface ProcessMix {
  total: number;
  mix: ProcessMixEntry[];
  unmapped: boolean;
}

export interface ProntoOrderResult {
  found: boolean;
  sales_order_number: string;
  territory: string;
  customer_name: string;
  email_address: string;
  phone_number: string;
  pronto_account: string;
  inferred_service_type: string;
  total_rolls: number;
  roll_summary: RollSummaryLine[];
  scan_summary: RollSummaryLine[];
  print_summary: RollSummaryLine[];
  synced_at: string;
  // Twin check allocation — additive field, see api/pronto.py. How many
  // rolls this order needs a twin check for, and their process-code mix,
  // derived live from sku_map (not the coarser roll_summary above).
  process_mix?: ProcessMix;
}

interface UseProntoLookupReturn {
  lookup: (orderNumber: string) => Promise<void>;
  order: ProntoOrderResult | null;
  loading: boolean;
  error: string | null;
  clear: () => void;
}

export function useProntoLookup(): UseProntoLookupReturn {
  const [order, setOrder]     = useState<ProntoOrderResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);

  const lookup = useCallback(async (orderNumber: string) => {
    const trimmed = orderNumber.trim();
    if (!trimmed) return;

    setLoading(true);
    setError(null);
    setOrder(null);

    try {
      const { data } = await api.get(`/pronto/lookup/${trimmed}`);
      setOrder(data);
    } catch (err: any) {
      if (err.response?.status === 404) {
        setError(`Order ${trimmed} not found in Pronto. Check the number and try again.`);
      } else {
        setError("Could not reach Pronto data. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const clear = useCallback(() => {
    setOrder(null);
    setError(null);
  }, []);

  return { lookup, order, loading, error, clear };
}