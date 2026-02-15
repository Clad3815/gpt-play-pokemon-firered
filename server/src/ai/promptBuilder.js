const fs = require("fs").promises;
const path = require("path");

const { state } = require("../state/stateManager");
const { config } = require("../config");
const { gameAreaToMarkdown, minimapToMarkdown } = require("../formatters/markdownFormatter");

function escapeXml(text) {
  if (text == null) return "";
  return String(text);
    // .replace(/&/g, "&amp;")
    // .replace(/</g, "&lt;")
    // .replace(/>/g, "&gt;")
    // .replace(/"/g, "&quot;")
    // .replace(/'/g, "&apos;");
}

function formatMemoryStructured(memoryObj) {
  const entries = memoryObj && typeof memoryObj === "object" ? Object.entries(memoryObj) : [];
  if (entries.length === 0) return "<memory />\n";

  const lines = ["<memory>"];
  for (const [k, v] of entries) {
    lines.push(`  <item key="${escapeXml(k)}">${escapeXml(v)}</item>`);
  }
  lines.push("</memory>");
  return lines.join("\n") + "\n";
}

function formatRecentMarkers(markers, lastVisitedMaps, isInDialog) {
  if (!markers || typeof markers !== "object" || Object.keys(markers).length === 0) {
    return "<markers>No markers set</markers>\n";
  }

  if (isInDialog) {
    return "<markers>Markers are not visible in dialogue</markers>\n";
  }

  const visited = Array.isArray(lastVisitedMaps) ? lastVisitedMaps : [];
  const lastVisitedMapIds = new Set(visited.map((entry) => String(entry?.map_id ?? "")));
  const mapIdToName = new Map(
    visited
      .filter((e) => e && typeof e === "object" && e.map_id != null)
      .map((e) => [String(e.map_id), String(e.map_name || `Unknown Map (${e.map_id})`)])
  );

  const mapMarkerStrings = [];
  for (const [mapId, mapMarkers] of Object.entries(markers)) {
    if (!lastVisitedMapIds.has(String(mapId))) continue;
    if (!mapMarkers || typeof mapMarkers !== "object" || Object.keys(mapMarkers).length === 0) continue;

    const mapName =
      mapIdToName.get(String(mapId)) ||
      mapMarkers[Object.keys(mapMarkers)[0]]?.map_name ||
      `Unknown Map (${mapId})`;

    const sortedCoords = Object.keys(mapMarkers).sort((a, b) => {
      const [ax, ay] = a.split("_").map(Number);
      const [bx, by] = b.split("_").map(Number);
      if (ay !== by) return ay - by;
      return ax - bx;
    });

    const individualMarkerStrings = [];
    for (const coords of sortedCoords) {
      const marker = mapMarkers[coords];
      if (!marker || typeof marker !== "object") continue;
      const [x, y] = coords.split("_");
      individualMarkerStrings.push(`(${x}, ${y})=${marker.emoji} ${marker.label}`);
    }

    if (individualMarkerStrings.length === 0) continue;

    mapMarkerStrings.push(`  <map_markers map_id="${escapeXml(mapId)}" map_name="${escapeXml(mapName)}">
  ${individualMarkerStrings.map((s) => escapeXml(s)).join("\n    ")}
</map_markers>`);
  }

  if (mapMarkerStrings.length === 0) {
    return "<markers>No markers set in recently visited maps</markers>\n";
  }

  return `           
<markers>
Your current markers from recently visited maps:
${mapMarkerStrings.join("\n")}
Notes:
- The markers may be inaccurate since you defined them yourself.
- Fix or delete markers as soon as you notice they are inaccurate.
- Remember marker ownership: All markers are set by you—they are not extracted from RAM.
</markers>
\n`;
}

