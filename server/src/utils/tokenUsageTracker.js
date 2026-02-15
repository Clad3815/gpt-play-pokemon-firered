const fs = require("fs").promises;
const fsSync = require("fs");
const path = require("path");
const { config } = require("../config");
const { calculateRequestCost } = require("./costs");

const EMPTY_TOTALS = () => ({
  input_tokens: 0,
  cached_input_tokens: 0,
  output_tokens: 0,
  total_tokens: 0,
  cost: 0,
  discounted_cost: 0,
});

let accumulator = null;
let cumulativeTotals = EMPTY_TOTALS();
let cumulativeLoaded = false;
let cumulativeLoadPromise = null;

function ensureFileDirExists(filePath) {
  const dir = path.dirname(filePath);
  if (!fsSync.existsSync(dir)) {
    fsSync.mkdirSync(dir, { recursive: true });
  }
}

function startLoop(step) {
  accumulator = {
    meta: { step, started_at: new Date().toISOString() },
    loop: { calls: [], totals: EMPTY_TOTALS() },
    pathfinding: { calls: [], totals: EMPTY_TOTALS() },
  };
}

function addCall(section, callData) {
  if (!accumulator) return;
  const bucket = accumulator[section];
  if (!bucket) return;

  const { type, model, serviceTier, usage, cost, discountedCost } = callData;

  const input_tokens = usage?.input_tokens || 0;
  const cached_input_tokens = usage?.input_tokens_details?.cached_tokens || 0;
  const output_tokens = usage?.output_tokens || 0;
  const total_tokens = usage?.total_tokens || 0;

  bucket.calls.push({
    type,
    model,
    service_tier: serviceTier,
    input_tokens,
    cached_input_tokens,
    output_tokens,
    total_tokens,
    cost: cost ?? 0,
    discounted_cost: discountedCost ?? 0,
  });

  bucket.totals.input_tokens += input_tokens;
  bucket.totals.cached_input_tokens += cached_input_tokens;
  bucket.totals.output_tokens += output_tokens;
  bucket.totals.total_tokens += total_tokens;
  bucket.totals.cost += cost ?? 0;
  bucket.totals.discounted_cost += discountedCost ?? 0;
}

function recordLoopUsage({ callType, usage, cost, model, serviceTier }) {
  if (!accumulator) return;
  let resolvedCost = cost;
  if (!resolvedCost) {
    resolvedCost = calculateRequestCost(usage, model, config.openai.tokenPrice, serviceTier);
  }
  addCall("loop", {
    type: callType,
    model,
    serviceTier,
    usage,
    cost: resolvedCost?.fullCost ?? 0,
    discountedCost: resolvedCost?.discountedCost ?? 0,
  });
}

function recordPathfindingUsage({ usage, cost, model, serviceTier }) {
  if (!accumulator) return;
  let resolvedCost = cost;
  if (!resolvedCost) {
    resolvedCost = calculateRequestCost(usage, model, config.openai.tokenPrice, serviceTier);
  }
  addCall("pathfinding", {
    type: "pathfinding",
    model,
    serviceTier,
    usage,
    cost: resolvedCost?.fullCost ?? 0,
    discountedCost: resolvedCost?.discountedCost ?? 0,
  });
}

function accumulateTotals(into, total) {
  if (!total) return;
  for (const key of ["input_tokens", "cached_input_tokens", "output_tokens", "total_tokens", "cost", "discounted_cost"]) {
    const value = total[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      into[key] += value;
    }
  }
}

async function ensureCumulativeLoaded() {
  if (cumulativeLoaded) return;
  if (cumulativeLoadPromise) {
    await cumulativeLoadPromise;
    return;
  }

  cumulativeLoadPromise = (async () => {
    const filePath = config.paths.tokenUsageFile;
    const totals = EMPTY_TOTALS();

    try {
      if (fsSync.existsSync(filePath)) {
        const raw = await fs.readFile(filePath, "utf8");
        const existing = raw.trim() ? JSON.parse(raw) : [];
        if (Array.isArray(existing)) {
          for (const entry of existing) {
            accumulateTotals(totals, entry?.total);
          }
        }
      }
    } catch (error) {
      console.error("Error loading cumulative token usage totals:", error);
    }

    cumulativeTotals = totals;
    cumulativeLoaded = true;
  })().finally(() => {
    cumulativeLoadPromise = null;
  });

  await cumulativeLoadPromise;
}

async function getCumulativeTotals() {
  await ensureCumulativeLoaded();
  return { ...cumulativeTotals };
}

async function flush(meta = {}) {
  if (!accumulator) return null;

  const hasLoopCalls = accumulator.loop.calls.length > 0;
  const hasPathCalls = accumulator.pathfinding.calls.length > 0;
  if (!hasLoopCalls && !hasPathCalls) {
    accumulator = null;
    return null;
  }

  const total = EMPTY_TOTALS();
  for (const key of ["input_tokens", "cached_input_tokens", "output_tokens", "total_tokens", "cost", "discounted_cost"]) {
    total[key] = (accumulator.loop.totals[key] || 0) + (accumulator.pathfinding.totals[key] || 0);
  }

  const entry = {
    step: meta.step ?? accumulator.meta.step ?? null,
    timestamp: meta.timestamp ?? new Date().toISOString(),
    loop: accumulator.loop,
    pathfinding: accumulator.pathfinding,
    total,
  };

  const filePath = config.paths.tokenUsageFile;
  ensureFileDirExists(filePath);

  try {
    let existing = [];
    if (fsSync.existsSync(filePath)) {
      const raw = await fs.readFile(filePath, "utf8");
      existing = raw.trim() ? JSON.parse(raw) : [];
      if (!Array.isArray(existing)) existing = [];
    }
    existing.push(entry);
    await fs.writeFile(filePath, JSON.stringify(existing, null, 2));

    if (cumulativeLoaded) {
      accumulateTotals(cumulativeTotals, entry.total);
    } else {
      const totals = EMPTY_TOTALS();
      for (const e of existing) {
        accumulateTotals(totals, e?.total);
      }
      cumulativeTotals = totals;
      cumulativeLoaded = true;
    }
  } catch (error) {
    console.error("Error writing token usage file:", error);
  } finally {
    accumulator = null;
  }

  return entry;
}

module.exports = {
  startLoop,
  recordLoopUsage,
  recordPathfindingUsage,
  flush,
  getCumulativeTotals,
};

