"use strict";

const palette = ["#58e0c1", "#72a7ff", "#f3c969", "#ef7f91", "#ba91ff", "#73d47c"];
const metrics = new Map();
const grid = document.getElementById("chartGrid");
const emptyState = document.getElementById("emptyState");
const template = document.getElementById("chartTemplate");
const pauseButton = document.getElementById("pauseButton");
const clearButton = document.getElementById("clearButton");
const timeWindow = document.getElementById("timeWindow");
const connection = document.getElementById("connection");
const connectionText = document.getElementById("connectionText");

let paused = false;
let maxPoints = 1000;
let renderPending = false;

function formatValue(value) {
  const abs = Math.abs(value);
  if ((abs !== 0 && abs < 0.001) || abs >= 100000) return value.toExponential(3);
  return Number(value.toFixed(4)).toString();
}

function createMetric(name) {
  const fragment = template.content.cloneNode(true);
  const card = fragment.querySelector(".chart-card");
  const canvas = fragment.querySelector(".chart");
  const color = palette[metrics.size % palette.length];
  card.querySelector(".metric-name").textContent = name;
  card.querySelector(".color-mark").style.background = color;
  canvas.setAttribute("aria-label", `${name} 实时曲线`);
  grid.appendChild(fragment);

  const metric = { name, color, points: [], card: grid.lastElementChild, canvas };
  metrics.set(name, metric);
  emptyState.classList.add("hidden");
  return metric;
}

function applySample(sample) {
  if (!sample || typeof sample.t !== "number" || !sample.values) return;
  for (const [name, rawValue] of Object.entries(sample.values)) {
    const value = Number(rawValue);
    if (!Number.isFinite(value)) continue;
    const metric = metrics.get(name) || createMetric(name);
    metric.points.push([sample.t, value]);
    if (metric.points.length > maxPoints) {
      metric.points.splice(0, metric.points.length - maxPoints);
    }
  }
}

function resetCharts() {
  metrics.clear();
  grid.replaceChildren();
  emptyState.classList.remove("hidden");
  scheduleRender();
}

function visiblePoints(points) {
  const seconds = Number(timeWindow.value);
  if (!seconds || points.length < 2) return points;
  const cutoff = points[points.length - 1][0] - seconds;
  let start = points.length - 1;
  while (start > 0 && points[start - 1][0] >= cutoff) start -= 1;
  return points.slice(start);
}

function drawMetric(metric) {
  const points = visiblePoints(metric.points);
  if (!points.length) return;

  const canvas = metric.canvas;
  const rect = canvas.getBoundingClientRect();
  const dpr = Math.max(1, window.devicePixelRatio || 1);
  const width = Math.max(1, Math.round(rect.width * dpr));
  const height = Math.max(1, Math.round(rect.height * dpr));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }

  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const w = rect.width;
  const h = rect.height;
  const pad = { left: 54, right: 10, top: 12, bottom: 25 };
  const plotW = Math.max(1, w - pad.left - pad.right);
  const plotH = Math.max(1, h - pad.top - pad.bottom);
  const values = points.map((point) => point[1]);
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (min === max) {
    const expansion = Math.max(Math.abs(min) * 0.05, 1);
    min -= expansion;
    max += expansion;
  } else {
    const expansion = (max - min) * 0.08;
    min -= expansion;
    max += expansion;
  }

  let tMin = points[0][0];
  let tMax = points[points.length - 1][0];
  if (tMin === tMax) tMin = tMax - 1;
  const x = (t) => pad.left + ((t - tMin) / (tMax - tMin)) * plotW;
  const y = (v) => pad.top + (1 - (v - min) / (max - min)) * plotH;

  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = "rgba(151, 188, 192, .12)";
  ctx.fillStyle = "#7f9497";
  ctx.font = "11px ui-monospace, SFMono-Regular, Consolas, monospace";
  ctx.lineWidth = 1;

  for (let i = 0; i <= 4; i += 1) {
    const gridY = pad.top + (plotH * i) / 4;
    ctx.beginPath();
    ctx.moveTo(pad.left, gridY);
    ctx.lineTo(w - pad.right, gridY);
    ctx.stroke();
    const label = max - ((max - min) * i) / 4;
    ctx.fillText(formatValue(label), 2, gridY + 4);
  }
  for (let i = 0; i <= 4; i += 1) {
    const gridX = pad.left + (plotW * i) / 4;
    ctx.beginPath();
    ctx.moveTo(gridX, pad.top);
    ctx.lineTo(gridX, h - pad.bottom);
    ctx.stroke();
  }

  const gradient = ctx.createLinearGradient(0, pad.top, 0, h - pad.bottom);
  gradient.addColorStop(0, `${metric.color}38`);
  gradient.addColorStop(1, `${metric.color}00`);
  ctx.beginPath();
  points.forEach((point, index) => {
    const px = x(point[0]);
    const py = y(point[1]);
    if (index === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
  });
  ctx.lineTo(x(points[points.length - 1][0]), h - pad.bottom);
  ctx.lineTo(x(points[0][0]), h - pad.bottom);
  ctx.closePath();
  ctx.fillStyle = gradient;
  ctx.fill();

  ctx.beginPath();
  points.forEach((point, index) => {
    if (index === 0) ctx.moveTo(x(point[0]), y(point[1]));
    else ctx.lineTo(x(point[0]), y(point[1]));
  });
  ctx.strokeStyle = metric.color;
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.stroke();

  ctx.fillStyle = "#7f9497";
  ctx.fillText(`${tMin.toFixed(1)}s`, pad.left, h - 5);
  const endLabel = `${tMax.toFixed(1)}s`;
  ctx.fillText(endLabel, w - pad.right - ctx.measureText(endLabel).width, h - 5);

  const latest = points[points.length - 1][1];
  metric.card.querySelector(".latest-value").textContent = formatValue(latest);
  metric.card.querySelector(".min-value").textContent = formatValue(Math.min(...values));
  metric.card.querySelector(".max-value").textContent = formatValue(Math.max(...values));
  metric.card.querySelector(".point-count").textContent = `${points.length} 点`;
}

function render() {
  renderPending = false;
  for (const metric of metrics.values()) drawMetric(metric);
}

function scheduleRender() {
  if (renderPending) return;
  renderPending = true;
  window.requestAnimationFrame(render);
}

pauseButton.addEventListener("click", () => {
  paused = !paused;
  pauseButton.textContent = paused ? "继续" : "暂停";
  pauseButton.classList.toggle("active", paused);
});

clearButton.addEventListener("click", async () => {
  resetCharts();
  try { await fetch("/api/clear", { method: "POST" }); } catch (_) { /* SSE will reconnect. */ }
});

timeWindow.addEventListener("change", scheduleRender);
window.addEventListener("resize", scheduleRender);

const events = new EventSource("/api/events");
events.addEventListener("open", () => {
  connection.classList.add("online");
  connection.classList.remove("offline");
  connectionText.textContent = "实时连接";
});
events.addEventListener("snapshot", (event) => {
  if (paused) return;
  const payload = JSON.parse(event.data);
  maxPoints = Number(payload.max_points) || maxPoints;
  resetCharts();
  for (const sample of payload.samples || []) applySample(sample);
  scheduleRender();
});
events.addEventListener("sample", (event) => {
  if (paused) return;
  applySample(JSON.parse(event.data));
  scheduleRender();
});
events.addEventListener("clear", () => resetCharts());
events.onerror = () => {
  connection.classList.remove("online");
  connection.classList.add("offline");
  connectionText.textContent = "正在重连";
};
