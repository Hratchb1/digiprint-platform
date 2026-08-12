// src/pages/IntakePage.tsx
import React, { useState, useRef, useCallback, useEffect } from "react";
import { useProntoLookup } from "../hooks/useProntoLookup";
import { ProntoOrderSummary } from "../components/ProntoOrderSummary";
import { api } from "../lib/api";
import { statusLabel } from "../lib/status";
import { SERVICE_TYPES, toBackendServiceType } from "../lib/serviceTypes";

const TERRITORY_STORE_MAP: Record<string, string> = {
  BOND: "a90c273e-49ff-4733-b709-31066f2ec503",
  BRIS: "514d0eee-b807-45bd-96bd-eda630be1fba",
  CANN: "8a525dc4-c1c2-48a0-a315-c03082b63f3e",
  MELB: "f2635a53-93ca-499f-aad4-4eb5e7f9128c",
  MIRA: "ff8bdc2e-966b-4a49-80b2-af5030148095",
  PARR: "87ed3978-0d69-4acd-89f5-8e60dd121165",
};

// Named store list for the manual entry store selector
const STORE_OPTIONS = [
  { id: "a90c273e-49ff-4733-b709-31066f2ec503", name: "Bondi" },
  { id: "514d0eee-b807-45bd-96bd-eda630be1fba", name: "Brisbane" },
  { id: "8a525dc4-c1c2-48a0-a315-c03082b63f3e", name: "Cannington" },
  { id: "f2635a53-93ca-499f-aad4-4eb5e7f9128c", name: "Melbourne" },
  { id: "ff8bdc2e-966b-4a49-80b2-af5030148095", name: "Miranda" },
  { id: "87ed3978-0d69-4acd-89f5-8e60dd121165", name: "Parramatta" },
];

function getCurrentUserInfo(): { store_id: string | null; role: string } {
  try {
    const token = localStorage.getItem("token");
    if (!token) return { store_id: null, role: "" };
    const payload = JSON.parse(atob(token.split(".")[1]));
    return {
      store_id: payload.store_id || null,
      role: payload.role || "",
    };
  } catch {
    return { store_id: null, role: "" };
  }
}

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
  manual_entry?: boolean;
  rolls: { twin_check: string; service_type: string; status: string }[];
}

interface LastBooked {
  orderNum: string;
  customerName: string;
  rollCount: number;
  action: "new" | "added";
  manual?: boolean;
}

interface SessionEntry extends LastBooked {
  time: Date;
}

interface ManualOrderData {
  customer_name: string;
  customer_email: string;
  customer_phone: string;
  account: string;
  service_type: string;
  store_id: string;
}

