#!/usr/bin/env node
/**
 * Tiny stdlib-only demo server (Node's built-in http + fetch, no Express, no deps).
 * Serves the shared frontend from ../shared/public and proxies /api/ask,
 * /api/upload, /api/corpus, /api/document to the deployed AWS backend (API_URL).
 *
 * Usage:
 *   API_URL=https://<api-id>.execute-api.<region>.amazonaws.com node server.js
 * (or put API_URL=... in a .env file next to this script)
 */
const http = require("http");
const fs = require("fs");
const path = require("path");

const HERE = __dirname;
const PUBLIC_DIR = path.resolve(HERE, "..", "shared", "public");

// routes proxied 1:1 to the AWS API Gateway backend
const PROXY_ROUTES = {
  "POST /api/ask": { method: "POST", path: "/ask" },
  "POST /api/upload": { method: "POST", path: "/upload" },
  "GET /api/corpus": { method: "GET", path: "/corpus" },
  "GET /api/document": { method: "GET", path: "/document" },
};

function loadDotenv() {
  const envPath = path.join(HERE, ".env");
  if (!fs.existsSync(envPath)) return;
  for (const line of fs.readFileSync(envPath, "utf8").split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
    const [key, ...rest] = trimmed.split("=");
    if (!(key.trim() in process.env)) {
      process.env[key.trim()] = rest.join("=").trim();
    }
  }
}

loadDotenv();

const PORT = parseInt(process.env.PORT || "5002", 10);
const API_URL = (process.env.API_URL || "").replace(/\/$/, "");
const API_KEY = process.env.API_KEY || "";

const MIME = {
  ".html": "text/html",
  ".css": "text/css",
  ".js": "application/javascript",
  ".json": "application/json",
};

// The dashboard's Backend selector calls whichever port you didn't load the page
// from, so CORS has to allow that cross-port request - but allowing it from *any*
// origin would let any website open in your browser silently call this server
// (which holds your API_KEY) while it's running. Scope it to just the two demo ports.
const ALLOWED_ORIGINS = new Set([
  "http://localhost:5001", "http://localhost:5002",
  "http://127.0.0.1:5001", "http://127.0.0.1:5002",
]);

function corsHeaders(req) {
  const origin = req.headers.origin;
  const headers = {
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  };
  if (ALLOWED_ORIGINS.has(origin)) headers["Access-Control-Allow-Origin"] = origin;
  return headers;
}

function sendJson(req, res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body), ...corsHeaders(req) });
  res.end(body);
}

function serveStatic(req, res) {
  let relPath = req.url.split("?")[0];
  if (relPath === "/") relPath = "/index.html";
  const fullPath = path.resolve(PUBLIC_DIR, "." + relPath);
  if (!fullPath.startsWith(PUBLIC_DIR) || !fs.existsSync(fullPath) || fs.statSync(fullPath).isDirectory()) {
    sendJson(req, res, 404, { error: "not found" });
    return;
  }
  const ext = path.extname(fullPath);
  const body = fs.readFileSync(fullPath);
  res.writeHead(200, { "Content-Type": MIME[ext] || "application/octet-stream", "Content-Length": body.length });
  res.end(body);
}

async function proxy(req, res, route) {
  if (!API_URL) {
    sendJson(req, res, 500, { error: "API_URL is not set. See .env.example." });
    return;
  }
  let body;
  if (route.method === "POST") {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    body = Buffer.concat(chunks);
  }

  const query = req.url.split("?")[1];
  const upstreamUrl = API_URL + route.path + (query ? `?${query}` : "");

  try {
    const upstream = await fetch(upstreamUrl, {
      method: route.method,
      headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
      body,
      signal: AbortSignal.timeout(30000),
    });
    const data = await upstream.json();
    sendJson(req, res, upstream.status, data);
  } catch (err) {
    sendJson(req, res, 502, { error: `could not reach API_URL: ${err.message}` });
  }
}

const server = http.createServer((req, res) => {
  console.log(`[node:${PORT}] ${req.method} ${req.url}`);

  if (req.method === "OPTIONS") {
    res.writeHead(204, corsHeaders(req));
    res.end();
    return;
  }
  if (req.method === "GET" && req.url === "/api/info") {
    sendJson(req, res, 200, { runtime: "node", port: PORT });
    return;
  }
  const routeKey = `${req.method} ${req.url.split("?")[0]}`;
  if (PROXY_ROUTES[routeKey]) {
    proxy(req, res, PROXY_ROUTES[routeKey]);
    return;
  }
  if (req.method === "GET") {
    serveStatic(req, res);
    return;
  }
  sendJson(req, res, 404, { error: "not found" });
});

if (!API_URL) {
  console.warn("Warning: API_URL is not set. Copy .env.example to .env and set it after deploying.");
}
if (!API_KEY) {
  console.warn("Warning: API_KEY is not set. AWS will reject every request with 401 until it matches what deploy.py provisioned.");
}
server.listen(PORT, () => console.log(`Node demo app on http://localhost:${PORT}`));
