const { state } = require("../state/stateManager");

function updateProgressSteps(gameDataJson) {
  if (!Array.isArray(state.progressSteps) || state.progressSteps.length === 0) {
    return false;
  }

  const currentTimestamp = new Date().toISOString();
  let hasUpdates = false;

  for (const step of state.progressSteps) {
    if (step.done) continue;

    let shouldMarkDone = false;

    if (step.type === "map_visit") {
      const currentMapName = gameDataJson?.current_trainer_data?.position?.map_name;
      if (currentMapName && currentMapName === step.trigger) {
        console.log(`>>> PROGRESS: Map visit step "${step.label}" completed (${step.trigger}) <<<`);
        shouldMarkDone = true;
      }
    } else if (step.type === "badge") {
      const currentBadges = gameDataJson?.current_trainer_data?.badges || {};
      if (currentBadges && typeof currentBadges === "object" && currentBadges[step.trigger] === true) {
        console.log(`>>> PROGRESS: Badge step "${step.label}" completed (${step.trigger}) <<<`);
        shouldMarkDone = true;
      }
    } else if (step.type === "event") {
      const importantEvents = gameDataJson?.important_events || {};
      if (importantEvents && typeof importantEvents === "object" && importantEvents[step.trigger] === true) {
        console.log(`>>> PROGRESS: Event step "${step.label}" completed (${step.trigger}) <<<`);
        shouldMarkDone = true;
      }
    } else {
      console.warn(`Unknown progress step type: ${step.type} for step ${step.id}`);
    }

    if (shouldMarkDone) {
      step.done = true;
      step.done_on = currentTimestamp;
      hasUpdates = true;
    }
  }

  return hasUpdates;
}

function updateLastVisitedMaps(currentMapId, currentMapName) {
  if (currentMapId == null || currentMapId === "0-0") {
    return false;
  }

  if (state.lastVisitedMaps.length > 0 && state.lastVisitedMaps[0].map_id === currentMapId) {
    return false;
  }

  const mapEntry = {
    map_id: currentMapId,
    map_name: currentMapName || `Unknown Map (${currentMapId})`,
    timestamp: new Date().toISOString(),
    step: state.counters.currentStep,
  };

  state.lastVisitedMaps = state.lastVisitedMaps.filter((entry) => entry.map_id !== currentMapId);
  state.lastVisitedMaps.unshift(mapEntry);
  state.lastVisitedMaps = state.lastVisitedMaps.slice(0, 7);

  console.log(`>>> LAST VISITED MAPS UPDATED: Now visiting ${currentMapName} (${currentMapId}) <<<`);
  return true;
}

module.exports = { updateProgressSteps, updateLastVisitedMaps };
