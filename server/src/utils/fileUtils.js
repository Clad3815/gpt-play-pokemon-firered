const fs = require("fs").promises;
const path = require("path");
const { config } = require("../config");

async function readImageAsBase64(relativePath) {
  const fullPath = path.join(config.paths.baseDir, relativePath);
  try {
    const imageBuffer = await fs.readFile(fullPath);
    return imageBuffer.toString("base64");
  } catch (error) {
    console.error(`Error reading image ${fullPath}:`, error.message);
    return null;
  }
}

module.exports = { readImageAsBase64 };

