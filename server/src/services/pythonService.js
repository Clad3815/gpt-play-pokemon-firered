const axios = require("axios");
const { config } = require("../config");

function toInt(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function formatSnakeToSpacesUpper(value) {
  if (typeof value !== "string") return "";
  return value.replace(/_/g, " ").replace(/\s+/g, " ").trim().toUpperCase();
}

function facingToOrientationId(facing) {
  switch (String(facing).toLowerCase()) {
    case "down":
      return 100;
    case "up":
      return 101;
    case "left":
      return 102;
    case "right":
      return 103;
    default:
      return 100;
  }
}

function mapStatus(statusCondition) {
  if (typeof statusCondition !== "string") return null;
  const upper = statusCondition.toUpperCase();
  if (upper === "NONE") return null;
  if (upper === "BAD_POISON") return "POISON";
  return upper;
}

function transformParty(party) {
  if (!Array.isArray(party)) return [];

  return party.slice(0, 6).map((mon) => {
    const speciesRaw = typeof mon?.species === "string" ? mon.species : "UNKNOWN";
    const species = speciesRaw.toUpperCase();
    const nicknameRaw = typeof mon?.nickname === "string" ? mon.nickname : null;
    const nickname = nicknameRaw && nicknameRaw !== speciesRaw ? nicknameRaw : null;

    const movesRaw = Array.isArray(mon?.moves) ? mon.moves : [];
    const ppRaw = Array.isArray(mon?.currentPP) ? mon.currentPP : [];
    const moves = movesRaw
      .map((moveName, idx) => ({
        name: formatSnakeToSpacesUpper(moveName),
        pp: toInt(ppRaw[idx]),
      }))
      .filter((m) => m.name && m.name !== "NONE");

    const types = Array.isArray(mon?.types) ? mon.types.filter((t) => typeof t === "string") : [];
    const ability = typeof mon?.ability === "string" ? formatSnakeToSpacesUpper(mon.ability) : null;
    const held_item_id = toInt(mon?.heldItemId);
    const heldItemNameRaw = typeof mon?.heldItemName === "string" ? mon.heldItemName : null;
    const held_item_name = heldItemNameRaw ? formatSnakeToSpacesUpper(heldItemNameRaw) : null;

    return {
      species_name: speciesRaw,
      nickname,
      level: toInt(mon?.level),
      current_hp: toInt(mon?.currentHP),
      max_hp: toInt(mon?.maxHP),
      moves,
      types,
      ability,
      status: mapStatus(mon?.statusCondition),
      pokedex_id: toInt(mon?.pokedexId),
      held_item_id,
      held_item_name,
      is_shiny: Boolean(mon?.is_shiny),
    };
  });
}

function pocketToTuples(items) {
  if (!Array.isArray(items)) return [];
  return items.map((it) => [formatSnakeToSpacesUpper(it?.name), toInt(it?.quantity)]);
}

function transformBagToInventory(bag) {
  return {
    item_pocket: pocketToTuples(bag?.["Items"]),
    ball_pocket: pocketToTuples(bag?.["Pokeballs"]),
    key_item_pocket: pocketToTuples(bag?.["Key Items"]),
    // FireRed exposes TMs/HMs through the TM Case UX; normalize this pocket name.
    tm_case: pocketToTuples(bag?.["TMs & HMs"]),
    // Keep other pockets if present (e.g. Berries), but do not assume order.
    berries_pocket: pocketToTuples(bag?.["Berries"]),
  };
}

function transformPcItems(pc) {
  const itemsRaw = pc?.items;
  if (!Array.isArray(itemsRaw)) return [];
  return itemsRaw
    .map((it) => ({
      name: formatSnakeToSpacesUpper(it?.name),
      quantity: toInt(it?.quantity),
      id: toInt(it?.id),
    }))
    .filter((it) => it.name && it.name !== "NONE" && it.quantity > 0);
}

function transformPcData(pc) {
  const boxMonsRaw = pc?.boxMons;
  const currentBoxRaw = toInt(pc?.currentBox, 0);
  const current_box = Number.isFinite(currentBoxRaw) ? currentBoxRaw + 1 : 1;

  const pokemons = [];
  if (Array.isArray(boxMonsRaw)) {
    for (let i = 0; i < boxMonsRaw.length; i++) {
      const mon = boxMonsRaw[i];
      if (!mon || typeof mon !== "object") continue;

      const speciesRaw = typeof mon?.species === "string" ? mon.species : "UNKNOWN";
      const nicknameRaw = typeof mon?.nickname === "string" ? mon.nickname : null;

      const movesRaw = Array.isArray(mon?.moves) ? mon.moves : [];
      const ppRaw = Array.isArray(mon?.currentPP) ? mon.currentPP : [];
      const moves = movesRaw
        .map((moveName, idx) => ({
          name: formatSnakeToSpacesUpper(moveName),
          pp: toInt(ppRaw[idx]),
        }))
        .filter((m) => m.name && m.name !== "NONE");

      const types = Array.isArray(mon?.types) ? mon.types.filter((t) => typeof t === "string") : [];

      pokemons.push({
        // 1-based for human readability (slots 1..30)
        slot_id: i + 1,
        species_name: speciesRaw,
        nickname: nicknameRaw && nicknameRaw !== speciesRaw ? nicknameRaw : null,
        level: toInt(mon?.level),
        current_hp: toInt(mon?.currentHP),
        max_hp: toInt(mon?.maxHP),
        moves,
        types,
        status: mapStatus(mon?.statusCondition),
        pokedex_id: toInt(mon?.pokedexId),
        is_shiny: Boolean(mon?.is_shiny),
      });
    }
  }

  return { current_box, pokemons };
}

function transformNpcEntries(npcs) {
  if (!Array.isArray(npcs)) return [];

  const entries = [];
  for (const npc of npcs) {
    if (!npc || typeof npc !== "object") continue;

    const posArr = Array.isArray(npc.position) ? npc.position : null;
    const xRaw = posArr ? Number(posArr[0]) : Number(npc.x);
    const yRaw = posArr ? Number(posArr[1]) : Number(npc.y);
    if (!Number.isFinite(xRaw) || !Number.isFinite(yRaw)) continue;

    const type = typeof npc.type === "string" ? npc.type : typeof npc.name === "string" ? npc.name : "UNKNOWN";

    entries.push({
      id: toInt(npc.id),
      localId: toInt(npc.localId),
      uid: typeof npc.uid === "string" ? npc.uid : null,
      objectEventId: npc.objectEventId ?? null,
      x: xRaw,
      y: yRaw,
      type,
      isOffScreen: Boolean(npc.isOffScreen),
      wandering: Boolean(npc.wandering),
      isActive: npc.isActive === undefined ? true : Boolean(npc.isActive),
      graphicsId: toInt(npc.graphicsId),
      movementType: toInt(npc.movementType),
      flagId: toInt(npc.flagId),
      elevation: toInt(npc.elevation),
    });
  }

  return entries;
}

function buildTrainerData(gameState) {
  const money = toInt(gameState?.player?.money);
  const pos = Array.isArray(gameState?.player?.position) ? gameState.player.position : [0, 0];
  const x = toInt(pos[0]);
  const y = toInt(pos[1]);
  const elevation = toInt(gameState?.player?.elevation, 0);

  const mapName = typeof gameState?.map?.name === "string" ? gameState.map.name : "Unknown";
  const mapGroup = toInt(gameState?.map?.group, 0);
  const mapNumber = toInt(gameState?.map?.number, 0);

  const rawBadges = gameState?.player?.badges;
  const badges = {};
  if (rawBadges && typeof rawBadges === "object" && !Array.isArray(rawBadges)) {
    for (const [badgeId, value] of Object.entries(rawBadges)) {
      badges[String(badgeId)] = Boolean(value);
    }
  } else if (Array.isArray(rawBadges)) {
    // Back-compat: older Python returned a list of acquired badge names.
    for (const badgeName of rawBadges) {
      badges[String(badgeName)] = true;
    }
  }
  const badge_count = Object.values(badges).filter(Boolean).length;

  return {
    name: "PLAYER",
    money,
    badge_count,
    badges,
    position: {
      map_name: mapName,
      map_id: `${mapGroup}-${mapNumber}`,
      x,
      y,
      elevation,
    },
  };
}

function transformBattlePokemon(battler) {
  if (!battler || typeof battler !== "object") return null;

  const movesRaw = Array.isArray(battler.moves) ? battler.moves : [];
  const ppRaw = Array.isArray(battler.pp) ? battler.pp : [];
  const moves = movesRaw
    .map((moveName, idx) => ({
      name: formatSnakeToSpacesUpper(moveName),
      pp: toInt(ppRaw[idx]),
    }))
    .filter((m) => m.name && m.name !== "NONE");

  const status =
    typeof battler.status === "string" && battler.status.toUpperCase() !== "NONE" ? battler.status : "OK";
  const types = Array.isArray(battler.types) ? battler.types.filter((t) => typeof t === "string") : [];

  return {
    species_name: typeof battler.species === "string" ? battler.species : "UNKNOWN",
    nickname: typeof battler.nickname === "string" ? battler.nickname : null,
    position: typeof battler.position === "string" ? battler.position : null,
    side: typeof battler.side === "string" ? battler.side : null,
    flank: typeof battler.flank === "string" ? battler.flank : null,
    level: toInt(battler.level),
    current_hp: toInt(battler?.hp?.current),
    max_hp: toInt(battler?.hp?.max),
    moves,
    types,
    status,
    species_id: toInt(battler.speciesId),
  };
}

function transformBattleData(gameState) {
  const battle = gameState?.battle;
  if (!battle || typeof battle !== "object" || battle.isActive !== true) {
    return {
      enemy: null,
      enemy_pokemons: [],
      in_battle: false,
      is_trainer_battle: false,
      is_double_battle: false,
      party_index: 0,
      party_indices: [],
      player_pokemon: null,
      player_pokemons: [],
    };
  }

  const playerBattlers = Array.isArray(battle?.data?.player) ? battle.data.player : [];
  const enemyBattlers = Array.isArray(battle?.data?.enemy) ? battle.data.enemy : [];

  const partyIndices = playerBattlers.map((b) => toInt(b?.partyIndex, -1)).filter((idx) => idx >= 0);
  const playerPokemons = playerBattlers.map(transformBattlePokemon).filter((mon) => mon !== null);
  const enemyPokemons = enemyBattlers.map(transformBattlePokemon).filter((mon) => mon !== null);

  return {
    enemy: enemyPokemons[0] ?? null,
    enemy_pokemons: enemyPokemons,
    in_battle: true,
    is_trainer_battle: Boolean(battle.isTrainerBattle),
    is_double_battle: Boolean(battle.isDoubleBattle),
    party_index: partyIndices[0] ?? 0,
    party_indices: partyIndices,
    player_pokemon: playerPokemons[0] ?? null,
    player_pokemons: playerPokemons,
  };
}

function buildMinimapData(gameState) {
  const fullMap = gameState?.map?.fullMap;
  const minimap = fullMap?.minimap_data;
  const gridRaw = minimap?.grid;
  if (!Array.isArray(gridRaw) || gridRaw.length === 0 || !Array.isArray(gridRaw[0])) {
    return null;
  }

  const height = gridRaw.length;
  const width = gridRaw[0].length;

  const playerPos = Array.isArray(gameState?.player?.position) ? gameState.player.position : [0, 0];
  const player_x = toInt(playerPos[0]);
  const player_y = toInt(playerPos[1]);

  const mapGroup = toInt(gameState?.map?.group, 0);
  const mapNumber = toInt(gameState?.map?.number, 0);

  return {
    grid: gridRaw,
    width,
    height,
    player_x,
    player_y,
    orientation: facingToOrientationId(gameState?.player?.facing),
    map_name: typeof gameState?.map?.name === "string" ? gameState.map.name : undefined,
    map_id: `${mapGroup}-${mapNumber}`,
  };
}

function buildVisibleAreaData(gameState) {
  const viewMap = gameState?.map?.viewMap;
  const gridRaw = viewMap?.minimap_data?.grid;
  if (!Array.isArray(gridRaw) || gridRaw.length === 0 || !Array.isArray(gridRaw[0])) {
    return null;
  }

  const origin = Array.isArray(viewMap?.minimap_data?.origin) ? viewMap.minimap_data.origin : [0, 0];
  const originX = toInt(origin[0]);
  const originY = toInt(origin[1]);

  return {
    grid: gridRaw,
    origin: { x: originX, y: originY },
    height: gridRaw.length,
    width: gridRaw[0].length,
  };
}

function buildGameDataJson(gameState) {
  const current_trainer_data = buildTrainerData(gameState);
  const minimap_data = buildMinimapData(gameState);
  const visible_area = buildVisibleAreaData(gameState);
  const pc_items = transformPcItems(gameState?.pc);
  const pc_data = transformPcData(gameState?.pc);
  const npc_entries = transformNpcEntries(gameState?.map?.fullMap?.npcs);
  const npc_entries_visible = transformNpcEntries(gameState?.map?.viewMap?.npcs);
  const importantEventsRaw = gameState?.importantEvents;
  const important_events = {};
  if (importantEventsRaw && typeof importantEventsRaw === "object" && !Array.isArray(importantEventsRaw)) {
    for (const [key, value] of Object.entries(importantEventsRaw)) {
      important_events[String(key)] = Boolean(value);
    }
  }

  const dialog = gameState?.dialog;
  const open_dialog_text = typeof dialog?.visibleText === "string" ? dialog.visibleText : "";
  const is_talking_to_npc = Boolean(dialog?.inDialog);

  const battle_data = transformBattleData(gameState);

  const flash_needed = Boolean(gameState?.map?.flashNeeded);
  const flash_active = Boolean(gameState?.map?.flashActive);
  const visibilityRaw = gameState?.map?.visibility;
  const visibility_reduced = Boolean(visibilityRaw?.reduced);
  const visibility_window_width_tiles = toInt(visibilityRaw?.widthTiles, visible_area?.width || 15);
  const visibility_window_height_tiles = toInt(visibilityRaw?.heightTiles, visible_area?.height || 10);
  const visibility_hint = typeof visibilityRaw?.hint === "string" ? visibilityRaw.hint : null;

  const strength_enabled = Boolean(gameState?.player?.strengthEnabled);
  const safari_zone_counter = Math.max(0, toInt(gameState?.player?.safariZoneStepsRemaining, 0));
  const safari_zone_active = Boolean(gameState?.player?.safariZoneActive);
  const player_movement_mode = typeof gameState?.player?.movementMode === "string" ? gameState.player.movementMode : "WALK";

  const screenshot_raw_path =
    typeof gameState?.emulator?.screenshotRawPath === "string" ? gameState.emulator.screenshotRawPath : null;

  return {
    // Keep legacy key names for compatibility with existing server consumers.
    current_trainer_data,
    current_pokemon_data: transformParty(gameState?.party),
    inventory_data: transformBagToInventory(gameState?.bag),
    pc_items,
    pc_data,
    minimap_data,
    game_area_meta_tiles: visible_area?.grid || null,
    visible_area_data: visible_area,
    is_talking_to_npc,
    open_dialog_text,
    battle_data,
    is_in_battle: Boolean(gameState?.emulator?.inBattle),
    flash_needed,
    flash_active,
    visibility_reduced,
    visibility_window_width_tiles,
    visibility_window_height_tiles,
    visibility_hint,
    strength_enabled,
    safari_zone_counter,
    safari_zone_active,
    player_movement_mode,
    minimap_legend: gameState?.map?.minimap_legend || {},
    screenshot_raw_path,
    important_events,
    npc_entries,
    npc_entries_visible,

    // Raw state aliases
    firered_state: gameState,
    raw_state: gameState,
  };
}

async function getMinimapData() {
  const gameData = await fetchGameData();
  return gameData?.minimap_data || null;
}

async function fetchMinimapSnapshot() {
  const url = config.pythonServer.baseUrl + config.pythonServer.endpoints.minimapSnapshot;
  try {
    const response = await axios.get(url);
    const body = response.data;
    if (!body || typeof body !== "object" || body.ok !== true) {
      console.error("Python /minimapSnapshot returned invalid payload:", body);
      return null;
    }
    return body.data || null;
  } catch (error) {
    console.error(`Error fetching minimap snapshot from ${url}:`, error.message);
    return null;
  }
}

async function fetchGameData() {
  const url = config.pythonServer.baseUrl + config.pythonServer.endpoints.requestData;
  try {
    const response = await axios.get(url);
    const body = response.data;
    if (!body || typeof body !== "object" || body.ok !== true || !body.data) {
      console.error("Python /requestData returned invalid payload:", body);
      return null;
    }
    return buildGameDataJson(body.data);
  } catch (error) {
    console.error(`Error fetching game data from ${url}:`, error.message);
    return null;
  }
}

async function sendCommandsToPythonServer(commands) {
  const url = config.pythonServer.baseUrl + config.pythonServer.endpoints.sendCommands;
  try {
    const response = await axios.post(url, { commands });
    return response.data;
  } catch (error) {
    console.error(`Error sending commands to ${url}:`, error.message);
    return { ok: false, error: error.message };
  }
}

async function requestConsoleRestart() {
  const url = config.pythonServer.baseUrl + config.pythonServer.endpoints.restartConsole;
  try {
    const response = await axios.post(url, {});
    return response.data;
  } catch (error) {
    const errorMessage = error.response?.data?.message || error.message;
    console.error(`Error restarting console via ${url}:`, errorMessage);
    return { status: false, message: errorMessage };
  }
}

module.exports = {
  getMinimapData,
  fetchMinimapSnapshot,
  fetchGameData,
  sendCommandsToPythonServer,
  requestConsoleRestart,
};
