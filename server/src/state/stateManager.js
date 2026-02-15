const fs = require("fs").promises;
const fsSync = require("fs");
const path = require("path");
const { config } = require("../config");

/**
 * Central in-memory state for the agent.
 */
const state = {
  history: [],
  memory: {},
  objectives: { primary: {}, secondary: {}, third: {}, others: [] },
  markers: {},
  counters: { currentStep: 0, lastCriticismStep: 0, lastSummaryStep: 0 },
  summaries: [],
  allSummaries: [],
  badgeHistory: {},
  previousBadgesState: {},
  mapVisitHistory: {},
  progressSteps: [],
  lastVisitedMaps: [],
  skipNextUserMessage: false,
  selfCritiqueReminderPending: false,
  selfCritiqueReminderAcknowledged: false,
  gameDataJsonRef: null,
  lastTotalTokens: 0,
  isThinking: false,
};

let broadcast = null;

function attachBroadcast(fn) {
  broadcast = fn;
}

function setIsThinking(value) {
  state.isThinking = value;
  if (broadcast) {
    broadcast({ type: "isThinking_update", payload: value });
  }
}

function historyEndsWithSelfCritiqueMessage(currentHistory) {
  if (!Array.isArray(currentHistory) || currentHistory.length === 0) return false;

  for (let i = currentHistory.length - 1; i >= 0; i--) {
    const entry = currentHistory[i];
    if (!entry) continue;

    if (entry.role === "assistant" && Array.isArray(entry.content)) {
      return entry.content.some(
        (item) =>
          item &&
          item.type === "output_text" &&
          typeof item.text === "string" &&
          item.text.includes("<self_criticism>")
      );
    }

    if (entry.role === "user" || entry.role === "system") {
      break;
    }
  }

  return false;
}

