const fs = require('fs').promises;
const fsSync = require('fs');
const path = require('path');
const { config } = require('../config');
const { state, setIsThinking, savePersistentState } = require('../state/stateManager');
const { broadcast } = require('../core/socketHub');
const { calculateRequestCost } = require('../utils/costs');
const { fetchGameData } = require('../services/pythonService');
const { buildVisionPayload } = require('../services/screenshotService');
const { buildUserInputText, buildDeveloperPrompt } = require('../ai/promptBuilder');
const { processHistoryForAPI } = require('../ai/historyProcessor');
const { defineTools, handleToolCall } = require('../ai/tools');
const { updateProgressSteps, updateLastVisitedMaps } = require('./progressTracker');
const { openai } = require('./openaiClient');
const { startLoop, recordLoopUsage, flush, getCumulativeTotals } = require('../utils/tokenUsageTracker');
const {
    startLoop: startTimeLoop,
    recordReasoning,
    recordToolBatch,
    recordDownTime,
    recordTotal,
    flush: flushTime,
    getCumulativeTotals: getCumulativeTimeTotals,
} = require('../utils/timeTracker');

// Keep markers with NPC-linked UIDs in sync with current npc_entries positions
// Returns true if any marker was moved
function reconcileMarkersWithNpcEntries(gameDataJson) {
    const npcEntries = Array.isArray(gameDataJson?.npc_entries) ? gameDataJson.npc_entries : null;
    const currentMapId = gameDataJson?.current_trainer_data?.position?.map_id;
    if (!npcEntries || !currentMapId) return false;

    const mapMarkers = state.markers[currentMapId];
    if (!mapMarkers || Object.keys(mapMarkers).length === 0) return false;

    const npcByUid = new Map();
    for (const entry of npcEntries) {
        if (entry?.uid) npcByUid.set(entry.uid, entry);
    }

    let updated = false;
    for (const markerKey of Object.keys(mapMarkers)) {
        const marker = mapMarkers[markerKey];
        if (!marker || !marker.uid) continue; // Only sync markers that are tied to a npc_entries UID

        const npc = npcByUid.get(marker.uid);
        if (!npc) continue; // UID no longer present; leave marker untouched for now

        const [mx, my] = markerKey.split('_').map(Number);
        if (npc.x !== mx || npc.y !== my) {
            // Move marker to NPC's new position
            delete mapMarkers[markerKey];
            const newKey = `${npc.x}_${npc.y}`;
            mapMarkers[newKey] = { ...marker };
            updated = true;
            console.log(`Markers sync: moved UID ${marker.uid} from (${mx}, ${my}) to (${npc.x}, ${npc.y}) on map ${currentMapId}`);
        }
    }

    if (updated) {
        state.markers[currentMapId] = mapMarkers;
        broadcast({ type: 'markers_update', payload: state.markers });
    }

    return updated;
}

