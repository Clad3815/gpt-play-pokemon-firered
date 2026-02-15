const fs = require("fs").promises;
const path = require("path");
const sharp = require("sharp");

function isOverworld(gameDataJson) {
  return !gameDataJson?.is_talking_to_npc && !gameDataJson?.battle_data?.in_battle;
}

function clamp(n, min, max) {
  return Math.max(min, Math.min(max, n));
}

function tileCodeToColor(code) {
  // Deterministic palette for borders (no gameplay logic).
  const c = Number(code);
  if (!Number.isFinite(c)) return "#888888";
  const hue = (c * 47) % 360;
  return `hsl(${hue} 70% 55%)`;
}

function estimateLabelStyle({ label, cellW, cellH, scale, maxFontSize }) {
  const charCount = Math.max(1, `${label ?? ""}`.length);
  const padding = Math.max(1, Math.round(scale * 0.5));
  const safeMaxFontSize = Number.isFinite(maxFontSize) ? maxFontSize : 22;

  // Safe-ish estimate for Arial digits + "x" width in ems (slightly pessimistic).
  const charWidthEm = 0.6;

  const maxByHeight = Math.floor(cellH - 2 * padding);
  const maxByWidth = Math.floor((cellW - 2 * padding) / (charCount * charWidthEm));

  let fontSize = clamp(Math.min(safeMaxFontSize, maxByHeight, maxByWidth), 6, safeMaxFontSize);
  let strokeWidth = Math.max(1, Math.round(fontSize * 0.12));

  // Refine with outline taken into account so the stroke doesn't spill out of the tile.
  const maxByWidth2 = Math.floor((cellW - 2 * (padding + strokeWidth)) / (charCount * charWidthEm));
  const maxByHeight2 = Math.floor(cellH - 2 * (padding + strokeWidth));
  fontSize = clamp(Math.min(fontSize, maxByWidth2, maxByHeight2), 6, safeMaxFontSize);
  strokeWidth = Math.max(1, Math.round(fontSize * 0.12));

  const textLength = Math.max(0, cellW - 2 * (padding + strokeWidth));

  return { fontSize, strokeWidth, textLength };
}

function buildOverlaySvg({ widthPx, heightPx, grid, originX, originY, playerX, playerY, scale }) {
  const rows = Array.isArray(grid) ? grid.length : 0;
  const cols = rows > 0 && Array.isArray(grid[0]) ? grid[0].length : 0;
  if (!rows || !cols) {
    return null;
  }

  // The screenshot always represents the GBA screen (15x10 meta-tiles).
  // When visibility is reduced (e.g. caves/gyms/pyramid), Python returns a smaller grid
  // centered on the player. We draw that smaller grid in the correct screen location
  // instead of stretching it to the whole image.
  const screenCols = 15;
  const screenRows = 10;
  const cellW = (widthPx / screenCols) | 0;
  const cellH = (heightPx / screenRows) | 0;

  const playerCol = playerX - originX; // local col in `grid`
  const playerRow = playerY - originY; // local row in `grid`
  const playerScreenCol = (screenCols / 2) | 0; // 7
  const playerScreenRow = (screenRows / 2) | 0; // 5

  const maxFontSize = clamp(Math.floor(10 * scale), 10, 22);

  const parts = [];
  parts.push(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${widthPx}" height="${heightPx}" viewBox="0 0 ${widthPx} ${heightPx}">`
  );

  // Semi-transparent background to improve readability.
  parts.push(`<rect x="0" y="0" width="${widthPx}" height="${heightPx}" fill="rgba(0,0,0,0)" />`);

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const dx = c - playerCol;
      const dy = r - playerRow;
      const screenC = playerScreenCol + dx;
      const screenR = playerScreenRow + dy;
      if (screenC < 0 || screenC >= screenCols || screenR < 0 || screenR >= screenRows) {
        continue;
      }

      const x = screenC * cellW;
      const y = screenR * cellH;

      const worldX = originX + c;
      const worldY = originY + r;

      const code = grid[r]?.[c];
      const stroke = tileCodeToColor(code);

      parts.push(
        `<rect x="${x}" y="${y}" width="${cellW}" height="${cellH}" fill="none" stroke="${stroke}" stroke-width="${Math.max(
          1,
          Math.floor(scale)
        )}" />`
      );

      const label = `${worldX}x${worldY}`;
      const { fontSize, strokeWidth, textLength } = estimateLabelStyle({ label, cellW, cellH, scale, maxFontSize });
      const tx = x + cellW / 2;
      const ty = y + cellH / 2 + fontSize / 3;

      const textFit = textLength ? ` textLength="${textLength}" lengthAdjust="spacingAndGlyphs"` : "";

      // Outline + foreground text for readability.
      parts.push(
        `<text x="${tx}" y="${ty}" text-anchor="middle" font-family="Arial, sans-serif" font-size="${fontSize}" fill="#000000" stroke="#000000" stroke-width="${strokeWidth}" paint-order="stroke"${textFit}>${label}</text>`
      );
      parts.push(
        `<text x="${tx}" y="${ty}" text-anchor="middle" font-family="Arial, sans-serif" font-size="${fontSize}" fill="#ffffff"${textFit}>${label}</text>`
      );
    }
  }

  // Player highlight
  if (Number.isFinite(playerCol) && Number.isFinite(playerRow) && playerCol >= 0 && playerRow >= 0) {
    const px = playerScreenCol * cellW;
    const py = playerScreenRow * cellH;
    parts.push(
      `<rect x="${px}" y="${py}" width="${cellW}" height="${cellH}" fill="none" stroke="#00ff00" stroke-width="${Math.max(
        2,
        Math.floor(scale * 2)
      )}" />`
    );
  }

  parts.push("</svg>");
  return parts.join("");
}