async function loadPersistentState() {
  try {
    const historyData = await fs.readFile(config.paths.historySaveFile, "utf-8");
    state.history = JSON.parse(historyData);
    console.log("History loaded. Size:", state.history.length);
  } catch (error) {
    if (error.code === "ENOENT") {
      console.log("History file not found, starting with empty history.");
      state.history = [
        {
          role: "user",
          content: [
            {
              type: "input_text",
              text: "[NEW GAME STARTED. Please set the text speed as soon as you finish the intro and have access to the start menu. Keep the battle animations and battle style with default settings.]",
            },
          ],
        },
      ];
    } else {
      console.error("Error loading history:", error);
    }
  }

  state.selfCritiqueReminderPending = historyEndsWithSelfCritiqueMessage(state.history);
  if (state.selfCritiqueReminderPending) {
    console.log("Detected pending self-critique reminder from saved history.");
  }

  try {
    const memoryData = await fs.readFile(config.paths.memorySaveFile, "utf-8");
    state.memory = JSON.parse(memoryData);
    console.log("Memory size:", Object.keys(state.memory).length);
    console.log("Memory loaded.");
  } catch (error) {
    if (error.code === "ENOENT") {
      console.log("Memory file not found, starting with empty memory.");
      state.memory = {};
    } else {
      console.error("Error loading memory:", error);
    }
  }

  try {
    const objectivesData = await fs.readFile(config.paths.objectivesSaveFile, "utf-8");
    state.objectives = JSON.parse(objectivesData);
    console.log("Objectives loaded.");
    if (typeof state.objectives.primary !== "object")
      state.objectives.primary = { short_description: "", description: "" };
    if (typeof state.objectives.secondary !== "object")
      state.objectives.secondary = { short_description: "", description: "" };
    if (typeof state.objectives.third !== "object")
      state.objectives.third = { short_description: "", description: "" };
    if (!Array.isArray(state.objectives.others)) state.objectives.others = [];
    state.objectives.others = state.objectives.others.filter((item) => typeof item === "object");
  } catch (error) {
    if (error.code === "ENOENT") {
      console.log("Objectives file not found, starting with empty objectives.");
    } else {
      console.error("Error loading objectives:", error);
    }
    state.objectives = {
      primary: { short_description: "", description: "" },
      secondary: { short_description: "", description: "" },
      third: { short_description: "", description: "" },
      others: [],
    };
  }

  try {
    const markersData = await fs.readFile(config.paths.markersSaveFile, "utf-8");
    state.markers = JSON.parse(markersData);
    console.log("Markers loaded.");
  } catch (error) {
    if (error.code === "ENOENT") {
      console.log("Markers file not found, starting with empty markers.");
      state.markers = {};
    } else {
      console.error("Error loading markers:", error);
      state.markers = {};
    }
  }

  try {
    const countersData = await fs.readFile(config.paths.countersSaveFile, "utf-8");
    state.counters = JSON.parse(countersData);
    console.log("Counters loaded.");
    if (typeof state.counters.currentStep !== "number") state.counters.currentStep = 0;
    if (typeof state.counters.lastCriticismStep !== "number") state.counters.lastCriticismStep = 0;
    if (typeof state.counters.lastSummaryStep !== "number") state.counters.lastSummaryStep = 0;
  } catch (error) {
    if (error.code === "ENOENT") {
      console.log("Counters file not found, starting with default counters.");
    } else {
      console.error("Error loading counters:", error);
    }
    state.counters = { currentStep: 0, lastCriticismStep: 0, lastSummaryStep: 0 };
  }

  try {
    const badgesData = await fs.readFile(config.paths.badgesSaveFile, "utf-8");
    const rawBadges = JSON.parse(badgesData);
    const normalized = {};
    if (rawBadges && typeof rawBadges === "object" && !Array.isArray(rawBadges)) {
      for (const [badgeId, value] of Object.entries(rawBadges)) {
        if (value && typeof value === "object" && !Array.isArray(value)) {
          const obtained = typeof value.obtained === "boolean" ? value.obtained : true; // back-compat
          const step = typeof value.step === "number" ? value.step : null;
          const timestamp = typeof value.timestamp === "string" ? value.timestamp : null;
          normalized[String(badgeId)] = { obtained, step, timestamp };
        } else if (typeof value === "boolean") {
          normalized[String(badgeId)] = { obtained: value, step: null, timestamp: null };
        } else {
          normalized[String(badgeId)] = { obtained: false, step: null, timestamp: null };
        }
      }
    }
    state.badgeHistory = normalized;
    console.log("Badge history loaded.");
    state.previousBadgesState = {};
    for (const [badgeId, info] of Object.entries(state.badgeHistory)) {
      state.previousBadgesState[badgeId] = Boolean(info?.obtained);
    }
    console.log("Initialized previousBadgesState based on loaded badge history state.");
  } catch (error) {
    if (error.code === "ENOENT") {
      console.log("Badges log file not found, starting with empty history.");
    } else {
      console.error("Error loading badge history:", error);
    }
    state.badgeHistory = {};
    state.previousBadgesState = {};
  }

  try {
    const mapVisitsData = await fs.readFile(config.paths.mapVisitsSaveFile, "utf-8");
    state.mapVisitHistory = JSON.parse(mapVisitsData);
    console.log("Map visit history loaded.");
  } catch (error) {
    if (error.code === "ENOENT") {
      console.log("Map visit log file not found, starting with empty history.");
    } else {
      console.error("Error loading map visit history:", error);
    }
    state.mapVisitHistory = {};
  }

  try {
    const summariesData = await fs.readFile(config.paths.summariesSaveFile, "utf-8");
    state.summaries = JSON.parse(summariesData);
    if (!Array.isArray(state.summaries)) {
      console.warn("Summaries file contained non-array data. Resetting.");
      state.summaries = [];
    }
    console.log("Summaries loaded. Count:", state.summaries.length);
  } catch (error) {
    if (error.code === "ENOENT") {
      console.log("Summaries file not found, starting with empty summaries list.");
    } else {
      console.error("Error loading summaries:", error);
    }
    state.summaries = [];
  }

  try {
    const allSummariesData = await fs.readFile(config.paths.allSummariesSaveFile, "utf-8");
    state.allSummaries = JSON.parse(allSummariesData);
    if (!Array.isArray(state.allSummaries)) {
      console.warn("All summaries file contained non-array data. Resetting.");
      state.allSummaries = [];
    }
    console.log("All summaries loaded. Count:", state.allSummaries.length);
  } catch (error) {
    if (error.code === "ENOENT") {
      console.log("All summaries file not found, starting with empty all summaries list.");
    } else {
      console.error("Error loading all summaries:", error);
    }
    state.allSummaries = [];
  }

  {
    let loadedSteps = [];
    let shouldSeedFromTemplate = false;

    try {
      const progressStepsData = await fs.readFile(config.paths.progressStepsFile, "utf-8");
      const parsed = JSON.parse(progressStepsData);
      if (!Array.isArray(parsed)) {
        console.warn("Progress steps file contained non-array data. Re-initializing from template.");
        shouldSeedFromTemplate = true;
      } else if (parsed.length === 0) {
        console.warn("Progress steps file is empty. Re-initializing from template.");
        shouldSeedFromTemplate = true;
      } else {
        loadedSteps = parsed;
        console.log("Progress steps loaded. Count:", loadedSteps.length);
      }
    } catch (error) {
      if (error.code === "ENOENT") {
        console.log("Progress steps file not found, initializing from template.");
        shouldSeedFromTemplate = true;
      } else {
        console.error("Error loading progress steps:", error);
        shouldSeedFromTemplate = true;
      }
    }

    if (shouldSeedFromTemplate) {
      try {
        const templatePath = path.join(config.paths.baseDir, "progress_steps.json");
        const templateData = await fs.readFile(templatePath, "utf-8");
        const templateSteps = JSON.parse(templateData);
        if (Array.isArray(templateSteps) && templateSteps.length > 0) {
          const initializedSteps = templateSteps.map((step) => ({
            ...step,
            done: false,
            done_on: null,
          }));
          await fs.mkdir(path.join(config.paths.baseDir, config.dataDir), { recursive: true });
          await fs.writeFile(config.paths.progressStepsFile, JSON.stringify(initializedSteps, null, 2));
          loadedSteps = initializedSteps;
          console.log(`Progress steps file created for this AI from template: ${config.paths.progressStepsFile}`);
        } else {
          console.warn("Template progress_steps.json contained no steps. Starting with empty progress steps list.");
          loadedSteps = [];
        }
      } catch (templateError) {
        console.error("Error reading template progress_steps.json:", templateError);
        loadedSteps = [];
      }
    }

    state.progressSteps = loadedSteps;
    console.log("Progress steps loaded. Count:", state.progressSteps.length);
  }

  try {
    const lastVisitedMapsData = await fs.readFile(config.paths.lastVisitedMapsFile, "utf-8");
    state.lastVisitedMaps = JSON.parse(lastVisitedMapsData);
    if (!Array.isArray(state.lastVisitedMaps)) {
      console.warn("Last visited maps file contained non-array data. Resetting.");
      state.lastVisitedMaps = [];
    }
    console.log("Last visited maps loaded. Count:", state.lastVisitedMaps.length);
  } catch (error) {
    if (error.code === "ENOENT") {
      console.log("Last visited maps file not found, starting with empty list.");
    } else {
      console.error("Error loading last visited maps:", error);
    }
    state.lastVisitedMaps = [];
  }

  // Ensure directories exist
  try {
    const dataDirPath = path.join(config.paths.baseDir, config.dataDir);
    if (!fsSync.existsSync(dataDirPath)) {
      fsSync.mkdirSync(dataDirPath, { recursive: true });
    }

    // Ensure the all_summaries file exists so data sync doesn't spam failures on a fresh run.
    if (!fsSync.existsSync(config.paths.allSummariesSaveFile)) {
      await fs.writeFile(config.paths.allSummariesSaveFile, JSON.stringify(state.allSummaries, null, 2));
    }
  } catch (e) {
    console.warn("Failed to ensure dataDir exists:", e);
  }
}