type IntakeStep = "operator" | "lookup" | "manual" | "confirm" | "twins";
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
  const userInfo = getCurrentUserInfo();
  const isMasterAdmin = userInfo.role === "master_admin";

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

  // Running log of this session's bookings — newest first; the newest entry
  // doubles as the booking confirmation (PRD 6.6 session log panel).
  const [sessionLog, setSessionLog] = useState<SessionEntry[]>([]);

  const [existingOrder, setExistingOrder] = useState<ExistingOrderInfo | null>(null);
  const [dupAction, setDupAction] = useState<DupAction>(null);
  const [showDupModal, setShowDupModal] = useState(false);

  const [isManualEntry, setIsManualEntry] = useState(false);
  const [manualData, setManualData] = useState<ManualOrderData>({
    customer_name: "",
    customer_email: "",
    customer_phone: "",
    account: "",
    service_type: "Develop + Scan",
    store_id: userInfo.store_id || "",
  });
  const [manualErrors, setManualErrors] = useState<Record<string, string>>({});

  const [twinMode, setTwinMode] = useState<"single" | "range">("single");
  const [singleInput, setSingleInput] = useState("");
  const [singleError, setSingleError] = useState<string | null>(null);
  const [firstTwin, setFirstTwin] = useState("");
  const [lastTwin, setLastTwin] = useState("");
  const [rangeError, setRangeError] = useState<string | null>(null);

  // Re-entrancy guard for addTwins — see the comment on addTwins below.
  const addingTwinsRef = useRef(false);

  const operatorInputRef = useRef<HTMLInputElement>(null);
  const orderInputRef    = useRef<HTMLInputElement>(null);
  const singleTwinRef    = useRef<HTMLInputElement>(null);
  const firstTwinRef     = useRef<HTMLInputElement>(null);
  const lastTwinRef      = useRef<HTMLInputElement>(null);
  const customerNameRef  = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (step === "operator") setTimeout(() => operatorInputRef.current?.focus(), 50);
    if (step === "lookup")   setTimeout(() => orderInputRef.current?.focus(), 50);
    if (step === "manual")   setTimeout(() => customerNameRef.current?.focus(), 50);
    if (step === "twins")    setTimeout(() => {
      if (twinMode === "single") singleTwinRef.current?.focus();
      else firstTwinRef.current?.focus();
    }, 100);
  }, [step, twinMode]);

  useEffect(() => {
    if (order && step === "lookup") {
      setServiceType(order.inferred_service_type);
      const storeId = TERRITORY_STORE_MAP[order.territory];
      if (storeId) {
        api.get("/orders/check/order-number", {
          params: { order_number: order.sales_order_number, store_id: storeId }
        }).then(({ data }) => {
          // An inbound order with no rolls is the Pronto-synced twin of this
          // sale, not a duplicate booking — go straight to intake. The backend
          // promotes it to booked_in when the rolls are saved.
          const emptyInbound = data.exists
            && data.order?.status === "inbound"
            && (data.order?.rolls?.length ?? 0) === 0;
          if (data.exists && !emptyInbound) {
            setExistingOrder(data.order);
            setShowDupModal(true);
          }
          setStep("confirm");
        }).catch(() => setStep("confirm"));
      } else {
        setStep("confirm");
      }
    }
  }, [order]);

  const handleOperatorSubmit = () => {
    const val = operatorInput.trim().toUpperCase();
    if (!val) { setOperatorError("Please enter your initials."); return; }
    if (val.length > 5) { setOperatorError("Initials too long (max 5 characters)."); return; }
    sessionStorage.setItem("operator_initials", val);
    setOperatorInitials(val);
    setStep("lookup");
  };

  const handleInitialLookup = useCallback(async () => {
    if (!orderInput.trim()) return;
    setIsManualEntry(false);
    await lookup(orderInput.trim());
  }, [orderInput, lookup]);

  const handleEnterManually = useCallback(async () => {
    if (!orderInput.trim()) return;

    // Check for duplicate before going to manual form
    const storeId = userInfo.store_id || manualData.store_id;
    if (storeId) {
      try {
        const { data } = await api.get("/orders/check/order-number", {
          params: { order_number: orderInput.trim(), store_id: storeId }
        });
        const emptyInbound = data.exists
          && data.order?.status === "inbound"
          && (data.order?.rolls?.length ?? 0) === 0;
        if (data.exists && !emptyInbound) {
          setExistingOrder(data.order);
          setShowDupModal(true);
        }
      } catch { /* proceed */ }
    }

    setIsManualEntry(true);
    setManualData(prev => ({
      ...prev,
      store_id: userInfo.store_id || prev.store_id || "",
      service_type: "Develop + Scan",
    }));
    setStep("manual");
  }, [orderInput, userInfo.store_id, manualData.store_id]);

  const handleManualConfirm = () => {
    const errors: Record<string, string> = {};
    if (!manualData.customer_name.trim()) {
      errors.customer_name = "Customer name is required";
    }
    // store_id required only if master_admin (staff always have one from JWT)
    if (isMasterAdmin && !manualData.store_id) {
      errors.store_id = "Please select a store";
    }
    if (Object.keys(errors).length > 0) {
      setManualErrors(errors);
      return;
    }
    setManualErrors({});
    setStep("twins");
  };

  const handleDupChoice = (action: "add" | "new" | "cancel") => {
    setShowDupModal(false);
    if (action === "cancel") { handleClear(); return; }
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
    setIsManualEntry(false);
    setManualData({
      customer_name: "",
      customer_email: "",
      customer_phone: "",
      account: "",
      service_type: "Develop + Scan",
      store_id: userInfo.store_id || "",
    });
    setManualErrors({});
    setStep("lookup");
  };

  const logBooking = (entry: LastBooked) =>
    setSessionLog(prev => [{ ...entry, time: new Date() }, ...prev]);

  // Rapid-entry reset: straight back to a fresh, focused order-number input
  // (the step change re-triggers the focus effect) — barcode-scanner cadence.
  const resetForNext = () => {
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
    setIsManualEntry(false);
    setManualData({
      customer_name: "",
      customer_email: "",
      customer_phone: "",
      account: "",
      service_type: "Develop + Scan",
      store_id: userInfo.store_id || "",
    });
    setManualErrors({});
    setStep("lookup");
  };

  const addTwins = useCallback(async (twinList: string[]) => {
    // Re-entrancy guard: barcode scanners commonly send a CR+LF Enter
    // suffix, which fires the input's onKeyDown Enter handler twice in
    // quick succession for one physical scan. Without this guard, both
    // calls read the same pre-append `twins` snapshot, both pass the
    // "not already added this session" check below, and both append —
    // rendering the same twin as two pills. A fast double-click on the
    // Add button hits the same path. Only one addTwins call is allowed
    // to be in flight at a time; the rest of the function is unchanged.
    if (addingTwinsRef.current) return;
    addingTwinsRef.current = true;
    try {
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
        const storeId = isManualEntry
          ? manualData.store_id
          : order?.territory ? TERRITORY_STORE_MAP[order.territory] : undefined;
        const { data } = await api.post("/rolls/check-twins", { twins: twinList, store_id: storeId });
        storeDups = data.duplicates || [];
      } catch { /* endpoint may not exist */ }

      const entries: TwinEntry[] = twinList.map((twin) => ({
        twin,
        status: storeDups.includes(twin) ? "duplicate" : "ok",
        message: storeDups.includes(twin) ? "Already in use at this store" : undefined,
      }));
      setTwins((prev) => [...prev, ...entries]);
    } finally {
      addingTwinsRef.current = false;
    }
  }, [twins, order, twinMode, isManualEntry, manualData.store_id]);

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

  const handleSave = useCallback(async () => {
    const validTwins = twins.filter((t) => t.status === "ok");
    if (validTwins.length === 0) { setSaveError("No valid twin checks to save."); return; }

    setSaving(true);
    setSaveError(null);

    try {
      if (isManualEntry) {
        const storeId = manualData.store_id || userInfo.store_id;
        if (!storeId) { setSaveError("No store selected."); setSaving(false); return; }

        const backendServiceType = toBackendServiceType(manualData.service_type);
        if (!backendServiceType) {
          setSaveError(`Unrecognised service type '${manualData.service_type}' — cannot book. Check the service-type list.`);
          setSaving(false);
          return;
        }
        const rollsPayload = validTwins.map((t) => ({
          twin_check: t.twin,
          service_type: backendServiceType,
        }));

        if (dupAction === "add" && existingOrder) {
          await api.post(`/orders/${existingOrder.id}/add-rolls`, {
            rolls: rollsPayload,
            operator_initials: operatorInitials || null,
          });
          logBooking({
            orderNum: orderInput.trim(),
            customerName: manualData.customer_name,
            rollCount: validTwins.length,
            action: "added",
            manual: true,
          });
        } else {
          const orderNumber = dupAction === "new"
            ? `${orderInput.trim()}-B`
            : orderInput.trim();

          await api.post("/orders", {
            order_number:      orderNumber,
            store_id:          storeId,
            customer_name:     manualData.customer_name,
            customer_email:    manualData.customer_email || null,
            customer_phone:    manualData.customer_phone || null,
            account:           manualData.account || null,
            operator_initials: operatorInitials || null,
            manual_entry:      true,
            rolls:             rollsPayload,
          });
          logBooking({
            orderNum: orderNumber,
            customerName: manualData.customer_name,
            rollCount: validTwins.length,
            action: "new",
            manual: true,
          });
        }
      } else {
        if (!order) return;
        const storeId = TERRITORY_STORE_MAP[order.territory];
        if (!storeId) { setSaveError(`Unknown store territory: ${order.territory}`); return; }

        const backendServiceType = toBackendServiceType(serviceType);
        if (!backendServiceType) {
          setSaveError(`Unrecognised service type '${serviceType}' — cannot book. Check the service-type list.`);
          setSaving(false);
          return;
        }
        const rollsPayload = validTwins.map((t) => ({
          twin_check: t.twin,
          service_type: backendServiceType,
        }));

        if (dupAction === "add" && existingOrder) {
          await api.post(`/orders/${existingOrder.id}/add-rolls`, {
            rolls: rollsPayload,
            operator_initials: operatorInitials || null,
          });
          logBooking({
            orderNum: order.sales_order_number,
            customerName: order.customer_name,
            rollCount: validTwins.length,
            action: "added",
          });
        } else {
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
            manual_entry:      false,
            rolls:             rollsPayload,
          });
          logBooking({
            orderNum: orderNumber,
            customerName: order.customer_name,
            rollCount: validTwins.length,
            action: "new",
          });
        }
      }
      resetForNext();
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      setSaveError(typeof detail === "string" ? detail : JSON.stringify(detail) || "Failed to save order.");
    } finally {
      setSaving(false);
    }
  }, [order, twins, serviceType, operatorInitials, dupAction, existingOrder, isManualEntry, manualData, orderInput, userInfo.store_id]);

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
      <div className="h-full flex items-center justify-center px-4">
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
              className="w-full rounded-lg px-3 py-2.5 text-sm text-white placeholder-gray-500 border border-[#2a2a2a] focus:outline-none focus:ring-2 focus:ring-[#ff6600] font-mono tracking-widest uppercase"
              style={{ backgroundColor: "#111111" }}
            />
            {operatorError && <p className="text-sm text-red-400">{operatorError}</p>}
          </div>
          <button onClick={handleOperatorSubmit} className="w-full py-3 rounded-lg font-semibold text-white" style={{ backgroundColor: "#ff6600" }}>
            Start intake
          </button>
        </div>
      </div>
    );
  }

  // ── Main intake — flow left, session log right, one viewport ──
  return (
    <div className="h-full flex overflow-hidden">
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-lg mx-auto px-4 py-5 space-y-4">

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
              {existingOrder.manual_entry && (
                <span className="inline-block mb-1 px-2 py-0.5 rounded text-xs font-medium text-orange-300 border border-orange-500/30" style={{ backgroundColor: "#431a00" }}>
                  Was entered manually
                </span>
              )}
              <p className="text-sm text-gray-300 mt-1">
                <span className="font-medium text-white">{existingOrder.customer_name}</span> — booked {new Date(existingOrder.created_at).toLocaleString("en-AU", { dateStyle: "short", timeStyle: "short" })}
                {existingOrder.operator ? ` by ${existingOrder.operator}` : ""}
              </p>
              <p className="text-sm text-gray-400 mt-0.5">
                {existingOrder.rolls?.length || 0} roll{existingOrder.rolls?.length !== 1 ? "s" : ""} — Status: {statusLabel(existingOrder.status)}
              </p>
            </div>
          </div>
          <p className="text-sm text-gray-300 font-medium">What do you want to do?</p>
          <div className="space-y-2">
            <button onClick={() => handleDupChoice("add")} className="w-full py-2.5 px-4 rounded-lg text-sm font-semibold text-white text-left" style={{ backgroundColor: "#2a2a2a" }}>
              ➕ Add more rolls — attach new twins to this order
            </button>
            <button onClick={() => handleDupChoice("new")} className="w-full py-2.5 px-4 rounded-lg text-sm font-semibold text-white text-left" style={{ backgroundColor: "#2a2a2a" }}>
              📋 New booking — create separate booking as {orderInput.trim()}-B
            </button>
            <button onClick={() => handleDupChoice("cancel")} className="w-full py-2.5 px-4 rounded-lg text-sm font-medium text-gray-400 text-left border border-[#222222]" style={{ backgroundColor: "#0f0f0f" }}>
              ✕ Cancel — go back
            </button>
          </div>
        </div>
      )}

      {/* Order number input */}
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
              className="flex-1 rounded-lg px-3 py-2.5 text-sm text-white placeholder-gray-500 border border-[#2a2a2a] focus:outline-none focus:ring-2 focus:ring-[#ff6600] disabled:opacity-50"
              style={{ backgroundColor: "#111111" }}
            />
            {step === "lookup" && (
              <button
                onClick={handleInitialLookup}
                disabled={lookupLoading || !orderInput.trim()}
                className="px-4 py-2.5 rounded-lg text-sm font-semibold text-white disabled:opacity-40"
                style={{ backgroundColor: "#ff6600" }}
              >
                {lookupLoading ? "Looking up..." : "Look up"}
              </button>
            )}
            {step !== "lookup" && (
              <button onClick={handleClear} className="px-4 py-2.5 rounded-lg text-sm font-medium text-gray-300 border border-[#2a2a2a]" style={{ backgroundColor: "#111111" }}>
                Change
              </button>
            )}
          </div>

          {/* Not found — offer manual entry */}
          {lookupError && step === "lookup" && (
            <div className="rounded-lg border border-[#222222] p-4 space-y-3" style={{ backgroundColor: "#0f0f0f" }}>
              <p className="text-sm text-red-400">{lookupError}</p>
              <p className="text-xs text-gray-500">
                Order not found in Pronto. If the system is unavailable, you can enter the order manually.
              </p>
              <button
                onClick={handleEnterManually}
                disabled={!orderInput.trim()}
                className="w-full py-2.5 px-4 rounded-lg text-sm font-semibold text-white disabled:opacity-40 border border-orange-500/40"
                style={{ backgroundColor: "#431a00" }}
              >
                ✏️ Enter manually
              </button>
            </div>
          )}
        </div>
      )}

      {/* Manual entry form */}
      {step === "manual" && !showDupModal && (
        <div className="rounded-xl border border-orange-500/20 p-4 space-y-3" style={{ backgroundColor: "#1a1200" }}>
          <div className="flex items-center gap-2">
            <span className="text-orange-400 text-sm">✏️</span>
            <p className="text-orange-400 text-sm font-semibold">Manual entry — order {orderInput.trim()}</p>
          </div>
          <p className="text-xs text-gray-500">
            This order will be flagged as manually entered. When Pronto syncs, you'll be notified if the order already exists.
          </p>

          {/* Store selector — only shown for master_admin */}
          {isMasterAdmin && (
            <div className="space-y-1">
              <label className="block text-xs font-medium text-gray-400">Store <span className="text-red-400">*</span></label>
              <select
                value={manualData.store_id}
                onChange={(e) => setManualData(prev => ({ ...prev, store_id: e.target.value }))}
                className="w-full rounded-lg px-3 py-2 text-sm text-white border border-[#2a2a2a] focus:outline-none focus:ring-2 focus:ring-[#ff6600]"
                style={{ backgroundColor: "#111111" }}
              >
                <option value="">Select a store…</option>
                {STORE_OPTIONS.map(s => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
              {manualErrors.store_id && <p className="text-xs text-red-400">{manualErrors.store_id}</p>}
            </div>
          )}

          {/* Customer name */}
          <div className="space-y-1">
            <label className="block text-xs font-medium text-gray-400">Customer name <span className="text-red-400">*</span></label>
            <input
              ref={customerNameRef}
              type="text"
              value={manualData.customer_name}
              onChange={(e) => setManualData(prev => ({ ...prev, customer_name: e.target.value }))}
              onKeyDown={(e) => e.key === "Enter" && handleManualConfirm()}
              placeholder="e.g. John Smith"
              className="w-full rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 border border-[#2a2a2a] focus:outline-none focus:ring-2 focus:ring-[#ff6600]"
              style={{ backgroundColor: "#111111" }}
            />
            {manualErrors.customer_name && <p className="text-xs text-red-400">{manualErrors.customer_name}</p>}
          </div>

          {/* Email */}
          <div className="space-y-1">
            <label className="block text-xs font-medium text-gray-400">Email <span className="text-gray-600">(optional)</span></label>
            <input
              type="email"
              value={manualData.customer_email}
              onChange={(e) => setManualData(prev => ({ ...prev, customer_email: e.target.value }))}
              placeholder="e.g. john@email.com"
              className="w-full rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 border border-[#2a2a2a] focus:outline-none focus:ring-2 focus:ring-[#ff6600]"
              style={{ backgroundColor: "#111111" }}
            />
          </div>

          {/* Phone */}
          <div className="space-y-1">
            <label className="block text-xs font-medium text-gray-400">Phone <span className="text-gray-600">(optional)</span></label>
            <input
              type="tel"
              value={manualData.customer_phone}
              onChange={(e) => setManualData(prev => ({ ...prev, customer_phone: e.target.value }))}
              placeholder="e.g. 0412 345 678"
              className="w-full rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 border border-[#2a2a2a] focus:outline-none focus:ring-2 focus:ring-[#ff6600]"
              style={{ backgroundColor: "#111111" }}
            />
          </div>

          {/* Account */}
          <div className="space-y-1">
            <label className="block text-xs font-medium text-gray-400">Account number <span className="text-gray-600">(optional)</span></label>
            <input
              type="text"
              value={manualData.account}
              onChange={(e) => setManualData(prev => ({ ...prev, account: e.target.value }))}
              placeholder="e.g. 1429084"
              className="w-full rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 border border-[#2a2a2a] focus:outline-none focus:ring-2 focus:ring-[#ff6600]"
              style={{ backgroundColor: "#111111" }}
            />
          </div>

          {/* Service type */}
          <div className="space-y-1">
            <label className="block text-xs font-medium text-gray-400">Service type</label>
            <select
              value={manualData.service_type}
              onChange={(e) => setManualData(prev => ({ ...prev, service_type: e.target.value }))}
              className="w-full rounded-lg px-3 py-2 text-sm text-white border border-[#2a2a2a] focus:outline-none focus:ring-2 focus:ring-[#ff6600]"
              style={{ backgroundColor: "#111111" }}
            >
              {SERVICE_TYPES.map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>

          <div className="flex gap-2 pt-1">
            <button
              onClick={handleManualConfirm}
              className="flex-1 py-2.5 rounded-lg text-sm font-semibold text-white"
              style={{ backgroundColor: "#ff6600" }}
            >
              Confirm & enter twins
            </button>
            <button
              onClick={handleClear}
              className="px-4 py-2.5 rounded-lg text-sm font-medium text-gray-400 border border-[#222222]"
              style={{ backgroundColor: "#0f0f0f" }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Pronto order summary */}
      {order && (step === "confirm" || step === "twins") && !showDupModal && !isManualEntry && (
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

      {/* Manual order summary (confirmed) */}
      {isManualEntry && step === "twins" && !showDupModal && (
        <div className="rounded-xl border border-orange-500/20 p-4" style={{ backgroundColor: "#1a1200" }}>
          <div className="flex items-center justify-between mb-2">
            <p className="text-orange-400 text-xs font-semibold uppercase tracking-wide">Manual entry</p>
            <button onClick={() => setStep("manual")} className="text-xs text-gray-500 hover:text-gray-300">Edit</button>
          </div>
          <p className="text-white font-medium">{manualData.customer_name}</p>
          {manualData.customer_email && <p className="text-gray-400 text-sm">{manualData.customer_email}</p>}
          {manualData.customer_phone && <p className="text-gray-400 text-sm">{manualData.customer_phone}</p>}
          <p className="text-gray-500 text-xs mt-1">{manualData.service_type}</p>
          {isMasterAdmin && manualData.store_id && (
            <p className="text-gray-500 text-xs">{STORE_OPTIONS.find(s => s.id === manualData.store_id)?.name}</p>
          )}
        </div>
      )}

      {/* Twin entry */}
      {step === "twins" && !showDupModal && (
        <div className="space-y-4">
          <div className="flex rounded-lg overflow-hidden border border-[#2a2a2a]">
            <button
              onClick={() => { setTwinMode("single"); setSingleError(null); }}
              className={`flex-1 py-2 text-sm font-medium transition-colors ${twinMode === "single" ? "text-white" : "text-gray-400"}`}
              style={{ backgroundColor: twinMode === "single" ? "#2a2a2a" : "#111111" }}
            >
              Twin checks
            </button>
            <button
              onClick={() => { setTwinMode("range"); setRangeError(null); }}
              className={`flex-1 py-2 text-sm font-medium transition-colors ${twinMode === "range" ? "text-white" : "text-gray-400"}`}
              style={{ backgroundColor: twinMode === "range" ? "#2a2a2a" : "#111111" }}
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
                  className="flex-1 rounded-lg px-3 py-2.5 text-sm text-white placeholder-gray-500 border border-[#2a2a2a] focus:outline-none focus:ring-2 focus:ring-[#ff6600] font-mono"
                  style={{ backgroundColor: "#111111" }}
                />
                <button onClick={handleSingleSubmit} disabled={saving} className="px-4 py-2.5 rounded-lg text-sm font-semibold text-white disabled:opacity-40" style={{ backgroundColor: "#2a2a2a" }}>Add</button>
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
                  className="flex-1 rounded-lg px-3 py-2.5 text-sm text-white placeholder-gray-500 border border-[#2a2a2a] focus:outline-none focus:ring-2 focus:ring-[#ff6600] font-mono"
                  style={{ backgroundColor: "#111111" }}
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
                  className="flex-1 rounded-lg px-3 py-2.5 text-sm text-white placeholder-gray-500 border border-[#2a2a2a] focus:outline-none focus:ring-2 focus:ring-[#ff6600] font-mono"
                  style={{ backgroundColor: "#111111" }}
                />
                <button onClick={handleRangeSubmit} disabled={saving} className="px-4 py-2.5 rounded-lg text-sm font-semibold text-white disabled:opacity-40 whitespace-nowrap" style={{ backgroundColor: "#2a2a2a" }}>Add range</button>
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
              <div className="flex flex-wrap gap-2 max-h-24 overflow-y-auto">
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
                style={{ backgroundColor: "#ff6600" }}
              >
                {saving ? "Saving..." : `${dupAction === "add" ? "Add" : "Book"} ${validTwinCount} roll${validTwinCount !== 1 ? "s" : ""}`}
              </button>
            </div>
          )}
        </div>
      )}
        </div>
      </div>

      {/* Session log panel — this session's bookings, newest first */}
      <aside className="hidden md:flex w-80 flex-shrink-0 flex-col border-l border-[#1e1e1e]" style={{ backgroundColor: "#0f0f0f" }}>
        <div className="px-4 py-4 border-b border-[#1e1e1e] flex items-center justify-between">
          <p className="text-white text-sm font-semibold">Session Log</p>
          <span className="text-gray-500 text-xs">
            {sessionLog.length} booking{sessionLog.length !== 1 ? "s" : ""}
          </span>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {sessionLog.length === 0 ? (
            <p className="text-gray-600 text-xs px-1 pt-2">
              Orders you book this session will appear here.
            </p>
          ) : (
            sessionLog.map((entry, i) => (
              <div
                key={`${entry.orderNum}-${entry.time.getTime()}`}
                className={`rounded-lg border p-3 ${
                  i === 0
                    ? "border-green-500/40 bg-green-500/5"
                    : "border-[#222222]"
                }`}
                style={i === 0 ? undefined : { backgroundColor: "#111111" }}
              >
                {i === 0 && (
                  <p className="text-green-400 text-[10px] uppercase tracking-widest font-semibold mb-1">
                    {entry.action === "added" ? "Rolls added" : "Booked"} ✓
                  </p>
                )}
                <div className="flex items-center justify-between gap-2">
                  <p className="text-white text-sm font-mono font-medium truncate">#{entry.orderNum}</p>
                  <p className="text-gray-600 text-[11px] flex-shrink-0">
                    {entry.time.toLocaleTimeString("en-AU", { hour: "2-digit", minute: "2-digit" })}
                  </p>
                </div>
                <p className="text-gray-400 text-xs truncate">{entry.customerName}</p>
                <p className="text-gray-600 text-[11px] mt-0.5">
                  {entry.rollCount} roll{entry.rollCount !== 1 ? "s" : ""}
                  {" · "}{entry.action === "added" ? "added to existing" : "new booking"}
                  {entry.manual && <span className="text-orange-400"> · manual</span>}
                </p>
              </div>
            ))
          )}
        </div>
      </aside>
    </div>
  );
}