function formatObjectives(objectives) {
  if (!objectives || typeof objectives !== "object") return "<objectives />\n";

  const safe = (o) => (o && typeof o === "object" ? o : { short_description: "", description: "" });
  const primary = safe(objectives.primary);
  const secondary = safe(objectives.secondary);
  const third = safe(objectives.third);
  const others = Array.isArray(objectives.others) ? objectives.others : [];

  const lines = ["<objectives>"];
  lines.push(
    `  <primary short="${escapeXml(primary.short_description || "")}">${escapeXml(primary.description || "")}</primary>`
  );
  lines.push(
    `  <secondary short="${escapeXml(secondary.short_description || "")}">${escapeXml(
      secondary.description || ""
    )}</secondary>`
  );
  lines.push(
    `  <third short="${escapeXml(third.short_description || "")}">${escapeXml(third.description || "")}</third>`
  );
  if (others.length > 0) {
    lines.push("  <others>");
    for (const o of others) {
      const oo = safe(o);
      lines.push(
        `    <objective short="${escapeXml(oo.short_description || "")}">${escapeXml(
          oo.description || ""
        )}</objective>`
      );
    }
    lines.push("  </others>");
  }
  lines.push("</objectives>");
  return lines.join("\n") + "\n";
}

function formatInventory(inventory) {
  if (!inventory || typeof inventory !== "object") return "<inventory />\n";

  const pocketOrder = ["item_pocket", "key_item_pocket", "ball_pocket", "tm_case", "berries_pocket"];
  const pocketLabels = {
    item_pocket: "Items",
    key_item_pocket: "Key Items",
    ball_pocket: "Balls",
    tm_case: "TM Case",
    berries_pocket: "Berries",
  };

  const lines = ["<inventory>"];
  let globalIdx = 0;

  for (const pocketName of pocketOrder) {
    const pocket = inventory[pocketName];
    if (!Array.isArray(pocket) || pocket.length === 0) continue;
    lines.push(`  <pocket name="${escapeXml(pocketLabels[pocketName] || pocketName)}">`);
    pocket.forEach(([itemName, qty], pocketIdx) => {
      lines.push(
        `    <item index_id="${globalIdx}" name="${escapeXml(itemName)}" quantity="${Number(qty) || 0}" pocket_index="${pocketIdx}" />`
      );
      globalIdx += 1;
    });
    lines.push("  </pocket>");
  }

  lines.push("</inventory>");
  return lines.join("\n") + "\n";
}

function formatPcItems(pcItems) {
  const items = Array.isArray(pcItems) ? pcItems : [];
  const lines = [`<pc_items slot_count="${items.length}/50">`];
  if (items.length === 0) {
    lines.push("  <info>PC is empty</info>");
    lines.push("</pc_items>");
    return lines.join("\n") + "\n";
  }

  items.forEach((item, idx) => {
    lines.push(
      `  <item index_id="${idx}" name="${escapeXml(item?.name || "")}" quantity="${Number(item?.quantity) || 0}" />`
    );
  });
  lines.push("</pc_items>");
  return lines.join("\n") + "\n";
}

function formatPcPokemon(pcData) {
  const currentBox = Number(pcData?.current_box) || 1;
  const mons = Array.isArray(pcData?.pokemons) ? pcData.pokemons : [];
  const lines = [`<pc_pokemon current_box="${currentBox}" slot_count="${mons.length}/30">`];

  if (mons.length === 0) {
    lines.push("  <info>No Pokemon in PC</info>");
    lines.push("</pc_pokemon>");
    return lines.join("\n") + "\n";
  }

  for (const pokemon of mons) {
    if (!pokemon) continue;
    const nickname = pokemon.nickname || pokemon.species_name || "";
    const moves = Array.isArray(pokemon.moves) ? pokemon.moves : [];
    const moveList = moves.map((m) => `${m.name} (${Number(m.pp) || 0} PP)`).join(", ");
    const types = Array.isArray(pokemon.types) ? pokemon.types.join(", ") : "";

    lines.push(
      `  <pokemon slot_id="${Number(pokemon.slot_id) || 0}" species="${escapeXml(
        pokemon.species_name || ""
      )}" nickname="${escapeXml(nickname)}" level="${Number(pokemon.level) || 0}">`
    );
    lines.push(`    <hp current="${Number(pokemon.current_hp) || 0}" max="${Number(pokemon.max_hp) || 0}" />`);
    lines.push(`    <moves>${escapeXml(moveList)}</moves>`);
    lines.push(`    <types>${escapeXml(types)}</types>`);
    lines.push(`    <status>${escapeXml(pokemon.status || "OK")}</status>`);
    lines.push(`    <pokedex_id>${Number(pokemon.pokedex_id) || 0}</pokedex_id>`);
    lines.push("  </pokemon>");
  }

  lines.push("</pc_pokemon>");
  return lines.join("\n") + "\n";
}

