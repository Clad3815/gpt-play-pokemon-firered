const OpenAI = require("openai");
const { config } = require("../config");

const openai = new OpenAI({
  apiKey: config.openai.apiKey,
  timeout: config.openai.timeout,
});

module.exports = { openai };

