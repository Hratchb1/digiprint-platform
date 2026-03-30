// src/pages/IntakePage.tsx
import React, { useState, useRef, useCallback, useEffect } from "react";
import { useProntoLookup } from "../hooks/useProntoLookup";
import { ProntoOrderSummary } from "../components/ProntoOrderSummary";
import { api } from "../lib/api";

const TERRITORY_STORE_MAP: Record<string, string> = {
  BOND: "a90c273e-49ff-4733-b709-31066f2ec503",
  BRIS: "514d0eee-b807-45bd-96bd-eda630be1fba",
  CANN: "8a525dc4-c1c2-48a0-a315-c03082b63f3e",
  MELB: "f2635a53-93ca-499f-aad4-4eb5e7f9128c",
  MIRA: "ff8bdc2e-966b-4a49-80b2-af5030148095",
  PARR: "87ed3978-0d69-4acd-89f5-8e60dd121165",
};

const SERVICE_TYPE_MAP: Record<string, string> = {
  "Develop only":           "Dev only",
  "Develop + Scan":         "Dev+Scan",
  "Develop + Scan + Print": "Dev+Scan+Print",
  "Scan only":              "Scan only",
  "Print only":             "Print only",
};

interface TwinEntry {
  twin: string;
  status: "ok" | "duplicate";
  message?: string;
}

interface ExistingOrderInfo {
  id: string;
  order_number: string;
  customer_name: string;
  status: string;
  created_at: string;
  operator: string;
  rolls: { twin_check: string; service_type: string; status: string }[];
}

interface LastBooked {
  orderNum: string;
  customerName: string;
  rollCount: number;
  action: "new" | "added";
}

type IntakeStep = "operator" | "lookup" | "confirm" | "twins" | "done";
type DupAction = "add" | "new" | null;

// ── Validation ───────────────────────────────────────────────
function validateSingleFieldInput(val: string): string | null {
  const v = val.trim();
  const rangeMatch = v.match(/^(\d+)-(\d+)$/);
  if (rangeMatch) {
    const f = rangeMatch[1]; const l = rangeMatch[2];
    if (f.length !== 4) return "Range start must be exactly 4 digits (e.g. 0042-0051).";
    if (l.length !== 4) return "Range end must be exactly 4 digits (e.g. 0042-0051).";
    const a = parseInt(f, 10); const b = parseInt(l, 10);
    if (b < a) return `Wrap-around not allowed (${f} → ${l}).`;
    if (a === 0) return "Twin checks cannot start at 0000.";
    if (b - a + 1 > 200) return `Range too large (${b - a + 1} rolls). Max 200.`;
    return null;
  }
  if (!/^\d+$/.test(v)) return "Must be digits only.";
  if (v.length !== 4) return "Twin check must be exactly 4 digits (e.g. 0042).";
  if (parseInt(v, 10) === 0) return "Twin check cannot be 0000.";
  return null;
}

function validateRangeInputs(first: string, last: string): string | null {
  const f = first.trim(); const l = last.trim();
  if (f.length !== 4 || !/^\d{4}$/.test(f)) return "First twin must be exactly 4 digits.";
  if (l.length !== 4 || !/^\d{4}$/.test(l)) return "Last twin must be exactly 4 digits.";
  const a = parseInt(f, 10); const b = parseInt(l, 10);
  if (a === 0) return "Twin checks cannot start at 0000.";
  if (b < a) return `Wrap-around not allowed (${f} → ${l}).`;
  if (b - a + 1 > 200) return `Range too large (${b - a + 1} rolls). Max 200.`;
  return null;
}

function parseSingleFieldInput(val: string): string[] {
  const v = val.trim();
  const rangeMatch = v.match(/^(\d{4})-(\d{4})$/);
  if (rangeMatch) {
    const a = parseInt(rangeMatch[1], 10); const b = parseInt(rangeMatch[2], 10);
    const result: string[] = [];
    for (let i = a; i <= b; i++) result.push(String(i).padStart(4, "0"));
    return result;
  }
  return [v];
}