async function gameLoop() {
    while (true) {
        const loopStartTime = Date.now(); // track per-iteration timing across try/catch/finally
        try {
            // <<< ADDED YIELD >>>
            await new Promise(setImmediate); // Allow event loop processing at the start
            startLoop(state.counters.currentStep);
            startTimeLoop(state.counters.currentStep);

            // Broadcast cumulative token usage at the start of each loop iteration.
            // Use `total_tokens` from persisted data (do not recompute from input/output).
            try {
                const totals = await getCumulativeTotals();
                broadcast({
                    type: 'token_usage_total',
                    payload: {
                        ...totals,
                        step: state.counters.currentStep,
                        discountedCost: totals.discounted_cost,
                        input_tokens_details: { cached_tokens: totals.cached_input_tokens },
                    },
                });
            } catch (error) {
                console.warn("Failed to broadcast cumulative token usage totals:", error);
            }

            // Broadcast cumulative time usage at the start of each loop iteration.
            try {
                const totals = await getCumulativeTimeTotals();
                broadcast({
                    type: 'time_usage_total',
                    payload: {
                        ...totals,
                        step: state.counters.currentStep,
                    },
                });
            } catch (error) {
                console.warn("Failed to broadcast cumulative time usage totals:", error);
            }

            let newUserMessage = null;
            let responseCompleted = false;
            setIsThinking(true);
            state.selfCritiqueReminderAcknowledged = false; // Reset reminder delivery flag for this iteration
            // 0. Short pause (optional)
            if (config.loopDelayMs > 0) {
                await new Promise(resolve => setTimeout(resolve, config.loopDelayMs));
            }
            // 1. Get the current game state
            const gameDataJson = await fetchGameData();
            state.gameDataJsonRef = gameDataJson; // <<< Store latest game data
            if (!gameDataJson) {
                console.error("Could not retrieve game data. Pausing and retrying...");
                broadcast({ type: 'error_message', payload: 'Failed to retrieve game data from Python server.' });
                await new Promise(resolve => setTimeout(resolve, 5000)); // Wait 5s
                continue; // Restart the loop
            }
            // Keep markers with NPC-linked UIDs aligned to their latest positions
            const markersMoved = reconcileMarkersWithNpcEntries(gameDataJson);
            if (markersMoved) {
                // Persist immediately so we don't repeat the move next loop
                await savePersistentState();
            }
            // console.log("Game data received:", gameDataJson); // Debug
            await fs.writeFile(config.paths.gameDataJsonFile, JSON.stringify(gameDataJson, null, 2));

            // --- Update Last Visited Maps ---
            const mapId = gameDataJson.current_trainer_data?.position?.map_id;
            const mapName = gameDataJson.current_trainer_data?.position?.map_name;
            const lastVisitedMapsUpdated = updateLastVisitedMaps(mapId, mapName);
            if (lastVisitedMapsUpdated) {
                // Broadcast the updated list to connected clients
                // broadcast({
                //     type: 'last_visited_maps_update',
                //     payload: state.lastVisitedMaps
                // });
                console.log(`>>> LAST VISITED MAPS UPDATED: Now visiting ${mapName} (${mapId}) <<<`);
            }
            // --- End Last Visited Maps Update ---

            // --- Check for Badge Updates ---
            const currentBadges = gameDataJson.current_trainer_data?.badges || {}; // Handle potential missing badges
            if (currentBadges && typeof currentBadges === 'object' && !Array.isArray(currentBadges)) {
                const nowIso = new Date().toISOString();

                // Ensure badgeHistory contains *all* known badges (including not obtained yet).
                for (const [badgeId, rawHave] of Object.entries(currentBadges)) {
                    const have = Boolean(rawHave);
                    const existing = state.badgeHistory?.[badgeId];

                    if (existing && typeof existing === "object" && !Array.isArray(existing) && typeof existing.obtained === "boolean") {
                        // ok
                    } else if (existing && typeof existing === "object" && !Array.isArray(existing)) {
                        // Back-compat: old format stored only {step,timestamp} for obtained badges.
                        state.badgeHistory[badgeId] = {
                            obtained: true,
                            step: typeof existing.step === "number" ? existing.step : null,
                            timestamp: typeof existing.timestamp === "string" ? existing.timestamp : null,
                        };
                    } else {
                        state.badgeHistory[badgeId] = {
                            obtained: have,
                            step: have ? state.counters.currentStep : null,
                            timestamp: have ? nowIso : null,
                        };
                    }
                }

                // Only report "just obtained" when we're not inside a dialog / fight and the map is valid.
                if (!gameDataJson.is_talking_to_npc && !gameDataJson.is_in_battle && mapName != "0-0") {
                    for (const [badgeId, rawHave] of Object.entries(currentBadges)) {
                        const have = Boolean(rawHave);
                        if (have === true && !state.previousBadgesState[badgeId]) {
                            state.badgeHistory[badgeId] = {
                                obtained: true,
                                step: state.counters.currentStep,
                                timestamp: nowIso,
                            };
                            console.log(`>>> BADGE OBTAINED: ${badgeId} at step ${state.counters.currentStep} <<< `);
                            // broadcast({ type: 'badge_obtained', payload: { badgeName: badgeId, info: state.badgeHistory[badgeId] } });
                        }
                    }
                }

                // Update previous state for the next iteration.
                const nextPrev = {};
                for (const [badgeId, rawHave] of Object.entries(currentBadges)) {
                    nextPrev[badgeId] = Boolean(rawHave);
                }
                state.previousBadgesState = nextPrev;
            } else {
                console.warn("Badge data missing or invalid in gameDataJson.current_trainer_data");
            }
            // --- End Badge Update Check ---

            // --- Check for Map First Visit ---
            const currentMapId = gameDataJson.current_trainer_data?.position?.map_id;
            if (!state.mapVisitHistory[currentMapId] && currentMapId != "0-0") {
                const visitInfo = {
                    map_name: gameDataJson.current_trainer_data?.position?.map_name,
                    step: state.counters.currentStep,
                    timestamp: new Date().toISOString()
                };
                state.mapVisitHistory[currentMapId] = visitInfo;
                console.log(`>>> FIRST VISIT TO MAP: ${currentMapId} (${gameDataJson.current_trainer_data?.position?.map_name}) at step ${state.counters.currentStep} <<< `);
            }
            // --- End Map First Visit Check ---

            // --- Update Progress Steps ---
            const progressUpdated = updateProgressSteps(gameDataJson);
            if (progressUpdated) {
                console.log("Progress steps updated, saving state...");
                // Note: saveState will be called at the end of the loop anyway
            }
            // --- End Progress Steps Update ---

            // Broadcast full state update periodically or on significant changes
            // For simplicity, let's broadcast essential parts more often
            // const assistantHistoryLength = history.filter(item => item.type === "function_call").length;
            // console.log("Assistant history length:", assistantHistoryLength);
            const lastSummaryText = state.summaries.length > 0 ? state.summaries[state.summaries.length - 1].text : ""; // Get text from the last summary object
            const lastCriticism = fsSync.existsSync(config.paths.lastCriticismSaveFile) ? fsSync.readFileSync(config.paths.lastCriticismSaveFile, "utf8") : "";
            broadcast({
                type: 'full_state', // Or create specific update types
                payload: {
                    current_trainer_data: gameDataJson.current_trainer_data,
                    current_pokemon_data: gameDataJson.current_pokemon_data,
                    inventory_data: gameDataJson.inventory_data,
                    objectives: state.objectives,
                    is_talking_to_npc: gameDataJson.is_talking_to_npc,
                    flash_needed: gameDataJson.flash_needed,
                    flash_active: gameDataJson.flash_active,
                    visibility_reduced: gameDataJson.visibility_reduced,
                    visibility_window_width_tiles: gameDataJson.visibility_window_width_tiles,
                    visibility_window_height_tiles: gameDataJson.visibility_window_height_tiles,
                    memory: state.memory,
                    markers: state.markers,
                    progressSteps: state.progressSteps,
                    // Use new counter logic for remaining steps
                    remaining_until_criticism: Math.max(0, config.history.limitAssistantMessagesForSelfCriticism - (state.counters.currentStep - state.counters.lastCriticismStep)),
                    remaining_until_summary: Math.max(0, config.history.limitAssistantMessagesForSummary - (state.counters.currentStep - state.counters.lastSummaryStep)),
                    steps: state.counters.currentStep,
                    last_summary: lastSummaryText, // Use the variable derived from the state.summaries array
                    last_criticism: lastCriticism,
                    isThinking: state.isThinking,
                    safari_zone_counter: gameDataJson.safari_zone_counter,
                    safari_zone_active: gameDataJson.safari_zone_active,
                }
            });


            // 2. Build vision payload (raw screenshot x3 + optional overlay in overworld)
            const { image1Base64, image2Base64, error: visionError } = await buildVisionPayload(gameDataJson);
            if (!image1Base64) {
                console.error(`Could not build vision payload: ${visionError || "Unknown error"}. Pausing...`);
                await new Promise(resolve => setTimeout(resolve, 5000)); // Wait 5s
                continue;
            }
            // 3. Build the user input for the AI

            // --- Determine if Summary or Criticism is needed ---
            const stepsSinceLastCriticism = state.counters.currentStep - state.counters.lastCriticismStep;
            const stepsSinceLastSummary = state.counters.currentStep - state.counters.lastSummaryStep;
            const shouldSummarizeBasedOnSteps = stepsSinceLastSummary >= config.history.limitAssistantMessagesForSummary;
            const shouldSummarizeBasedOnTokens = state.lastTotalTokens >= config.openai.tokenLimit;
            const shouldSummarize = shouldSummarizeBasedOnSteps || shouldSummarizeBasedOnTokens; // <<< Updated condition


            // Check if the last history item is an EmptyActionError
            //   {
            //     "type": "function_call_output",
            //     "call_id": "call_RwlGoeTRZMoJLzb8C89RpAql",
            //     "output": "Tool call received with no actions to execute, it's forbidden to send an empty action."
            // }

            if (state.history.length > 0) {
                const lastHistoryItem = state.history[state.history.length - 1];
                if (lastHistoryItem.type === "function_call_output" && lastHistoryItem.output === "ERROR: Tool call received with no actions to execute, it's forbidden to send an empty action.") {
                    state.skipNextUserMessage = true;
                }
            }

            if (shouldSummarize) {
                setIsThinking(true);
                console.log(`Triggering summary. Reason: ${shouldSummarizeBasedOnSteps ? 'Steps limit reached' : ''}${shouldSummarizeBasedOnSteps && shouldSummarizeBasedOnTokens ? ' and ' : ''}${shouldSummarizeBasedOnTokens ? 'Token limit reached' : ''}.`); // Add logging
                const summaryPrompt = await fs.readFile(path.join(config.promptsDir, "summary.txt"), "utf8");

                const userInputText = await buildUserInputText(gameDataJson);
                // Broadcast the generated map
                // if (mapDisplayRef) {
                //     broadcast({ type: 'map_update', payload: mapDisplayRef });
                // }
                const newUserMessage = {
                    "role": "user",
                    "content": [
                        // { "type": "input_image", "image_url": `data:image/png;base64,${image1Base64}` },
                        // { "type": "input_image", "image_url": `data:image/png;base64,${image2Base64}` },
                        { "type": "input_text", "text": userInputText },
                        { "type": "input_text", "text": summaryPrompt + "\n\nDo your summary now ! Start your summary with <summary> tags and end it with </summary> tags. You will resume playing after the summary." }
                    ]
                };
                // history.push(newUserMessage);

                const developerPrompt = await buildDeveloperPrompt();
                const processedHistory = processHistoryForAPI(state.history); // Clean old messages
                const apiInput = [developerPrompt, ...processedHistory, newUserMessage];

                // <<< ADDED YIELD >>>
                await new Promise(setImmediate); // Allow event loop before potentially long API call

                // 5. Call the OpenAI API with streaming
                console.log("\n--- Making summary ---");
                // console.log("API Input (history size):", apiInput.length); // Debug

	                const summaryStart = Date.now();
	                const stream = await openai.responses.create({
	                    model: config.openai.model,
	                    service_tier: config.openai.service_tierSummary,
	                    input: apiInput,
	                    text: { format: { type: "text" } },
	                    reasoning: {
	                        effort: config.openai.reasoningEffortSummary,
	                        summary: config.openai.reasoningSummary,
                    },
                    max_output_tokens: 32000,
                    store: true, // Important to get call details in the final response

                    // store: false, // Important to get call details in the final response,
                    // include: ["reasoning.encrypted_content"],
                    stream: true,
                });

                let finalResponse = null;
                let summaryIsValid = false;
                let newSummaryText = "";
                try {

                    for await (const event of stream) {
                        switch (event.type) {
                            case "response.output_item.added":
                                if (event.item.type === "reasoning") console.log("\n=== Reasoning ===");
                                if (event.item.type === "message") {
                                    console.log("\n=== Text Response ===");
                                    broadcast({ type: 'summary_start', payload: 'Starting history summary...' });
                                }
                                if (event.item.type === "function_call") console.log("\n=== Tool Call ===");
                                break;
                            case "response.reasoning_summary_part.done":
                                broadcast({ type: 'reasoning_chunk', payload: "\n\n" }); // <<< Broadcast reasoning chunk
                                process.stdout.write("\n\n");
                                break;
                            case "response.output_item.done":
                                if (event.item.type === "reasoning" || event.item.type === "output_text") {
                                    console.log("--------------------");
                                }
                                break;
                            case "response.reasoning_summary_text.delta":
                                process.stdout.write(event.delta);
                                broadcast({ type: 'reasoning_chunk', payload: event.delta }); // <<< Broadcast reasoning chunk
                                break;
                            case "response.output_text.delta":
                                process.stdout.write(event.delta);
                                broadcast({ type: 'summary_chunk', payload: event.delta }); // <<< Broadcast summary chunk
                                break;
                            case "response.completed":
                                responseCompleted = true;
                                console.log("\n=== End of OpenAI Response ===");
                                console.log("Usage Tokens:", JSON.stringify(event.response.usage, null, 2));
                                finalResponse = event.response; // Store the final response
                                const summaryDuration = Date.now() - summaryStart;
	                                recordReasoning({
	                                    type: "summary",
	                                    model: config.openai.model,
	                                    serviceTier: config.openai.service_tierSummary,
	                                    durationMs: summaryDuration,
	                                });
	                                // <<< Calculate and log cost >>>
	                                const summaryCost = calculateRequestCost(event.response.usage, config.openai.model, config.openai.tokenPrice, config.openai.service_tierSummary);
	                                if (summaryCost !== null) {
	                                    console.log(`Estimated Cost: $${summaryCost.fullCost} (Discounted: $${summaryCost.discountedCost})`);
	                                    broadcast({ type: 'token_usage', payload: { ...event.response.usage, cost: summaryCost.fullCost, discountedCost: summaryCost.discountedCost } }); // Include cost
	                                    recordLoopUsage({ callType: "summary", usage: event.response.usage, cost: summaryCost, model: config.openai.model, serviceTier: config.openai.service_tierSummary });
	                                } else {
	                                    broadcast({ type: 'token_usage', payload: event.response.usage }); // Broadcast usage even if cost fails
	                                    recordLoopUsage({ callType: "summary", usage: event.response.usage, cost: null, model: config.openai.model, serviceTier: config.openai.service_tierSummary });
	                                }
	                                // console.log(JSON.stringify(event.response.output, null, 2)); // Less verbose
	                                // Extract summary text (do not persist yet; we may roll it up before saving)
	                                const summaryItem = event.response.output.find(item => item.type === "message");
	                                newSummaryText = summaryItem?.content?.find(item => item.type === "output_text")?.text || "[Summary Error]";
                                // If the summary doesn't contain <summary> tags, try again
                                if (newSummaryText.includes("<summary>") && newSummaryText.includes("</summary>")) {
                                    summaryIsValid = true;
                                }

                                broadcast({ type: 'summary_end', payload: 'History summary finished.' });
                                break;
                            case "error":
                                console.error("\n--- OpenAI Stream Error ---");
                                console.error(event.error);
                                if (!responseCompleted) {
                                    broadcast({ type: 'error_message', payload: `OpenAI Stream Error: ${event.error?.message || 'Unknown error'}` }); // <<< Broadcast API error
                                    throw new Error(`OpenAI Stream Error: ${event.error?.message || 'Unknown error'}`); // Stop in case of API error
                                }
                            default:
                                // console.log("Unknown event type:", event.type);
                                break;
                            // Add other cases if necessary (e.g., response.input_processed)
                        }
                    }
                } catch (streamError) {
                    if (!responseCompleted) {
                        console.error("\n--- OpenAI Stream Processing Error ---");
                        console.error(streamError);
                        broadcast({ type: 'error_message', payload: `OpenAI Stream Processing Error: ${streamError?.message || 'Unknown error'}` });
                        throw streamError; // Re-throw if we didn't complete successfully
                    } else {
                        console.warn("Stream processing error occurred after response completion - ignoring and removing reasoning fields:", streamError?.message);

                        // Remove reasoning fields from the response output
                        if (finalResponse?.output && Array.isArray(finalResponse.output)) {
                            finalResponse.output = finalResponse.output.filter(item => item.type !== "reasoning");
                        }

                        // Remove all the "id" fields from the response output
                        if (finalResponse?.output && Array.isArray(finalResponse.output)) {
                            finalResponse.output = finalResponse.output.map(item => {
                                if (item.id) delete item.id;
                                return item;
                            });
                        }
                    }
                }

                if (!summaryIsValid) {
                    console.log("Summary is not valid, trying again...");
                    continue;
                }

                // Persist summary (and rollup if we reached the threshold) BEFORE saving summaries.json / rewriting history.json.
                const summaryTimestamp = new Date().toISOString();
                const baseSummaryEntry = {
                    text: newSummaryText,
                    step: state.counters.currentStep,
                    timestamp: summaryTimestamp,
                };

                const existingAllSummaries = Array.isArray(state.allSummaries) ? state.allSummaries : [];
                const existingSummaries = Array.isArray(state.summaries) ? state.summaries : [];

                const nextAllSummaries = [...existingAllSummaries, { ...baseSummaryEntry, kind: "summary" }];
                const nextSummaries = [...existingSummaries, baseSummaryEntry];

                let finalSummaries = nextSummaries;
                let rolledUpText = null;

                if (nextSummaries.length >= 10) {
                    console.log(`Summaries reached ${nextSummaries.length}; running summary rollup...`);
                    broadcast({ type: 'summary_rollup_start', payload: { count: nextSummaries.length } });

                    try {
                        const rollupPrompt = await fs.readFile(path.join(config.promptsDir, "summary_rollup.txt"), "utf8");
                        const rollupInputText =
                            rollupPrompt +
                            "\n\n" +
                            nextSummaries
                                .map(
                                    (s, i) =>
                                        `=== SUMMARY ${i + 1}/${nextSummaries.length} ===\n${s.text}`
                                )
                                .join("\n\n");

                        const rollupStart = Date.now();
                        const rollupStream = await openai.responses.create({
                            model: config.openai.model,
                            service_tier: config.openai.service_tierSummary,
                            input: [
                                {
                                    role: "user",
                                    content: [{ type: "input_text", text: rollupInputText }],
                                },
                            ],
                            text: { format: { type: "text" } },
                            reasoning: {
                                effort: "xhigh",
                                summary: config.openai.reasoningSummary,
                            },
                            max_output_tokens: 64000,
                            store: true,
                            stream: true,
                        });
                        let rollupResponseCompleted = false;
                        let rollupFinalResponse = null;

                        let rollupTextAccum = "";
                        try {
                            for await (const event of rollupStream) {
                                switch (event.type) {
                                    case "response.output_item.added":
                                        if (event.item.type === "reasoning") console.log("\n=== Rollup Reasoning ===");
                                        if (event.item.type === "message") {
                                            console.log("\n=== Rollup Text Response ===");
                                            // Reuse summary broadcast keys so the frontend can render live.
                                            broadcast({ type: 'summary_start', payload: 'Starting summary rollup...' });
                                        }
                                        break;
                                    case "response.reasoning_summary_part.done":
                                        broadcast({ type: 'reasoning_chunk', payload: "\n\n" });
                                        process.stdout.write("\n\n");
                                        break;
                                    case "response.reasoning_summary_text.delta":
                                        process.stdout.write(event.delta);
                                        broadcast({ type: 'reasoning_chunk', payload: event.delta });
                                        break;
                                    case "response.output_text.delta":
                                        process.stdout.write(event.delta);
                                        rollupTextAccum += event.delta;
                                        broadcast({ type: 'summary_chunk', payload: event.delta });
                                        break;
                                    case "response.output_item.done":
                                        if (event.item.type === "reasoning" || event.item.type === "output_text") {
                                            console.log("--------------------");
                                        }
                                        break;
                                    case "response.completed":
                                        rollupResponseCompleted = true;
                                        rollupFinalResponse = event.response;
                                        console.log("\n=== End of Rollup Response ===");
                                        console.log("Rollup Usage Tokens:", JSON.stringify(event.response.usage, null, 2));

                                        {
                                            const rollupDuration = Date.now() - rollupStart;
                                            recordReasoning({
                                                type: "summary_rollup",
                                                model: config.openai.model,
                                                serviceTier: config.openai.service_tierSummary,
                                                durationMs: rollupDuration,
                                            });

                                            const rollupCost = calculateRequestCost(
                                                event.response.usage,
                                                config.openai.model,
                                                config.openai.tokenPrice,
                                                config.openai.service_tierSummary
                                            );
                                            if (rollupCost !== null) {
                                                console.log(
                                                    `Estimated Rollup Cost: $${rollupCost.fullCost} (Discounted: $${rollupCost.discountedCost})`
                                                );
                                                broadcast({
                                                    type: 'token_usage',
                                                    payload: { ...event.response.usage, cost: rollupCost.fullCost, discountedCost: rollupCost.discountedCost },
                                                });
                                                recordLoopUsage({
                                                    callType: "summary_rollup",
                                                    usage: event.response.usage,
                                                    cost: rollupCost,
                                                    model: config.openai.model,
                                                    serviceTier: config.openai.service_tierSummary,
                                                });
                                            } else {
                                                broadcast({ type: 'token_usage', payload: event.response.usage });
                                                recordLoopUsage({
                                                    callType: "summary_rollup",
                                                    usage: event.response.usage,
                                                    cost: null,
                                                    model: config.openai.model,
                                                    serviceTier: config.openai.service_tierSummary,
                                                });
                                            }
                                        }

                                        broadcast({ type: 'summary_end', payload: 'Summary rollup finished.' });
                                        break;
                                    case "error":
                                        console.error("\n--- Rollup Stream Error ---");
                                        console.error(event.error);
                                        if (!rollupResponseCompleted) {
                                            broadcast({
                                                type: 'error_message',
                                                payload: `OpenAI Rollup Stream Error: ${event.error?.message || 'Unknown error'}`,
                                            });
                                            throw new Error(
                                                `OpenAI Rollup Stream Error: ${event.error?.message || 'Unknown error'}`
                                            );
                                        }
                                    default:
                                        break;
                                }
                            }
                        } catch (rollupStreamError) {
                            if (!rollupResponseCompleted) {
                                console.error("\n--- Rollup Stream Processing Error ---");
                                console.error(rollupStreamError);
                                broadcast({
                                    type: 'error_message',
                                    payload: `OpenAI Rollup Stream Processing Error: ${rollupStreamError?.message || 'Unknown error'}`,
                                });
                                throw rollupStreamError;
                            } else {
                                console.warn(
                                    "Rollup stream error occurred after completion - ignoring:",
                                    rollupStreamError?.message
                                );
                            }
                        }

                        if (!rollupFinalResponse) {
                            throw new Error("No final rollup response received from the OpenAI API after the stream.");
                        }

                        const rollupMessage = Array.isArray(rollupFinalResponse.output)
                            ? rollupFinalResponse.output.find((item) => item.type === "message")
                            : null;
                        const rollupText =
                            rollupMessage?.content?.find((item) => item.type === "output_text")?.text || rollupTextAccum;

                        if (rollupText.includes("<summary>") && rollupText.includes("</summary>")) {
                            rolledUpText = rollupText;

                            const rollupTimestamp = new Date().toISOString();
                            const rollupEntry = {
                                text: rolledUpText,
                                step: state.counters.currentStep,
                                timestamp: rollupTimestamp,
                            };

                            nextAllSummaries.push({
                                ...rollupEntry,
                                kind: "rollup",
                                sourceCount: nextSummaries.length,
                            });
                            finalSummaries = [rollupEntry];

                            // Replace the summary content that will be written into history.json.
                            if (finalResponse?.output && Array.isArray(finalResponse.output)) {
                                const msgItem = finalResponse.output.find((item) => item.type === "message");
                                const outTextItem = msgItem?.content?.find((c) => c.type === "output_text");
                                if (outTextItem) outTextItem.text = rolledUpText;
                            }

                            console.log("Summary rollup succeeded; compacting summaries to a single rolled-up entry.");
                        } else {
                            console.warn("Summary rollup produced invalid output; keeping original summary and full summaries list.");
                        }
                    } catch (rollupError) {
                        console.error("Summary rollup failed; keeping original summary and full summaries list:", rollupError);
                    } finally {
                        broadcast({ type: 'summary_rollup_end', payload: { ok: Boolean(rolledUpText) } });
                    }
                }

                state.allSummaries = nextAllSummaries;
                state.summaries = finalSummaries;
                console.log(
                    `Summary stored. summaries=${state.summaries.length}, allSummaries=${state.allSummaries.length}`
                );
                state.lastTotalTokens = 0;

                // TODO: Save the old history in a backup folder and replace the whole history with the summary
                const backupFolder = "backup";
                if (!fsSync.existsSync(backupFolder)) {
                    fsSync.mkdirSync(backupFolder, { recursive: true });
                }
                const backupFile = path.join(backupFolder, `history_backup_${Date.now()}.json`);
                fsSync.writeFileSync(backupFile, JSON.stringify(state.history, null, 2));

                // Replace the whole history with the summary
                state.history = [];
                // Always include the last summary in the history, to have more context
                // We keep the last summary in the history + the new summary
                // if (lastSummary) {
                //     history.push({
                //         "role": "assistant",
                //         "content": [{ "type": "output_text", "text": lastSummary }]
                //     });
                // }
                // Get the last 2 state.summaries before the current one
                const lastTwoSummaries = state.summaries.slice(0, -1).slice(-2);

                console.log(`Adding ${lastTwoSummaries.length} last state.summaries to history.`);

                // // Add the last 2 state.summaries to history
                // lastTwoSummaries.forEach(summary => {
                //     state.history.push({
                //         "role": "assistant",
                //         "content": [{ "type": "output_text", "text": summary.text }]
                //     });
                // });

                if (finalResponse?.output) {
                    finalResponse.output.forEach(item => {
                        state.history.push(item); // Add the item (potentially modified) to the history
                    });
                }

                // Add a user message to the history to remind the AI to play the game
                state.history.push({
                    "role": "user",
                    "content": [
                        { "type": "input_text", "text": "<system>Resume your gameplay now !</system>" }
                    ]
                });
                state.skipNextUserMessage = true;

                state.counters.lastSummaryStep = state.counters.currentStep; // Update last summary step
                // Update also the lastCriticismStep
                state.counters.lastCriticismStep = state.counters.currentStep;
                // REMOVED: selfCriticismDone = false;
                // Save the new history and state.counters
                await savePersistentState();
                continue; // Skip the rest of the loop for summary turn

            } else if (!state.skipNextUserMessage) { // <<< Check the flag BEFORE creating newUserMessage
                const userInputText = await buildUserInputText(gameDataJson);
                const lastHistoryItem = state.history.length > 0 ? state.history[state.history.length - 1] : null;
                const canExtendLastToolOutput = lastHistoryItem?.type === "function_call_output" && Array.isArray(lastHistoryItem.output);
                // console.log("User input text:", userInputText);
                // Broadcast the generated map
                // if (mapDisplayRef) {
                //     broadcast({ type: 'map_update', payload: mapDisplayRef });
                // }

                if (canExtendLastToolOutput) {
                    const appendedOutputItems = [];

                    appendedOutputItems.push({ "type": "input_image", "image_url": `data:image/png;base64,${image1Base64}` });
                    if (image2Base64) {
                        appendedOutputItems.push({ "type": "input_image", "image_url": `data:image/png;base64,${image2Base64}` });
                    }
                    appendedOutputItems.push({ "type": "input_text", "text": userInputText });

                    lastHistoryItem.output.push(...appendedOutputItems);
                    console.log("Appended inputs to last function_call_output entry.");
                } else {
                    // Broadcast the generated map
                    // if (mapDisplayRef) {
                    //     broadcast({ type: 'map_update', payload: mapDisplayRef });
                    // }
                    const content = [{ "type": "input_image", "image_url": `data:image/png;base64,${image1Base64}` }];
                    if (image2Base64) {
                        content.push({ "type": "input_image", "image_url": `data:image/png;base64,${image2Base64}` });
                    }
                    content.push({ "type": "input_text", "text": userInputText });
                    newUserMessage = { "role": "user", "content": content };
                    console.log("Created newUserMessage for this step.");
                }
            } else {
                newUserMessage = null; // Ensure it's null if skipped
                console.log("Skipping creation of newUserMessage due to skipNextUserMessage flag.");
            }
            setIsThinking(true);

            // 4. Prepare the complete input for the OpenAI API
            const developerPrompt = await buildDeveloperPrompt();
            const processedHistory = processHistoryForAPI(newUserMessage ? [...state.history, newUserMessage] : state.history); // Clean old messages
            const apiInput = [developerPrompt, ...processedHistory];
            const tools = defineTools();

            // 5. Call the OpenAI API with streaming
            console.log("\n--- Sending to OpenAI ---");
            // console.log("API Input (history size):", apiInput.length); // Debug


            // Only criticize if enough steps have passed AND we are not summarizing this turn
            const shouldCriticize = stepsSinceLastCriticism >= config.history.limitAssistantMessagesForSelfCriticism;
            if (shouldCriticize) { // Use the pre-calculated flag and remove assistantHistoryLength check
                const selfCriticismPrompt = await fs.readFile(path.join(config.promptsDir, "self_criticism.txt"), "utf8");
                const newUserMessage = {
                    "role": "user",
                    "content": [
                        { "type": "input_text", "text": selfCriticismPrompt }
                    ]
                };
                // history.push(newUserMessage);

                const apiInputCriticism = [...apiInput, newUserMessage];

                // <<< ADDED YIELD >>>
                await new Promise(setImmediate); // Allow event loop before potentially long API call

                // 5. Call the OpenAI API with streaming
                console.log("\n--- Making self-criticism ---");
                // console.log("API Input (history size):", apiInput.length); // Debug

	                const criticismStart = Date.now();
	                const stream = await openai.responses.create({
	                    model: config.openai.model,
	                    service_tier: config.openai.service_tierSelfCriticism,
	                    input: apiInputCriticism,
	                    text: { format: { type: "text" } },
	                    reasoning: {
	                        effort: config.openai.reasoningEffortCriticism,
	                        summary: config.openai.reasoningSummary,
                    },
                    max_output_tokens: 32000,
                    store: true, // Important to get call details in the final response
                    // store: false, // Important to get call details in the final response,
                    // include: ["reasoning.encrypted_content"],
                    stream: true,
                });

                let finalResponse = null;
                try {

                    for await (const event of stream) {
                        switch (event.type) {
                            case "response.output_item.added":
                                if (event.item.type === "reasoning") {
                                    console.log("\n=== Reasoning ===");
                                }
                                if (event.item.type === "message") {
                                    console.log("\n=== Text Response ===");
                                    broadcast({ type: 'criticism_start', payload: 'Starting self-criticism...' });
                                }
                                if (event.item.type === "function_call") console.log("\n=== Tool Call ===");
                                break;
                            case "response.reasoning_summary_part.done":
                                broadcast({ type: 'reasoning_chunk', payload: "\n\n" }); // <<< Broadcast reasoning chunk
                                process.stdout.write("\n\n");
                                break;
                            case "response.output_item.done":
                                if (event.item.type === "reasoning" || event.item.type === "output_text") {
                                    console.log("--------------------");
                                }
                                break;
                            case "response.reasoning_summary_text.delta":
                                process.stdout.write(event.delta);
                                broadcast({ type: 'reasoning_chunk', payload: event.delta }); // <<< Broadcast reasoning chunk
                                break;
                            case "response.output_text.delta":
                                process.stdout.write(event.delta);
                                broadcast({ type: 'criticism_chunk', payload: event.delta }); // <<< Broadcast criticism chunk
                                break;
                            case "response.completed":
                                responseCompleted = true;
                                console.log("\n=== End of OpenAI Response ===");
                                console.log("Usage Tokens:", JSON.stringify(event.response.usage, null, 2));
                                finalResponse = event.response; // Store the final response
                                const criticismDuration = Date.now() - criticismStart;
	                                recordReasoning({
	                                    type: "self_criticism",
	                                    model: config.openai.model,
	                                    serviceTier: config.openai.service_tierSelfCriticism,
	                                    durationMs: criticismDuration,
	                                });
	                                // <<< Calculate and log cost >>>
	                                const criticismCost = calculateRequestCost(event.response.usage, config.openai.model, config.openai.tokenPrice, config.openai.service_tierSelfCriticism);
	                                if (criticismCost !== null) {
	                                    console.log(`Estimated Cost: $${criticismCost.fullCost} (Discounted: $${criticismCost.discountedCost})`);
	                                    broadcast({ type: 'token_usage', payload: { ...event.response.usage, cost: criticismCost.fullCost, discountedCost: criticismCost.discountedCost } }); // Include cost
	                                    recordLoopUsage({ callType: "self_criticism", usage: event.response.usage, cost: criticismCost, model: config.openai.model, serviceTier: config.openai.service_tierSelfCriticism });
	                                } else {
	                                    broadcast({ type: 'token_usage', payload: event.response.usage }); // Broadcast usage even if cost fails
	                                    recordLoopUsage({ callType: "self_criticism", usage: event.response.usage, cost: null, model: config.openai.model, serviceTier: config.openai.service_tierSelfCriticism });
	                                }
	                                // console.log(JSON.stringify(event.response.output, null, 2)); // Less verbose
	                                // Save the criticism to the text file "last_criticism.txt"
	                                const criticismItem = event.response.output.find(item => item.type === "message");
	                                const criticismText = criticismItem?.content?.find(item => item.type === "output_text")?.text || "[Criticism Error]";
                                fsSync.writeFileSync(config.paths.lastCriticismSaveFile, criticismText);
                                broadcast({ type: 'criticism_end', payload: 'Self-criticism finished.' });
                                break;
                            case "error":
                                console.error("\n--- OpenAI Stream Error ---");
                                console.error(event.error);
                                if (!responseCompleted) {
                                    broadcast({ type: 'error_message', payload: `OpenAI Stream Error: ${event.error?.message || 'Unknown error'}` }); // <<< Broadcast API error
                                    throw new Error(`OpenAI Stream Error: ${event.error?.message || 'Unknown error'}`); // Stop in case of API error
                                }
                            default:
                                // console.log("Unknown event type:", event.type);
                                console.log("Event:", JSON.stringify(event, null, 2));
                                break;
                            // Add other cases if necessary (e.g., response.input_processed)
                        }
                    }
                } catch (streamError) {
                    if (!responseCompleted) {
                        console.error("\n--- OpenAI Stream Processing Error ---");
                        console.error(streamError);
                        broadcast({ type: 'error_message', payload: `OpenAI Stream Processing Error: ${streamError?.message || 'Unknown error'}` });
                        throw streamError; // Re-throw if we didn't complete successfully
                    } else {
                        console.warn("Stream processing error occurred after response completion - ignoring and removing reasoning fields:", streamError?.message);
                        // Remove reasoning fields from the response output
                        if (finalResponse?.output && Array.isArray(finalResponse.output)) {
                            finalResponse.output = finalResponse.output.filter(item => item.type !== "reasoning");
                        }

                        // Remove all the "id" fields from the response output
                        if (finalResponse?.output && Array.isArray(finalResponse.output)) {
                            finalResponse.output = finalResponse.output.map(item => {
                                if (item.id) delete item.id;
                                return item;
                            });
                        }
                    }
                }

                if (finalResponse?.output) {
                    finalResponse.output.forEach(item => {
                        state.history.push(item); // Add the item (potentially modified) to the history
                        apiInput.push(item);
                    });
                }

                // Save the new history
                state.counters.lastCriticismStep = state.counters.currentStep; // Update last criticism step
                state.selfCritiqueReminderPending = true; // Flag reminder for the next actionable step
                await savePersistentState();
                continue; // Skip the rest of the loop for criticism turn
            }


            let reasoningEffort = config.openai.reasoningEffort;
            if (gameDataJson.is_talking_to_npc) {
                reasoningEffort = config.openai.reasoningEffortDialog;
            }
            if (gameDataJson.battle_data?.in_battle) {
                reasoningEffort = config.openai.reasoningEffortBattle;
            }
            console.log("reasoningEffort:", reasoningEffort);
            const mainCallStart = Date.now();
            const stream = await openai.responses.create({
                model: config.openai.model,
                service_tier: config.openai.service_tier,
                input: apiInput,
                text: { format: { type: "text" } },
                reasoning: {
                    effort: reasoningEffort,
                    summary: config.openai.reasoningSummary,
                },
                tools: tools,
                tool_choice: "required",
                parallel_tool_calls: false,
                max_output_tokens: 32000,
                store: true, // Important to get call details in the final response,
                // store: false, // Important to get call details in the final response,
                // include: ["reasoning.encrypted_content"],
                stream: true,
            });

            // 6. Process the streamed response
            let currentReasoning = "";
            let currentOutputText = "";
            let finalResponse = null; // Reset finalResponse for the new call
            try {

                for await (const event of stream) {
                    switch (event.type) {
                        case "response.output_item.added":
                            if (event.item.type === "reasoning") console.log("\n=== Reasoning ===");
                            if (event.item.type === "message") console.log("\n=== Text Response ===");
                            if (event.item.type === "function_call") console.log("\n=== Tool Call ===");
                            break;
                        case "response.reasoning_summary_part.done":
                            broadcast({ type: 'reasoning_chunk', payload: "\n\n" }); // <<< Broadcast reasoning chunk
                            process.stdout.write("\n\n");
                            break;
                        case "response.output_item.done":
                            if (event.item.type === "reasoning" || event.item.type === "output_text") {
                                console.log("--------------------");
                            }
                            break;
                        case "response.reasoning_summary_text.delta":
                            process.stdout.write(event.delta);
                            currentReasoning += event.delta;
                            broadcast({ type: 'reasoning_chunk', payload: event.delta }); // <<< Broadcast reasoning chunk
                            break;
                        case "response.output_text.delta":
                            process.stdout.write(event.delta);
                            broadcast({ type: 'reasoning_chunk', payload: event.delta }); // <<< Broadcast reasoning chunk
                            currentOutputText += event.delta;
                            break;
                        case "response.completed":
                            responseCompleted = true;
                            console.log("\n=== End of OpenAI Response ===");
                            console.log("Usage Tokens:", JSON.stringify(event.response.usage, null, 2));
                            finalResponse = event.response; // Store the final response
                            const mainDuration = Date.now() - mainCallStart;
                            recordReasoning({
                                type: "main",
                                model: config.openai.model,
                                serviceTier: config.openai.service_tier,
                                durationMs: mainDuration,
                            });
                            // <<< Calculate and log cost >>>
                            const requestCost = calculateRequestCost(event.response.usage, config.openai.model, config.openai.tokenPrice, config.openai.service_tier);
                            if (requestCost !== null) {
                                console.log(`Estimated Cost: $${requestCost.fullCost} (Discounted: $${requestCost.discountedCost})`);
                                broadcast({ type: 'token_usage', payload: { ...event.response.usage, cost: requestCost.fullCost, discountedCost: requestCost.discountedCost } }); // Include cost
                                recordLoopUsage({ callType: "main", usage: event.response.usage, cost: requestCost, model: config.openai.model, serviceTier: config.openai.service_tier });
                            } else {
                                broadcast({ type: 'token_usage', payload: event.response.usage }); // Broadcast usage even if cost fails
                                recordLoopUsage({ callType: "main", usage: event.response.usage, cost: null, model: config.openai.model, serviceTier: config.openai.service_tier });
                            }
                            broadcast({ type: 'reasoning_end', payload: null }); // <<< Signal end of reasoning stream
                            if (event.response.usage?.total_tokens) {
                                state.lastTotalTokens = event.response.usage.total_tokens; // <<< Update lastTotalTokens
                                console.log(`Updated lastTotalTokens: ${state.lastTotalTokens}`); // Add logging
                            } else {
                                console.warn("Could not read total_tokens from API response usage.");
                            }
                            break;
                        case "error":
                            console.error("\n--- OpenAI Stream Error ---");
                            console.error(event.error);
                            if (!responseCompleted) {
                                broadcast({ type: 'error_message', payload: `OpenAI Stream Error: ${event.error?.message || 'Unknown error'}` }); // <<< Broadcast API error
                                throw new Error(`OpenAI Stream Error: ${event.error?.message || 'Unknown error'}`); // Stop in case of API error
                            }
                        default:
                            // console.log("Unknown event type:", event.type);
                            break;
                        // Add other cases if necessary (e.g., response.input_processed)
                    }
                }
            } catch (streamError) {
                if (!responseCompleted) {
                    console.error("\n--- OpenAI Stream Processing Error ---");
                    console.error(streamError);
                    broadcast({ type: 'error_message', payload: `OpenAI Stream Processing Error: ${streamError?.message || 'Unknown error'}` });
                    throw streamError; // Re-throw if we didn't complete successfully
                } else {
                    console.warn("Stream processing error occurred after response completion - ignoring and removing reasoning fields:", streamError?.message);

                    // Remove reasoning fields from the response output
                    if (finalResponse?.output && Array.isArray(finalResponse.output)) {
                        finalResponse.output = finalResponse.output.filter(item => item.type !== "reasoning");
                    }
                    // Remove all the "id" fields from the response output
                    if (finalResponse?.output && Array.isArray(finalResponse.output)) {
                        finalResponse.output = finalResponse.output.map(item => {
                            if (item.id) delete item.id;
                            return item;
                        });
                    }
                }
            }

            // 7. Process the final response (after the stream)
            if (!finalResponse) {
                throw new Error("No final response received from the OpenAI API after the stream.");
            }
            if (!state.skipNextUserMessage && newUserMessage) {
                state.history.push(newUserMessage);
            }
            setIsThinking(false);
            // Add response elements (reasoning, message, function call) to history
            // Handle reasoning replacement logic if necessary (WARNING: fragile)
            // let lastThinkingForReplacement = currentReasoning; // Use the streamed reasoning // Removed replacement logic
            if (finalResponse.output) {
                finalResponse.output.forEach(item => {
                    // Specific logic to replace 'reasoning' in tool args REMOVED
                    state.history.push(item); // Add the item to the history
                });
            }

            state.skipNextUserMessage = false; // Reset the flag after processing the final response, handleToolCall will set it again if needed
            let haveToolCall = false;
            // 8. Execute tool calls and add results to history
            if (finalResponse.output) {
                for (const item of finalResponse.output) {
                    if (item.type === "function_call") {
                        haveToolCall = true;
                        // Pass gameDataJson AND the call_id (which is item.id)
                        setIsThinking(false);
                        const toolResult = await handleToolCall(item, gameDataJson);
                        state.history.push(toolResult); // Add the tool result to the history
                    }
                }
            }
            if (!haveToolCall) {
                // Add a message to the history to remind the player to use tools
                state.history.push({
                    "role": "user",
                    "content": [
                        { "type": "input_text", "text": "<system>You must include tools in your response ! Always call 'execute_action' tool with your messages to continue your actions !</system>" }
                    ]
                });
                state.skipNextUserMessage = true;
            }
            state.counters.currentStep++;
            console.log(`Step counter incremented to: ${state.counters.currentStep}`);
            if (state.selfCritiqueReminderAcknowledged) {
                state.selfCritiqueReminderPending = false; // Reminder satisfied after completing an action step
            }

            // Reset lastTotalTokens *after* a successful step (including summary/criticism steps which `continue`)
            // This ensures the token count from the *just completed* step is used for the *next* step's check.
            // If a summary happened due to tokens, we need to reset it.
            if (shouldSummarize) {
                state.lastTotalTokens = 0; // Reset after a summary is completed
                console.log("Reset lastTotalTokens after summary.");
            }
            setIsThinking(false);
            // 9. Save state (history, state.memory)
            await savePersistentState();


        } catch (error) {
            console.error("\n--- ERROR IN MAIN LOOP ---");
            console.error(error);
            console.error("Pausing for 10 seconds before retrying...");
            const downDuration = Date.now() - loopStartTime;
            recordDownTime(downDuration);
            broadcast({ type: 'error_message', payload: `Main loop error: ${error.message}` }); // <<< Broadcast loop error
            // Save state even in case of error (can be useful for debugging)
            // try {
            //     await savePersistentState();
            // } catch (saveError) {
            //     console.error("Error saving state during loop error handling:", saveError);
            // }
            await new Promise(resolve => setTimeout(resolve, 10000));
        } finally {
            const totalDuration = Date.now() - loopStartTime;
            recordTotal(totalDuration);
            await flush({ step: state.counters.currentStep, timestamp: new Date().toISOString() });
            await flushTime({ step: state.counters.currentStep, timestamp: new Date().toISOString() });
            // Always yield back to the event loop so WS handshakes are never starved
            await new Promise(setImmediate);
        }
    }
}

// --- Startup ---


module.exports = { gameLoop };