async function buildVisionPayload(gameDataJson) {
  const rawPath = gameDataJson?.screenshot_raw_path;
  if (!rawPath || typeof rawPath !== "string") {
    return { image1Base64: null, image2Base64: null, error: "Missing screenshot_raw_path" };
  }

  let rawBuffer;
  try {
    rawBuffer = await fs.readFile(rawPath);
  } catch (e) {
    return { image1Base64: null, image2Base64: null, error: `Failed to read screenshot: ${e.message}` };
  }

  // Upscale x3 (nearest), PNG output.
  const scale = 3;
  const widthPx = 240 * scale;
  const heightPx = 160 * scale;

  const upscaled = await sharp(rawBuffer)
    .resize({ width: widthPx, height: heightPx, kernel: sharp.kernel.nearest })
    .png()
    .toBuffer();

  const image1Base64 = upscaled.toString("base64");

  // Debug: always persist the generated vision screenshots next to the raw screenshot.
  // This keeps behavior stable and makes it easy to inspect what we actually sent.
  try {
    const outDir = path.dirname(rawPath);
    await fs.writeFile(path.join(outDir, "gba_upscaled_x3.png"), upscaled);
  } catch {
    // Non-fatal: vision can still proceed without debug files.
  }

  // Overworld: add overlay image2 (raw + coords/grid).
  if (!isOverworld(gameDataJson)) {
    return { image1Base64, image2Base64: null, error: null };
  }

  const visible = gameDataJson?.visible_area_data;
  const grid = visible?.grid;
  const originX = Number(visible?.origin?.x);
  const originY = Number(visible?.origin?.y);
  const playerX = Number(gameDataJson?.current_trainer_data?.position?.x);
  const playerY = Number(gameDataJson?.current_trainer_data?.position?.y);

  const svg = buildOverlaySvg({
    widthPx,
    heightPx,
    grid,
    originX: Number.isFinite(originX) ? originX : playerX,
    originY: Number.isFinite(originY) ? originY : playerY,
    playerX: Number.isFinite(playerX) ? playerX : 0,
    playerY: Number.isFinite(playerY) ? playerY : 0,
    scale,
  });

  if (!svg) {
    return { image1Base64, image2Base64: null, error: null };
  }

  const overlayed = await sharp(upscaled)
    .composite([{ input: Buffer.from(svg) }])
    .png()
    .toBuffer();

  const image2Base64 = overlayed.toString("base64");

  try {
    const outDir = path.dirname(rawPath);
    await fs.writeFile(path.join(outDir, "gba_overlay_x3.png"), overlayed);
  } catch {
    // Non-fatal: vision can still proceed without debug files.
  }

  return { image1Base64, image2Base64, error: null };
}

module.exports = { buildVisionPayload, isOverworld };