function formatPokemonTeam(team) {
  const mons = Array.isArray(team) ? team : [];
  const lines = ["<pokemon_team>"];

  if (mons.length === 0) {
    lines.push("  <info>No Pokémon in party</info>");
    lines.push("</pokemon_team>");
    return lines.join("\n") + "\n";
  }

  for (const pokemon of mons) {
    const nickname = pokemon.nickname || pokemon.species_name;
    const status = pokemon.status || "OK";
    const moves = Array.isArray(pokemon.moves) ? pokemon.moves : [];
    const ability = pokemon.ability || "UNKNOWN";
    const heldItemId = Number(pokemon.held_item_id) || 0;
    const heldItemNameRaw = typeof pokemon.held_item_name === "string" ? pokemon.held_item_name : "";
    const heldItemName = heldItemNameRaw || (heldItemId ? "UNKNOWN" : "NONE");
    lines.push(
      `  <pokemon species="${escapeXml(pokemon.species_name)}" nickname="${escapeXml(
        nickname
      )}" level="${Number(pokemon.level) || 0}">`
    );
    lines.push(`    <hp current="${Number(pokemon.current_hp) || 0}" max="${Number(pokemon.max_hp) || 0}" />`);
    lines.push(`    <held_item id="${heldItemId}" name="${escapeXml(heldItemName)}" />`);
    lines.push("    <moves>");
    for (const m of moves) {
      lines.push(`      <move name="${escapeXml(m.name)}" pp="${Number(m.pp) || 0}" />`);
    }
    lines.push("    </moves>");
    lines.push(`    <types>${escapeXml((pokemon.types || []).join(", "))}</types>`);
    lines.push(`    <ability>${escapeXml(ability)}</ability>`);
    lines.push(`    <status>${escapeXml(status)}</status>`);
    lines.push(`    <is_shiny>${pokemon.is_shiny ? "true" : "false"}</is_shiny>`);
    lines.push("  </pokemon>");
  }

  lines.push("</pokemon_team>");
  return lines.join("\n") + "\n";
}

