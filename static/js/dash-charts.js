/** Graphiques des tableaux de bord (canvas, sans dépendance externe). */

const INK = "#0c1c2e";
const GOLD = "#c49a3c";
const SLATE = "#667483";
const MUTED = "#e2e6ec";
const STATUS_COLORS = {
  granted: "#c49a3c",
  requested: "#007fff",
  draft: "#667483",
  refused: "#ce1021",
  revoked: "#8a1f28",
  open: "#007fff",
  in_progress: "#0c1c2e",
  on_hold: "#c49a3c",
  closed: "#667483",
  national: "#007fff",
  international: "#c49a3c",
};

function readData() {
  const node =
    document.getElementById("supervision-charts-data") ||
    document.getElementById("cabinet-charts-data");
  if (!node) return null;
  try {
    return JSON.parse(node.textContent || "{}");
  } catch {
    return null;
  }
}

function fitCanvas(canvas) {
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || canvas.width;
  const height = canvas.clientHeight || canvas.height;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  return { ctx, width, height };
}

function toggleEmpty(canvas, empty) {
  const hint = canvas.parentElement?.querySelector(".chart-empty");
  canvas.hidden = empty;
  if (hint) hint.hidden = !empty;
}

function formatTick(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return String(value ?? "");
  if (Math.abs(value) >= 1000) {
    return new Intl.NumberFormat("fr-CD", { maximumFractionDigits: 0 }).format(value);
  }
  return String(Math.round(value * 100) / 100);
}

function drawHorizontalBars(canvas, series) {
  const empty = !series.length || series.every((row) => !row.value);
  toggleEmpty(canvas, empty);
  if (empty) return;
  const fitted = fitCanvas(canvas);
  if (!fitted) return;
  const { ctx, width, height } = fitted;
  const max = Math.max(...series.map((row) => Number(row.value) || 0), 1);
  const padL = 118;
  const padR = 48;
  const padT = 8;
  const padB = 8;
  const rowH = (height - padT - padB) / series.length;

  series.forEach((row, index) => {
    const y = padT + index * rowH;
    const barW = ((width - padL - padR) * (Number(row.value) || 0)) / max;
    ctx.fillStyle = SLATE;
    ctx.font = "12px IBM Plex Sans, sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    const label = String(row.label || "").slice(0, 22);
    ctx.fillText(label, padL - 10, y + rowH / 2);
    ctx.fillStyle = INK;
    const h = Math.max(10, rowH * 0.45);
    const by = y + (rowH - h) / 2;
    roundRect(ctx, padL, by, Math.max(barW, 4), h, 6);
    ctx.fill();
    ctx.fillStyle = GOLD;
    ctx.textAlign = "left";
    ctx.fillText(formatTick(Number(row.value) || 0), padL + Math.max(barW, 4) + 8, y + rowH / 2);
  });
}

function drawGroupedBars(canvas, series, leftKey, rightKey) {
  const empty =
    !series.length ||
    series.every((row) => !(Number(row[leftKey]) || 0) && !(Number(row[rightKey]) || 0));
  toggleEmpty(canvas, empty);
  if (empty) return;
  const fitted = fitCanvas(canvas);
  if (!fitted) return;
  const { ctx, width, height } = fitted;
  const max = Math.max(
    ...series.flatMap((row) => [Number(row[leftKey]) || 0, Number(row[rightKey]) || 0]),
    1,
  );
  const padL = 36;
  const padR = 16;
  const padT = 16;
  const padB = 36;
  const groupW = (width - padL - padR) / series.length;
  const barW = Math.max(8, groupW * 0.28);

  ctx.strokeStyle = MUTED;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padL, height - padB);
  ctx.lineTo(width - padR, height - padB);
  ctx.stroke();

  series.forEach((row, index) => {
    const gx = padL + index * groupW;
    const leftH = ((height - padT - padB) * (Number(row[leftKey]) || 0)) / max;
    const rightH = ((height - padT - padB) * (Number(row[rightKey]) || 0)) / max;
    const base = height - padB;
    ctx.fillStyle = INK;
    roundRect(ctx, gx + groupW * 0.18, base - leftH, barW, Math.max(leftH, 2), 4);
    ctx.fill();
    ctx.fillStyle = GOLD;
    roundRect(ctx, gx + groupW * 0.18 + barW + 6, base - rightH, barW, Math.max(rightH, 2), 4);
    ctx.fill();
    ctx.fillStyle = SLATE;
    ctx.font = "11px IBM Plex Sans, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillText(row.label, gx + groupW / 2, base + 8);
  });
}

function drawDonut(canvas, series) {
  const empty = !series.length || series.every((row) => !row.value);
  toggleEmpty(canvas, empty);
  if (empty) return;
  const fitted = fitCanvas(canvas);
  if (!fitted) return;
  const { ctx, width, height } = fitted;
  const total = series.reduce((sum, row) => sum + (Number(row.value) || 0), 0);
  const cx = width * 0.34;
  const cy = height / 2;
  const radius = Math.min(width, height) * 0.32;
  let angle = -Math.PI / 2;

  series.forEach((row) => {
    const slice = ((Number(row.value) || 0) / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, radius, angle, angle + slice);
    ctx.closePath();
    ctx.fillStyle = STATUS_COLORS[row.key] || INK;
    ctx.fill();
    angle += slice;
  });

  ctx.beginPath();
  ctx.arc(cx, cy, radius * 0.55, 0, Math.PI * 2);
  ctx.fillStyle = "#fff";
  ctx.fill();
  ctx.fillStyle = INK;
  ctx.font = "600 20px EB Garamond, serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(String(total), cx, cy - 6);
  ctx.fillStyle = SLATE;
  ctx.font = "11px IBM Plex Sans, sans-serif";
  ctx.fillText("total", cx, cy + 14);

  const legendX = width * 0.62;
  let legendY = Math.max(24, cy - series.length * 12);
  series.forEach((row) => {
    ctx.fillStyle = STATUS_COLORS[row.key] || INK;
    ctx.fillRect(legendX, legendY - 6, 10, 10);
    ctx.fillStyle = INK;
    ctx.font = "12px IBM Plex Sans, sans-serif";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillText(`${row.label} (${row.value})`, legendX + 16, legendY);
    legendY += 22;
  });
}

function roundRect(ctx, x, y, w, h, r) {
  const radius = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.arcTo(x + w, y, x + w, y + h, radius);
  ctx.arcTo(x + w, y + h, x, y + h, radius);
  ctx.arcTo(x, y + h, x, y, radius);
  ctx.arcTo(x, y, x + w, y, radius);
  ctx.closePath();
}

function render() {
  const data = readData();
  if (!data) return;
  document.querySelectorAll("canvas[data-chart]").forEach((node) => {
    if (!(node instanceof HTMLCanvasElement)) return;
    const series = data[node.dataset.series || ""] || [];
    const type = node.dataset.chart;
    if (type === "bars-h") {
      drawHorizontalBars(node, series);
    } else if (type === "grouped") {
      drawGroupedBars(
        node,
        series,
        node.dataset.left || "matters",
        node.dataset.right || "procurations",
      );
    } else if (type === "donut") {
      drawDonut(node, series);
    }
  });
}

render();
window.addEventListener("resize", render);
