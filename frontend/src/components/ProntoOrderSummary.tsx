// src/components/ProntoOrderSummary.tsx
import React from "react";
import { ProntoOrderResult } from "../hooks/useProntoLookup";

const SERVICE_TYPES = [
  "Develop only",
  "Develop + Scan",
  "Develop + Scan + Print",
  "Scan only",
  "Print only",
];

interface Props {
  order: ProntoOrderResult;
  serviceType: string;
  onServiceTypeChange: (val: string) => void;
  onConfirm: () => void;
  onClear: () => void;
  dupAction?: "add" | "new" | null;
  existingOrderRollCount?: number;
}

const FILM_COLOURS: Record<string, string> = {
  "C41 35mm":  "bg-blue-900 text-blue-200",
  "B&W 35mm":  "bg-gray-700 text-gray-200",
  "C41 120mm": "bg-purple-900 text-purple-200",
  "B&W 120mm": "bg-gray-800 text-gray-300",
};

const SCAN_COLOURS: Record<string, string> = {
  "Standard Scan": "bg-green-900 text-green-200",
  "Medium Scan":   "bg-yellow-900 text-yellow-200",
  "High Scan":     "bg-orange-900 text-orange-200",
};

function Pill({ label, qty, colourMap }: { label: string; qty: number; colourMap: Record<string, string> }) {
  const colours = colourMap[label] ?? "bg-gray-700 text-gray-200";
  return (
    <span className={`inline-flex items-center gap-1 px-3 py-1 rounded-full text-sm font-medium ${colours}`}>
      {label} <span className="font-bold">× {qty}</span>
    </span>
  );
}

export function ProntoOrderSummary({
  order, serviceType, onServiceTypeChange, onConfirm, onClear,
  dupAction, existingOrderRollCount
}: Props) {
  const allTypes = SERVICE_TYPES.includes(order.inferred_service_type)
    ? SERVICE_TYPES
    : [...SERVICE_TYPES, order.inferred_service_type];

  // Roll count = dev SKU quantity only
  const devRollCount = order.roll_summary.reduce((sum, line) => sum + line.qty, 0);

  const confirmLabel = dupAction === "add"
    ? "Confirm & add twins to existing order"
    : dupAction === "new"
    ? `Confirm & enter twins for ${order.sales_order_number}-B`
    : "Confirm & enter twins";

  return (
    <div className="rounded-xl border border-gray-700 p-5 space-y-4" style={{ backgroundColor: "#1f2937" }}>

      {/* Dup action indicator */}
      {dupAction === "add" && existingOrderRollCount !== undefined && (
        <div className="rounded-lg px-3 py-2 text-sm" style={{ backgroundColor: "#1e3a5f" }}>
          <p className="text-blue-300">
            ➕ Adding to existing order — currently has {existingOrderRollCount} roll{existingOrderRollCount !== 1 ? "s" : ""}
          </p>
        </div>
      )}
      {dupAction === "new" && (
        <div className="rounded-lg px-3 py-2 text-sm" style={{ backgroundColor: "#1a2e1a" }}>
          <p className="text-green-300">
            📋 New booking — will be created as {order.sales_order_number}-B
          </p>
        </div>
      )}

      {/* Customer details */}
      <div>
        <p className="text-xs text-gray-500 font-mono">
          Order #{order.sales_order_number} · {order.territory}
        </p>
        <h3 className="text-lg font-semibold text-white mt-0.5">{order.customer_name || "—"}</h3>
        {order.email_address
          ? <p className="text-sm text-gray-400">{order.email_address}</p>
          : <p className="text-sm text-amber-400 font-medium">⚠ No email in Pronto — add manually</p>
        }
        {order.phone_number   && <p className="text-sm text-gray-500">{order.phone_number}</p>}
        {order.pronto_account && <p className="text-sm text-gray-500">Account: {order.pronto_account}</p>}
        {order.sales_rep_name && <p className="text-sm text-gray-500">Sales rep: {order.sales_rep_name}</p>}
      </div>

      {/* Service type — editable */}
      <div className="space-y-1">
        <p className="text-xs text-gray-500 uppercase tracking-wide">Service type</p>
        <select
          value={serviceType}
          onChange={(e) => onServiceTypeChange(e.target.value)}
          className="w-full rounded-lg px-3 py-2 text-sm text-white border border-gray-600 focus:outline-none focus:ring-2 focus:ring-orange-500"
          style={{ backgroundColor: "#111827" }}
        >
          {allTypes.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {/* Film / Scan / Print */}
      <div className="space-y-2">
        {order.roll_summary.length > 0 && (
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Film</p>
            <div className="flex flex-wrap gap-2">
              {order.roll_summary.map((line, i) => <Pill key={i} label={line.label} qty={line.qty} colourMap={FILM_COLOURS} />)}
            </div>
          </div>
        )}
        {order.scan_summary.length > 0 && (
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Scanning</p>
            <div className="flex flex-wrap gap-2">
              {order.scan_summary.map((line, i) => <Pill key={i} label={line.label} qty={line.qty} colourMap={SCAN_COLOURS} />)}
            </div>
          </div>
        )}
        {order.print_summary.length > 0 && (
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Prints</p>
            <div className="flex flex-wrap gap-2">
              {order.print_summary.map((line, i) => (
                <Pill key={i} label={line.label} qty={line.qty} colourMap={{ [line.label]: "bg-pink-900 text-pink-200" }} />
              ))}
            </div>
          </div>
        )}
      </div>

      {devRollCount > 0 && (
        <p className="text-sm text-gray-400">
          <span className="font-semibold text-white">{devRollCount}</span> roll{devRollCount !== 1 ? "s" : ""} of film to scan in
        </p>
      )}

      {order.synced_at && (
        <p className="text-xs text-gray-600">
          Pronto data as of {new Date(order.synced_at).toLocaleTimeString("en-AU")}
        </p>
      )}

      <div className="flex gap-3 pt-1">
        <button
          onClick={onConfirm}
          className="flex-1 py-2.5 px-4 rounded-lg font-semibold text-white"
          style={{ backgroundColor: "#f97316" }}
        >
          {confirmLabel}
        </button>
        <button
          onClick={onClear}
          className="px-4 py-2.5 text-gray-400 hover:text-white border border-gray-600 rounded-lg"
          style={{ backgroundColor: "#111827" }}
        >
          Clear
        </button>
      </div>
    </div>
  );
}