function formatBattleState(battleData) {
  const inBattle = Boolean(battleData?.in_battle);
  if (!inBattle) return `<battle_state active="false" />\n`;

  const playerMons = Array.isArray(battleData?.player_pokemons) ? battleData.player_pokemons : [];
  const enemyMons = Array.isArray(battleData?.enemy_pokemons) ? battleData.enemy_pokemons : [];

  const lines = [`<battle_state active="true">`];

  lines.push(`  <player_side count="${playerMons.length}">`);
  for (const p of playerMons) {
    if (!p) continue;
    const nickname = p.nickname || p.species_name;
    lines.push(
      `    <pokemon species="${escapeXml(p.species_name)}" nickname="${escapeXml(
        nickname
      )}" level="${Number(p.level) || 0}" position="${escapeXml(p.position || "")}">`
    );
    lines.push(`      <hp current="${Number(p.current_hp) || 0}" max="${Number(p.max_hp) || 0}" />`);
    lines.push(`      <status>${escapeXml(p.status || "OK")}</status>`);
    lines.push("      <moves>");
    for (const m of p.moves || []) {
      lines.push(`        <move name="${escapeXml(m.name)}" pp="${Number(m.pp) || 0}" />`);
    }
    lines.push("      </moves>");
    lines.push(`      <types>${escapeXml((p.types || []).join(", "))}</types>`);
    lines.push("    </pokemon>");
  }
  lines.push("  </player_side>");

  lines.push(`  <enemy_side count="${enemyMons.length}">`);
  for (const e of enemyMons) {
    if (!e) continue;
    const curHp = Number(e.current_hp) || 0;
    const maxHp = Number(e.max_hp) || 0;
    const hpPct =
      maxHp > 0 ? Math.max(0, Math.min(100, Math.round((curHp / maxHp) * 100))) : null;
    lines.push(
      `    <pokemon species="${escapeXml(e.species_name)}" level="${Number(e.level) || 0}" position="${escapeXml(
        e.position || ""
      )}">`
    );
    // Do not reveal exact enemy HP numbers; percentage is enough.
    lines.push(`      <hp percentage="${hpPct == null ? "unknown" : `${hpPct}%`}" />`);
    lines.push(`      <status>${escapeXml(e.status || "OK")}</status>`);
    lines.push(`      <types>${escapeXml((e.types || []).join(", "))}</types>`);
    lines.push("    </pokemon>");
  }
  lines.push("  </enemy_side>");

  lines.push("</battle_state>");
  return lines.join("\n") + "\n";
}

