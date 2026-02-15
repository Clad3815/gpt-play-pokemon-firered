const fs = require("fs").promises;
const fsSync = require("fs");
const path = require("path");
const { config } = require("../config");

const emptyTotals = () => ({
  reasoning_ms: 0,
  tools_ms: 0,
  overall_ms: 0,
  down_ms: 0,
});

let acc = null;
let cumulativeTotals = emptyTotals();
let cumulativeLoaded = false;
let cumulativeLoadPromise = null;

function ensureDir(filePath) {
  const dir = path.dirname(filePath);
  if (!fsSync.existsSync(dir)) {
    fsSync.mkdirSync(dir, { recursive: true });
  }
}

function startLoop(step) {
  acc = {
    meta: { step, started_at: new Date().toISOString(), loop_start_ms: Date.now() },
    loop: { total_ms: 0, down_ms: 0 },
    reasoning: [],
    tools: [],
  };
}

function recordReasoning({ type, model, serviceTier, durationMs }) {
  if (!acc) return;
  acc.reasoning.push({
    type,
    model,
    service_tier: serviceTier,
    duration_ms: durationMs,
  });
}

function recordToolBatch({ callId, durationMs }) {
  if (!acc) return;
  acc.tools.push({
    call_id: callId,
    duration_ms: durationMs,
  });
}

function recordDownTime(durationMs) {
  if (!acc) return;
  acc.loop.down_ms = durationMs;
}

function recordTotal(durationMs) {
  if (!acc) return;
  acc.loop.total_ms = durationMs;
}

function accumulateTotals(into, totals) {
  if (!totals) return;
  for (const key of ["reasoning_ms", "tools_ms", "overall_ms", "down_ms"]) {
    const value = totals[key];
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
    const filePath = config.paths.timeUsageFile;
    const totals = emptyTotals();

    try {
      if (fsSync.existsSync(filePath)) {
        const raw = await fs.readFile(filePath, "utf8");
        const existing = raw.trim() ? JSON.parse(raw) : [];
        if (Array.isArray(existing)) {
          for (const entry of existing) {
            accumulateTotals(totals, entry?.totals);
          }
        }
      }
    } catch (error) {
      console.error("Error loading cumulative time usage totals:", error);
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
  if (!acc) return null;

  const totals = emptyTotals();
  totals.reasoning_ms = acc.reasoning.reduce((s, r) => s + (r.duration_ms || 0), 0);
  totals.tools_ms = acc.tools.reduce((s, t) => s + (t.duration_ms || 0), 0);
  totals.down_ms = acc.loop.down_ms || 0;
  totals.overall_ms = acc.loop.total_ms || 0;

  const entry = {
    step: meta.step ?? acc.meta.step ?? null,
    timestamp: meta.timestamp ?? new Date().toISOString(),
    loop: acc.loop,
    reasoning: acc.reasoning,
    tools: acc.tools,
    totals,
  };

  const filePath = config.paths.timeUsageFile;
  ensureDir(filePath);

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
      accumulateTotals(cumulativeTotals, entry.totals);
    } else {
      const totals = emptyTotals();
      for (const e of existing) {
        accumulateTotals(totals, e?.totals);
      }
      cumulativeTotals = totals;
      cumulativeLoaded = true;
    }
  } catch (error) {
    console.error("Error writing time usage file:", error);
  } finally {
    acc = null;
  }

  return entry;
}

module.exports = {
  startLoop,
  recordReasoning,
  recordToolBatch,
  recordDownTime,
  recordTotal,
  flush,
  getCumulativeTotals,
};

