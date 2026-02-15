const path = require("path");

// `__dirname` points to `server/src`; ROOT_DIR is `server/`
const ROOT_DIR = path.join(__dirname, "..");

const config = {
  wsPort: Number(process.env.WS_PORT || 9885),

  // --- OpenAI Configuration ---
  openai: {
    apiKey: process.env.OPENAI_API_KEY,
    model: process.env.OPENAI_MODEL || "gpt-5.2",
    reasoningEffort: process.env.OPENAI_REASONING_EFFORT || "high",
    reasoningEffortBattle: process.env.OPENAI_REASONING_EFFORT_BATTLE || "high",
    reasoningEffortDialog: process.env.OPENAI_REASONING_EFFORT_DIALOG || "high",
    reasoningEffortCriticism: process.env.OPENAI_REASONING_EFFORT_CRITICISM || "high",
    reasoningEffortSummary: process.env.OPENAI_REASONING_EFFORT_SUMMARY || "xhigh",
    modelPathFinding: process.env.OPENAI_MODEL_PATHFINDING || "gpt-5.2",
    reasoningEffortPathfinding: process.env.OPENAI_REASONING_EFFORT_PATHFINDING || "high",
    reasoningSummary: process.env.OPENAI_REASONING_SUMMARY || "auto",

    tokenLimit: Number(process.env.OPENAI_TOKEN_LIMIT || 250000),
    timeout: Number(process.env.OPENAI_TIMEOUT_MS || 15 * 60 * 1000),
    service_tier: process.env.OPENAI_SERVICE_TIER || "priority",
    service_tierSelfCriticism:
      process.env.OPENAI_SERVICE_TIER_SELF_CRITICISM || process.env.OPENAI_SERVICE_TIER || "priority",
    service_tierSummary: process.env.OPENAI_SERVICE_TIER_SUMMARY || process.env.OPENAI_SERVICE_TIER || "priority",
    service_tierPathfinding: process.env.OPENAI_SERVICE_TIER_PATHFINDING || "priority",

    tokenPrice: {
      "gpt-5.2": { input: 1.75, cached_input: 0.175, output: 14 },
      "gpt-5.1": { input: 1.25, cached_input: 0.125, output: 10 },
      "gpt-5": { input: 1.25, cached_input: 0.125, output: 10 },
      "gpt-4.1": { input: 2, cached_input: 0.5, output: 8 },
      "o4-mini": { input: 1.1, cached_input: 0.275, output: 4.4 },
      "o3": { input: 10, cached_input: 2.5, output: 40 },
    },
  },

  // --- Python Server Configuration (FireRed bridge) ---
  pythonServer: {
    baseUrl: process.env.PYTHON_BASE_URL || "http://127.0.0.1:8000",
    endpoints: {
      requestData: "/requestData",
      minimapSnapshot: "/minimapSnapshot",
      sendCommands: "/sendCommands",
      restartConsole: "/restartConsole",
    },
  },

  // --- Runtime Paths ---
  get dataDir() {
    return "gpt_data";
  },

  get promptsDir() {
    return path.join(ROOT_DIR, "prompts");
  },

  // --- File Paths ---
  paths: {
    baseDir: ROOT_DIR,

    get dataDir() {
      return config.dataDir;
    },

    get historySaveFile() {
      return path.join(ROOT_DIR, config.dataDir, "history.json");
    },
    get memorySaveFile() {
      return path.join(ROOT_DIR, config.dataDir, "memory.json");
    },
    get objectivesSaveFile() {
      return path.join(ROOT_DIR, config.dataDir, "objectives.json");
    },
    get markersSaveFile() {
      return path.join(ROOT_DIR, config.dataDir, "markers.json");
    },
    get countersSaveFile() {
      return path.join(ROOT_DIR, config.dataDir, "counters.json");
    },
    get badgesSaveFile() {
      return path.join(ROOT_DIR, config.dataDir, "badges_log.json");
    },
    get mapVisitsSaveFile() {
      return path.join(ROOT_DIR, config.dataDir, "map_visits.json");
    },
    get summariesSaveFile() {
      return path.join(ROOT_DIR, config.dataDir, "summaries.json");
    },
    get allSummariesSaveFile() {
      return path.join(ROOT_DIR, config.dataDir, "all_summaries.json");
    },
    get progressStepsFile() {
      return path.join(ROOT_DIR, config.dataDir, "progress_steps.json");
    },
    get lastVisitedMapsFile() {
      return path.join(ROOT_DIR, config.dataDir, "last_visited_maps.json");
    },
    get gameDataJsonFile() {
      return path.join(ROOT_DIR, config.dataDir, "game_data.json");
    },
    get lastCriticismSaveFile() {
      return path.join(ROOT_DIR, config.dataDir, "last_criticism.txt");
    },
    get tokenUsageFile() {
      return path.join(ROOT_DIR, config.dataDir, "token_usage.json");
    },
    get timeUsageFile() {
      return path.join(ROOT_DIR, config.dataDir, "time_usage.json");
    },
    get lastUserInputTextSaveFile() {
      return path.join(ROOT_DIR, config.dataDir, "last_userInputText_prompt.txt");
    },
  },

  // --- History Processing Configuration ---
  history: {
    keepLastNToolPartialResults: 20,
    keepLastNToolFullResults: 6,
    keepLastNUserMessagesWithMinimap: 1,
    keepLastNUserMessagesWithMemory: 1,
    keepLastNUserMessagesWithViewMap: 5,
    keepLastNUserMessagesWithImages: 10,
    keepLastNUserMessagesWithDetailedData: 4,
    keepLastNUserMessagesWithPokedex: 1,
    limitAssistantMessagesForSelfCriticism: 55,
    limitAssistantMessagesForSummary: 120,
  },

  // --- Tool Configuration ---
  tools: {
    strict: true,
  },

  // --- Loop Configuration ---
  loopDelayMs: 0,
};

module.exports = { config };
