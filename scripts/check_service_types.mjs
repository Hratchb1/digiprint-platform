#!/usr/bin/env node
// scripts/check_service_types.mjs
//
// Drift guard for the film service-type mapping (RollCall "Harden
// Service-Type Mapping" fix brief, 11 Aug 2026).
//
// There are two hand-maintained lists that must agree:
//   1. backend/app/models/schemas.py — ServiceType enum (canonical values)
//   2. frontend/src/lib/serviceTypes.ts — SERVICE_TYPE_MAP (label -> enum value)
//
// This script reads both directly off disk (no build step, no test runner
// dependency — this repo has neither configured) and fails loudly if the
// set of backend enum values doesn't exactly match the set of values on the
// right-hand side of SERVICE_TYPE_MAP. Run it after touching either file:
//   node scripts/check_service_types.mjs
// or via the frontend npm alias:
//   npm run check:service-types --prefix frontend

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, "..");

const SCHEMA_PATH = resolve(repoRoot, "backend/app/models/schemas.py");
const MAP_PATH = resolve(repoRoot, "frontend/src/lib/serviceTypes.ts");

function fail(msg) {
  console.error(`✗ check_service_types: ${msg}`);
  process.exit(1);
}

// ── 1. Extract ServiceType enum values from schemas.py ──
const schemaSrc = readFileSync(SCHEMA_PATH, "utf8");
const enumBlockMatch = schemaSrc.match(/class ServiceType\(str, Enum\):([\s\S]*?)\n\n/);
if (!enumBlockMatch) {
  fail(`could not locate "class ServiceType(str, Enum):" block in ${SCHEMA_PATH}`);
}
const backendValues = [...enumBlockMatch[1].matchAll(/=\s*"([^"]+)"/g)].map((m) => m[1]);
if (backendValues.length === 0) {
  fail(`found the ServiceType class but no quoted values inside it — check ${SCHEMA_PATH} by hand`);
}

// ── 2. Extract SERVICE_TYPE_MAP values from serviceTypes.ts ──
const mapSrc = readFileSync(MAP_PATH, "utf8");
const mapBlockMatch = mapSrc.match(/SERVICE_TYPE_MAP[^{]*\{([\s\S]*?)\n\};/);
if (!mapBlockMatch) {
  fail(`could not locate "SERVICE_TYPE_MAP = { ... }" block in ${MAP_PATH}`);
}
// Each line looks like:  "Develop only":           "Dev only",
const frontendValues = [...mapBlockMatch[1].matchAll(/"[^"]+"\s*:\s*"([^"]+)"/g)].map((m) => m[1]);
if (frontendValues.length === 0) {
  fail(`found SERVICE_TYPE_MAP but no "label": "value" pairs inside it — check ${MAP_PATH} by hand`);
}

// ── 3. Diff as sets ──
const backendSet = new Set(backendValues);
const frontendSet = new Set(frontendValues);

const missingFromFrontend = [...backendSet].filter((v) => !frontendSet.has(v));
const extraInFrontend = [...frontendSet].filter((v) => !backendSet.has(v));

if (missingFromFrontend.length > 0 || extraInFrontend.length > 0) {
  console.error("✗ check_service_types: backend ServiceType enum and frontend SERVICE_TYPE_MAP have drifted apart.");
  if (missingFromFrontend.length > 0) {
    console.error(`  In backend enum but missing from frontend map: ${missingFromFrontend.join(", ")}`);
  }
  if (extraInFrontend.length > 0) {
    console.error(`  In frontend map but not a valid backend enum value: ${extraInFrontend.join(", ")}`);
  }
  console.error(`  Fix: update ${SCHEMA_PATH} and ${MAP_PATH} so both sides list the same enum values.`);
  process.exit(1);
}

console.log(`✓ check_service_types: backend enum and frontend map agree (${backendValues.length} service types).`);
