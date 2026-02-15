function calculateRequestCost(usage, modelName, priceConfig, serviceTier) {
  if (!usage || !priceConfig[modelName]) {
    console.warn("Could not calculate cost: Missing usage data or price config for model:", modelName);
    return null;
  }

  const prices = priceConfig[modelName];
  const inputTokens = usage.input_tokens || 0;
  const cachedInputTokens = usage.input_tokens_details?.cached_tokens || 0;
  const outputTokens = usage.output_tokens || 0;

  const nonCachedInputTokens = inputTokens - cachedInputTokens;
  const inputPrice = prices.input ?? 0;
  const cachedInputPrice = prices.cached_input ?? inputPrice;
  const outputPrice = prices.output ?? 0;

  const inputCost =
    (nonCachedInputTokens / 1_000_000) * inputPrice +
    (cachedInputTokens / 1_000_000) * cachedInputPrice;
  const outputCost = (outputTokens / 1_000_000) * outputPrice;

  const totalCost = inputCost + outputCost;
  const fullCost = parseFloat(totalCost.toFixed(6));

  let discountedCost;
  if (serviceTier === "flex") {
    discountedCost = parseFloat((totalCost * 0.5).toFixed(6));
  } else if (serviceTier === "priority") {
    discountedCost = parseFloat((totalCost * 2).toFixed(6));
  } else {
    discountedCost = fullCost;
  }

  return { fullCost, discountedCost };
}

module.exports = { calculateRequestCost };