function buildRange(first: string, last: string): string[] {
  const a = parseInt(first.trim(), 10); const b = parseInt(last.trim(), 10);
  const result: string[] = [];
  for (let i = a; i <= b; i++) result.push(String(i).padStart(4, "0"));
  return result;
}

export default function IntakePage() {
  const { lookup, order, loading: lookupLoading, error: lookupError, clear } = useProntoLookup();

  const [operatorInitials, setOperatorInitials] = useState<string>(
    () => sessionStorage.getItem("operator_initials") || ""
  );
  const [operatorInput, setOperatorInput] = useState("");
  const [operatorError, setOperatorError] = useState("");
  const [step, setStep] = useState<IntakeStep>(operatorInitials ? "lookup" : "operator");

  const [orderInput, setOrderInput] = useState("");
  const [serviceType, setServiceType] = useState("Develop + Scan");
  const [twins, setTwins] = useState<TwinEntry[]>([]);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Last booked banner
  const [lastBooked, setLastBooked] = useState<LastBooked | null>(null);

  // Duplicate order state
  const [existingOrder, setExistingOrder] = useState<ExistingOrderInfo | null>(null);
  const [dupAction, setDupAction] = useState<DupAction>(null);
  const [showDupModal, setShowDupModal] = useState(false);
  const [checkingDup, setCheckingDup] = useState(false);

  // Twin entry
  const [twinMode, setTwinMode] = useState<"single" | "range">("single");
  const [singleInput, setSingleInput] = useState("");
  const [singleError, setSingleError] = useState<string | null>(null);
  const [firstTwin, setFirstTwin] = useState("");
  const [lastTwin, setLastTwin] = useState("");
  const [rangeError, setRangeError] = useState<string | null>(null);

  const operatorInputRef = useRef<HTMLInputElement>(null);
  const orderInputRef    = useRef<HTMLInputElement>(null);
  const singleTwinRef    = useRef<HTMLInputElement>(null);
  const firstTwinRef     = useRef<HTMLInputElement>(null);
  const lastTwinRef      = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (step === "operator") setTimeout(() => operatorInputRef.current?.focus(), 50);
    if (step === "lookup")   setTimeout(() => orderInputRef.current?.focus(), 50);
    if (step === "twins")    setTimeout(() => {
      if (twinMode === "single") singleTwinRef.current?.focus();
      else firstTwinRef.current?.focus();
    }, 100);
  }, [step, twinMode]);

  useEffect(() => {
    if (order && step === "lookup") {
      setServiceType(order.inferred_service_type);
      setStep("confirm");
    }
  }, [order]);

  // ── Operator ─────────────────────────────────────────────
  const handleOperatorSubmit = () => {
    const val = operatorInput.trim().toUpperCase();
    if (!val) { setOperatorError("Please enter your initials."); return; }
    if (val.length > 5) { setOperatorError("Initials too long (max 5 characters)."); return; }
    sessionStorage.setItem("operator_initials", val);
    setOperatorInitials(val);
    setStep("lookup");
  };

  // ── Order lookup with duplicate check ────────────────────
  const handleOrderLookup = useCallback(async () => {
    if (!orderInput.trim() || !order) return;

    const storeId = TERRITORY_STORE_MAP[order.territory];
    if (!storeId) return;

    setCheckingDup(true);
    try {
      const { data } = await api.get("/orders/check/order-number", {
        params: { order_number: orderInput.trim(), store_id: storeId }
      });
      if (data.exists) {
        setExistingOrder(data.order);
        setShowDupModal(true);
      } else {
        setStep("twins");
      }
    } catch {
      // If check fails, proceed normally
      setStep("twins");
    } finally {
      setCheckingDup(false);
    }
  }, [orderInput, order]);

  // When Pronto lookup completes, then check for duplicates
  const handleInitialLookup = useCallback(async () => {
    if (!orderInput.trim()) return;
    await lookup(orderInput.trim());
  }, [orderInput, lookup]);

  // After order loads, check for duplicates then go to confirm
  useEffect(() => {
    if (order && step === "lookup") {
      setServiceType(order.inferred_service_type);
      // Check for duplicate order at store level
      const storeId = TERRITORY_STORE_MAP[order.territory];
      if (storeId) {
        api.get("/orders/check/order-number", {
          params: { order_number: order.sales_order_number, store_id: storeId }
        }).then(({ data }) => {
          if (data.exists) {
            setExistingOrder(data.order);
            setShowDupModal(true);
            setStep("confirm");
          } else {
            setStep("confirm");
          }
        }).catch(() => setStep("confirm"));
      } else {
        setStep("confirm");
      }
    }
  }, [order]);

  const handleDupChoice = (action: "add" | "new" | "cancel") => {
    setShowDupModal(false);
    if (action === "cancel") {
      handleClear();
      return;
    }
    setDupAction(action);
    setStep("twins");
  };

  const handleClear = () => {
    clear();
    setOrderInput("");
    setTwins([]);
    setSingleInput("");
    setSingleError(null);
    setFirstTwin("");
    setLastTwin("");
    setRangeError(null);
    setSaveError(null);
    setServiceType("Develop + Scan");
    setExistingOrder(null);
    setDupAction(null);
    setShowDupModal(false);
    setStep("lookup");
  };

  // ── Add twins ─────────────────────────────────────────────
  const addTwins = useCallback(async (twinList: string[]) => {
    const existingInSession = new Set(twins.map((t) => t.twin));
    const sessionDups = twinList.filter((t) => existingInSession.has(t));
    if (sessionDups.length > 0) {
      const msg = `Already added this session: ${sessionDups.join(", ")}`;
      if (twinMode === "single") setSingleError(msg);
      else setRangeError(msg);
      return;
    }

    let storeDups: string[] = [];
    try {
      const storeId = order?.territory ? TERRITORY_STORE_MAP[order.territory] : undefined;
      const { data } = await api.post("/rolls/check-twins", { twins: twinList, store_id: storeId });
      storeDups = data.duplicates || [];
    } catch { /* endpoint not built yet */ }

    const entries: TwinEntry[] = twinList.map((twin) => ({
      twin,
      status: storeDups.includes(twin) ? "duplicate" : "ok",
      message: storeDups.includes(twin) ? "Already in use at this store" : undefined,
    }));
    setTwins((prev) => [...prev, ...entries]);
  }, [twins, order, twinMode]);

  const handleSingleSubmit = useCallback(async () => {
    const raw = singleInput.trim();
    if (!raw && twins.length > 0) { handleSave(); return; }
    if (!raw) return;
    setSingleError(null);
    const err = validateSingleFieldInput(raw);
    if (err) { setSingleError(err); return; }
    await addTwins(parseSingleFieldInput(raw));
    setSingleInput("");
    singleTwinRef.current?.focus();
  }, [singleInput, twins, addTwins]);

  const handleRangeSubmit = useCallback(async () => {
    setRangeError(null);
    const err = validateRangeInputs(firstTwin, lastTwin);
    if (err) { setRangeError(err); return; }
    await addTwins(buildRange(firstTwin, lastTwin));
    setFirstTwin("");
    setLastTwin("");
    firstTwinRef.current?.focus();
  }, [firstTwin, lastTwin, addTwins]);

  // ── Save order ────────────────────────────────────────────
  const handleSave = useCallback(async () => {
    if (!order) return;
    const validTwins = twins.filter((t) => t.status === "ok");
    if (validTwins.length === 0) { setSaveError("No valid twin checks to save."); return; }

    const storeId = TERRITORY_STORE_MAP[order.territory];
    if (!storeId) { setSaveError(`Unknown store territory: ${order.territory}`); return; }

    const backendServiceType = SERVICE_TYPE_MAP[serviceType] || serviceType;
    const rollsPayload = validTwins.map((t) => ({ twin_check: t.twin, service_type: backendServiceType }));

    setSaving(true);
    setSaveError(null);

    try {
      if (dupAction === "add" && existingOrder) {
        // Add rolls to existing order
        await api.post(`/orders/${existingOrder.id}/add-rolls`, {
          rolls: rollsPayload,
          operator_initials: operatorInitials || null,
        });
        setLastBooked({
          orderNum: order.sales_order_number,
          customerName: order.customer_name,
          rollCount: validTwins.length,
          action: "added",
        });
      } else {
        // New order — with suffix if "new booking" on duplicate
        const orderNumber = dupAction === "new"
          ? `${order.sales_order_number}-B`
          : order.sales_order_number;

        await api.post("/orders", {
          order_number:      orderNumber,
          store_id:          storeId,
          customer_name:     order.customer_name,
          customer_email:    order.email_address || null,
          account:           order.pronto_account || null,
          operator_initials: operatorInitials || null,
          rolls:             rollsPayload,
        });
        setLastBooked({
          orderNum: orderNumber,
          customerName: order.customer_name,
          rollCount: validTwins.length,
          action: "new",
        });
      }
      setStep("done");
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      setSaveError(typeof detail === "string" ? detail : JSON.stringify(detail) || "Failed to save order.");
    } finally {
      setSaving(false);
    }
  }, [order, twins, serviceType, operatorInitials, dupAction, existingOrder]);

  const removeTwin = (twin: string) => setTwins((prev) => prev.filter((t) => t.twin !== twin));

  const validTwinCount = twins.filter((t) => t.status === "ok").length;
  const dupTwinCount   = twins.filter((t) => t.status === "duplicate").length;
  const rangePreviewCount =
    firstTwin.length === 4 && lastTwin.length === 4 &&
    /^\d{4}$/.test(firstTwin) && /^\d{4}$/.test(lastTwin) &&
    parseInt(lastTwin) >= parseInt(firstTwin)
      ? parseInt(lastTwin) - parseInt(firstTwin) + 1
      : null;

  // ── Operator prompt ───────────────────────────────────────
  if (step === "operator") {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <div className="w-full max-w-sm space-y-6">
          <div>
            <h1 className="text-2xl font-bold text-white">Film Intake</h1>
            <p className="text-gray-400 mt-1 text-sm">Enter your initials to start your session</p>
          </div>
          <div className="space-y-2">
            <label className="block text-sm font-medium text-gray-300">Your initials</label>
            <input
              ref={operatorInputRef}
              type="text"
              value={operatorInput}
              onChange={(e) => { setOperatorInput(e.target.value.toUpperCase()); setOperatorError(""); }}
              onKeyDown={(e) => e.key === "Enter" && handleOperatorSubmit()}
              placeholder="e.g. HB"
              maxLength={5}
              className="w-full rounded-lg px-3 py-2.5 text-sm text-white placeholder-gray-500 border border-gray-600 focus:outline-none focus:ring-2 focus:ring-orange-500 font-mono tracking-widest uppercase"
              style={{ backgroundColor: "#1f2937" }}
            />
            {operatorError && <p className="text-sm text-red-400">{operatorError}</p>}
          </div>
          <button onClick={handleOperatorSubmit} className="w-full py-3 rounded-lg font-semibold text-white" style={{ backgroundColor: "#f97316" }}>
            Start intake
          </button>
        </div>
      </div>
    );
  }

  // ── Done ──────────────────────────────────────────────────
  if (step === "done") {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <div className="w-full max-w-md text-center space-y-6">
          <div className="w-16 h-16 rounded-full bg-green-500 flex items-center justify-center mx-auto">
            <svg className="w-8 h-8 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <div>
            <h2 className="text-2xl font-bold text-white">
              {lastBooked?.action === "added" ? "Rolls added" : "Order booked"}
            </h2>
            <p className="text-gray-400 mt-1">
              {lastBooked?.customerName} — {lastBooked?.rollCount} roll{lastBooked?.rollCount !== 1 ? "s" : ""} checked in
            </p>
            <p className="text-gray-500 text-sm mt-1">#{lastBooked?.orderNum}</p>
            <p className="text-gray-600 text-xs mt-1">Operator: {operatorInitials}</p>
          </div>
          <button
            onClick={() => {
              clear();
              setOrderInput("");
              setTwins([]);
              setSingleInput("");
              setFirstTwin("");
              setLastTwin("");
              setSingleError(null);
              setRangeError(null);
              setSaveError(null);
              setServiceType("Develop + Scan");
              setExistingOrder(null);
              setDupAction(null);
              setStep("lookup");
            }}
            className="w-full py-3 px-6 rounded-lg font-semibold text-white"
            style={{ backgroundColor: "#f97316" }}
          >
            Next order
          </button>
        </div>
      </div>
    );
  }

  // ── Main intake ───────────────────────────────────────────
  return (
    <div className="max-w-lg mx-auto px-4 py-8 space-y-6">

      {/* Last booked banner */}
      {lastBooked && (
        <div className="rounded-lg px-4 py-3 flex items-center justify-between" style={{ backgroundColor: "#064e3b" }}>
          <div>
            <p className="text-xs text-green-400 uppercase tracking-wide">Last booked</p>
            <p className="text-sm text-white font-medium">
              #{lastBooked.orderNum} — {lastBooked.customerName}
            </p>
            <p className="text-xs text-green-400">
              {lastBooked.rollCount} roll{lastBooked.rollCount !== 1 ? "s" : ""} · {lastBooked.action === "added" ? "Added to existing" : "New order"}
            </p>
          </div>
          <button onClick={() => setLastBooked(null)} className="text-green-600 hover:text-green-400 text-lg">×</button>
        </div>
      )}

      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Film Intake</h1>
        <span className="text-sm text-gray-500">
          Operator: <span className="text-gray-300 font-mono">{operatorInitials}</span>
        </span>
      </div>

      {/* Duplicate order modal */}
      {showDupModal && existingOrder && (
        <div className="rounded-xl border border-amber-700 p-5 space-y-4" style={{ backgroundColor: "#1c1a0f" }}>
          <div className="flex items-start gap-3">
            <span className="text-amber-400 text-xl">⚠</span>
            <div>
              <p className="text-amber-400 font-semibold">Order already exists</p>
              <p className="text-sm text-gray-300 mt-1">
                <span className="font-medium text-white">{existingOrder.customer_name}</span> — booked {new Date(existingOrder.created_at).toLocaleString("en-AU", { dateStyle: "short", timeStyle: "short" })}
                {existingOrder.operator ? ` by ${existingOrder.operator}` : ""}
              </p>
              <p className="text-sm text-gray-400 mt-0.5">
                {existingOrder.rolls?.length || 0} roll{existingOrder.rolls?.length !== 1 ? "s" : ""} — Status: {existingOrder.status}
              </p>
            </div>
          </div>
          <p className="text-sm text-gray-300 font-medium">What do you want to do?</p>
          <div className="space-y-2">
            <button
              onClick={() => handleDupChoice("add")}
              className="w-full py-2.5 px-4 rounded-lg text-sm font-semibold text-white text-left"
              style={{ backgroundColor: "#374151" }}
            >
              ➕ Add more rolls — attach new twins to this order
            </button>
            <button
              onClick={() => handleDupChoice("new")}
              className="w-full py-2.5 px-4 rounded-lg text-sm font-semibold text-white text-left"
              style={{ backgroundColor: "#374151" }}
            >
              📋 New booking — create separate booking as {order?.sales_order_number}-B
            </button>
            <button
              onClick={() => handleDupChoice("cancel")}
              className="w-full py-2.5 px-4 rounded-lg text-sm font-medium text-gray-400 text-left border border-gray-700"
              style={{ backgroundColor: "#111827" }}
            >
              ✕ Cancel — go back
            </button>
          </div>
        </div>
      )}

      {/* Order number */}
      {!showDupModal && (
        <div className="space-y-2">
          <label className="block text-sm font-medium text-gray-300">Pronto order number</label>
          <div className="flex gap-2">
            <input
              ref={orderInputRef}
              type="text"
              value={orderInput}
              onChange={(e) => setOrderInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleInitialLookup()}
              placeholder="Scan or type order number"
              disabled={step !== "lookup"}
              className="flex-1 rounded-lg px-3 py-2.5 text-sm text-white placeholder-gray-500 border border-gray-600 focus:outline-none focus:ring-2 focus:ring-orange-500 disabled:opacity-50"
              style={{ backgroundColor: "#1f2937" }}
            />
            {step === "lookup" && (
              <button
                onClick={handleInitialLookup}
                disabled={lookupLoading || !orderInput.trim()}
                className="px-4 py-2.5 rounded-lg text-sm font-semibold text-white disabled:opacity-40"
                style={{ backgroundColor: "#f97316" }}
              >
                {lookupLoading ? "Looking up..." : "Look up"}
              </button>
            )}
            {step !== "lookup" && (
              <button
                onClick={handleClear}
                className="px-4 py-2.5 rounded-lg text-sm font-medium text-gray-300 border border-gray-600"
                style={{ backgroundColor: "#1f2937" }}
              >
                Change
              </button>
            )}
          </div>
          {lookupError && <p className="text-sm text-red-400">{lookupError}</p>}
        </div>
      )}

      {/* Order summary */}
      {order && (step === "confirm" || step === "twins") && !showDupModal && (
        <ProntoOrderSummary
          order={order}
          serviceType={serviceType}
          onServiceTypeChange={setServiceType}
          onConfirm={() => setStep("twins")}
          onClear={handleClear}
          dupAction={dupAction}
          existingOrderRollCount={existingOrder?.rolls?.length}
        />
      )}

      {/* Twin entry */}
      {step === "twins" && !showDupModal && (
        <div className="space-y-4">
          <div className="flex rounded-lg overflow-hidden border border-gray-600">
            <button
              onClick={() => { setTwinMode("single"); setSingleError(null); }}
              className={`flex-1 py-2 text-sm font-medium transition-colors ${twinMode === "single" ? "text-white" : "text-gray-400"}`}
              style={{ backgroundColor: twinMode === "single" ? "#374151" : "#1f2937" }}
            >
              Twin checks
            </button>
            <button
              onClick={() => { setTwinMode("range"); setRangeError(null); }}
              className={`flex-1 py-2 text-sm font-medium transition-colors ${twinMode === "range" ? "text-white" : "text-gray-400"}`}
              style={{ backgroundColor: twinMode === "range" ? "#374151" : "#1f2937" }}
            >
              Range
            </button>
          </div>

          {twinMode === "single" && (
            <div className="space-y-2">
              <label className="block text-sm font-medium text-gray-300">
                Twin check
                <span className="ml-2 text-gray-500 font-normal text-xs">4 digits (e.g. 0042) or dash range (e.g. 0042-0051)</span>
              </label>
              <div className="flex gap-2">
                <input
                  ref={singleTwinRef}
                  type="text"
                  value={singleInput}
                  onChange={(e) => { setSingleInput(e.target.value); setSingleError(null); }}
                  onKeyDown={(e) => e.key === "Enter" && handleSingleSubmit()}
                  placeholder="e.g. 0042 or 0042-0051"
                  maxLength={9}
                  className="flex-1 rounded-lg px-3 py-2.5 text-sm text-white placeholder-gray-500 border border-gray-600 focus:outline-none focus:ring-2 focus:ring-orange-500 font-mono"
                  style={{ backgroundColor: "#1f2937" }}
                />
                <button onClick={handleSingleSubmit} disabled={saving} className="px-4 py-2.5 rounded-lg text-sm font-semibold text-white disabled:opacity-40" style={{ backgroundColor: "#374151" }}>Add</button>
              </div>
              {singleError && <p className="text-sm text-red-400">{singleError}</p>}
              {twins.length > 0 && !singleInput && (
                <p className="text-xs text-gray-500">Press Enter on empty field to book {validTwinCount} roll{validTwinCount !== 1 ? "s" : ""}</p>
              )}
            </div>
          )}

          {twinMode === "range" && (
            <div className="space-y-2">
              <label className="block text-sm font-medium text-gray-300">
                Twin check range
                <span className="ml-2 text-gray-500 font-normal text-xs">Both must be exactly 4 digits</span>
              </label>
              <div className="flex gap-2 items-center">
                <input
                  ref={firstTwinRef}
                  type="text"
                  value={firstTwin}
                  onChange={(e) => { setFirstTwin(e.target.value); setRangeError(null); }}
                  onKeyDown={(e) => e.key === "Enter" && lastTwinRef.current?.focus()}
                  placeholder="First (e.g. 0042)"
                  maxLength={4}
                  className="flex-1 rounded-lg px-3 py-2.5 text-sm text-white placeholder-gray-500 border border-gray-600 focus:outline-none focus:ring-2 focus:ring-orange-500 font-mono"
                  style={{ backgroundColor: "#1f2937" }}
                />
                <span className="text-gray-500 text-sm px-1">→</span>
                <input
                  ref={lastTwinRef}
                  type="text"
                  value={lastTwin}
                  onChange={(e) => { setLastTwin(e.target.value); setRangeError(null); }}
                  onKeyDown={(e) => e.key === "Enter" && handleRangeSubmit()}
                  placeholder="Last (e.g. 0051)"
                  maxLength={4}
                  className="flex-1 rounded-lg px-3 py-2.5 text-sm text-white placeholder-gray-500 border border-gray-600 focus:outline-none focus:ring-2 focus:ring-orange-500 font-mono"
                  style={{ backgroundColor: "#1f2937" }}
                />
                <button onClick={handleRangeSubmit} disabled={saving} className="px-4 py-2.5 rounded-lg text-sm font-semibold text-white disabled:opacity-40 whitespace-nowrap" style={{ backgroundColor: "#374151" }}>Add range</button>
              </div>
              {rangeError && <p className="text-sm text-red-400">{rangeError}</p>}
              {rangePreviewCount && !rangeError && (
                <p className="text-xs text-gray-500">{rangePreviewCount} rolls in range</p>
              )}
            </div>
          )}

          {twins.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-3">
                <p className="text-xs text-gray-500 uppercase tracking-wide">{validTwinCount} valid</p>
                {dupTwinCount > 0 && <p className="text-xs text-red-400 uppercase tracking-wide">{dupTwinCount} duplicate{dupTwinCount !== 1 ? "s" : ""}</p>}
              </div>
              <div className="flex flex-wrap gap-2">
                {twins.map((entry) => (
                  <div
                    key={entry.twin}
                    className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-mono font-medium ${entry.status === "ok" ? "bg-gray-700 text-white" : "bg-red-900 text-red-300 border border-red-700"}`}
                  >
                    {entry.twin}
                    {entry.status === "duplicate" && <span className="text-xs text-red-400">dup</span>}
                    <button onClick={() => removeTwin(entry.twin)} className="text-gray-400 hover:text-white ml-0.5">×</button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {twins.length > 0 && (
            <div className="pt-2 space-y-2">
              {saveError && <p className="text-sm text-red-400">{saveError}</p>}
              <button
                onClick={handleSave}
                disabled={saving || validTwinCount === 0}
                className="w-full py-3 rounded-lg font-semibold text-white disabled:opacity-40"
                style={{ backgroundColor: "#f97316" }}
              >
                {saving ? "Saving..." : `${dupAction === "add" ? "Add" : "Book"} ${validTwinCount} roll${validTwinCount !== 1 ? "s" : ""}`}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