async function buildUserInputText(gameDataJson) {
  const { counters } = state;

  const trainer = gameDataJson?.current_trainer_data || null;
  const pos = trainer?.position || { map_name: "Unknown", map_id: "0-0", x: 0, y: 0, elevation: 0 };
  const isInDialog = Boolean(gameDataJson?.is_talking_to_npc);

  const movementMode = gameDataJson?.player_movement_mode || "WALK";
  const strengthEnabled = Boolean(gameDataJson?.strength_enabled);

  const visibilityReduced = Boolean(gameDataJson?.visibility_reduced);

  const visibleGrid = Array.isArray(gameDataJson?.game_area_meta_tiles) ? gameDataJson.game_area_meta_tiles : null;
  const minimap = gameDataJson?.minimap_data || null;
  const visibleAreaOrigin = gameDataJson?.visible_area_data?.origin || { x: pos.x, y: pos.y };
  const visibleW = gameDataJson?.visible_area_data?.width || (visibleGrid && visibleGrid[0] ? visibleGrid[0].length : 0);
  const visibleH = gameDataJson?.visible_area_data?.height || (visibleGrid ? visibleGrid.length : 0);
  // FireRed bridge: the visible grid comes with an origin (top-left world coords),
  // so the player's local position in the grid is (player - origin).
  let localRow = Number(pos.y) - Number(visibleAreaOrigin.y);
  let localCol = Number(pos.x) - Number(visibleAreaOrigin.x);
  if (!Number.isFinite(localRow) || localRow < 0 || localRow >= visibleH) {
    localRow = visibleH ? Math.floor(visibleH / 2) : 0;
  }
  if (!Number.isFinite(localCol) || localCol < 0 || localCol >= visibleW) {
    localCol = visibleW ? Math.floor(visibleW / 2) : 0;
  }

  let gameAreaDisplay = null;
  let minimapDisplay = null;

  if (!isInDialog && visibleGrid && minimap && minimap.grid) {
    // Viewport uses `origin` instead of assuming the player is always at (4,4).
    // Keep markdown format stable and adapt coordinate math in the formatter.
    gameAreaDisplay = gameAreaToMarkdown(
      visibleGrid,
      pos.x,
      pos.y,
      pos.map_id,
      pos.map_name,
      minimap.grid.length,
      minimap.grid[0]?.length || 0,
      visibleAreaOrigin.x,
      visibleAreaOrigin.y,
      minimap.orientation ?? null,
      gameDataJson?.npc_entries_visible ?? null
    );

    // Console log the visible game area
    console.log("Visible game area:", gameAreaDisplay);

    minimapDisplay = minimapToMarkdown(
      minimap,
      pos.x,
      pos.y,
      pos.map_id,
      pos.map_name,
      minimap.orientation ?? null,
      visibleGrid,
      localRow,
      localCol,
      gameDataJson?.npc_entries ?? null
    );
  }


  const trainerName = trainer?.name || "PLAYER";
  const money = trainer?.money ?? 0;
  const badgeCount = trainer?.badge_count ?? 0;
  let userInputText = `
<game_state timestamp="${new Date().toISOString()}" current_step="${counters.currentStep}">
<current_situation>
  <player_location map="${escapeXml(pos.map_name)}" map_id="${escapeXml(pos.map_id)}" x="${pos.x}" y="${pos.y}" elevation="${Number(pos.elevation) || 0}" />
  <dialog_status active="${isInDialog}">${isInDialog ? "In dialogue/menu" : "Free movement"}</dialog_status>
  ${isInDialog ? `<dialog_text>${escapeXml(gameDataJson?.open_dialog_text || "")}</dialog_text>` : ""}
  <movement_mode>${escapeXml(movementMode)}</movement_mode>
  <strength_status>${strengthEnabled ? "true" : "false"}</strength_status>
  <flash_needed>${gameDataJson?.flash_needed ? "true" : "false"}</flash_needed>
  <flash_active>${gameDataJson?.flash_active ? "true" : "false"}</flash_active>
  <visibility reduced="${visibilityReduced ? "true" : "false"}" window="${visibleH}x${visibleW}">
    ${visibilityReduced ? "Visibility is reduced due to darkness." : ""}
  </visibility>
</current_situation>

<player_stats>
  <trainer name="${escapeXml(trainerName)}" money="${money}" badges="${badgeCount}/8" />
  ${formatPokemonTeam(gameDataJson?.current_pokemon_data)}
  ${formatInventory(gameDataJson?.inventory_data)}
  ${formatPcItems(gameDataJson?.pc_items)}
  ${formatPcPokemon(gameDataJson?.pc_data)}
</player_stats>

${formatBattleState(gameDataJson?.battle_data)}

<objectives_section>
${formatObjectives(state.objectives)}
</objectives_section>

${formatMemoryStructured(state.memory)}

${formatRecentMarkers(state.markers, state.lastVisitedMaps, isInDialog)}

<visible_area>
${isInDialog ? "Not visible in dialogue" : gameAreaDisplay || "No visible area data"}
</visible_area>

<explored_map>
${isInDialog ? "Not visible in dialogue" : minimapDisplay || "No minimap data"}
</explored_map>

</game_state>
  `.trim();

  if (state.selfCritiqueReminderPending) {
    userInputText += `
<self_criticism_reminder>
Before taking the next action, update the <memory> / <objectives> / <markers> sections exactly as indicated by your latest self-criticism using the memory / objectives / markers management tools.
Read your self-criticism carefully and update the sections accordingly as mentioned in the self-criticism.
You can safely update them all at once.
</self_criticism_reminder>`;
    state.selfCritiqueReminderAcknowledged = true;
  }

  // Save the userInputText into a debug file
  fs.writeFile(config.paths.lastUserInputTextSaveFile, userInputText, "utf8");

  return userInputText;
}

async function buildDeveloperPrompt() {
  const gamePrompt = await fs.readFile(path.join(config.promptsDir, "game.txt"), "utf8");
  return {
    role: "developer",
    content: [{ type: "input_text", text: gamePrompt }],
  };
}

module.exports = { buildUserInputText, formatMemoryStructured, buildDeveloperPrompt };