async function savePersistentState() {
  try {
    await fs.writeFile(config.paths.historySaveFile, JSON.stringify(state.history, null, 2));
    await fs.writeFile(config.paths.memorySaveFile, JSON.stringify(state.memory, null, 2));
    await fs.writeFile(config.paths.objectivesSaveFile, JSON.stringify(state.objectives, null, 2));
    await fs.writeFile(config.paths.markersSaveFile, JSON.stringify(state.markers, null, 2));
    await fs.writeFile(config.paths.countersSaveFile, JSON.stringify(state.counters, null, 2));
    await fs.writeFile(config.paths.badgesSaveFile, JSON.stringify(state.badgeHistory, null, 2));
    await fs.writeFile(config.paths.mapVisitsSaveFile, JSON.stringify(state.mapVisitHistory, null, 2));
    await fs.writeFile(config.paths.summariesSaveFile, JSON.stringify(state.summaries, null, 2));
    await fs.writeFile(config.paths.allSummariesSaveFile, JSON.stringify(state.allSummaries, null, 2));
    await fs.writeFile(config.paths.progressStepsFile, JSON.stringify(state.progressSteps, null, 2));
    await fs.writeFile(config.paths.lastVisitedMapsFile, JSON.stringify(state.lastVisitedMaps, null, 2));
  } catch (error) {
    console.error("Error saving persistent state:", error);
  }
}

module.exports = {
  state,
  attachBroadcast,
  setIsThinking,
  loadPersistentState,
  savePersistentState,
};
