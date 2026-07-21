#!/usr/bin/env node
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { devToolsActivePortCandidates, isTargetAwemeDetail, isTargetAwemePost, networkCaptureCommands, parseJsonResponseBody, selectReusableTarget } from "./douyin_cdp_capture.mjs";

const PORT = Number(process.env.DOUYIN_CDP_BRIDGE_PORT || 3457);

async function enableFreshNetworkCapture(cdp, sessionId) {
  for (const [method, params] of networkCaptureCommands()) {
    await cdp.send(method, params, sessionId, 30000);
  }
}

function readDevToolsActivePort() {
  const candidates = devToolsActivePortCandidates(process.platform, process.env, os.homedir());
  for (const file of candidates) {
    try {
      const [port, wsPath] = fs.readFileSync(file, "utf8").trim().split(/\r?\n/);
      if (port && wsPath) return { port: Number(port), wsPath, file };
    } catch {
      // Continue.
    }
  }
  throw new Error("Could not find Chrome DevToolsActivePort.");
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      const text = Buffer.concat(chunks).toString("utf8");
      if (!text) return resolve({});
      try {
        resolve(JSON.parse(text));
      } catch (error) {
        reject(new Error(`Invalid JSON body: ${error.message}`));
      }
    });
    req.on("error", reject);
  });
}

class CDP {
  constructor(ws) {
    this.ws = ws;
    this.nextId = 1;
    this.pending = new Map();
    this.eventListeners = new Set();
    ws.addEventListener("message", (event) => {
      const msg = JSON.parse(event.data);
      if (!msg.id) {
        for (const listener of this.eventListeners) listener(msg);
        return;
      }
      if (!this.pending.has(msg.id)) return;
      const { resolve, reject, timer } = this.pending.get(msg.id);
      this.pending.delete(msg.id);
      clearTimeout(timer);
      if (msg.error) reject(new Error(`CDP error: ${JSON.stringify(msg.error)}`));
      else resolve(msg.result || {});
    });
    ws.addEventListener("close", () => {
      for (const [id, pending] of this.pending.entries()) {
        clearTimeout(pending.timer);
        pending.reject(new Error("Chrome CDP websocket closed"));
        this.pending.delete(id);
      }
    });
  }

  onEvent(listener) {
    this.eventListeners.add(listener);
  }

  static async connect() {
    let active;
    let url;
    try {
      active = readDevToolsActivePort();
      url = `ws://127.0.0.1:${active.port}${active.wsPath}`;
    } catch (fileError) {
      const port = Number(process.env.DOUYIN_CDP_PORT || 0);
      if (!port) throw fileError;
      const response = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (!response.ok) throw new Error(`Chrome DevTools discovery failed on port ${port}: HTTP ${response.status}`);
      const version = await response.json();
      if (!version.webSocketDebuggerUrl) throw new Error(`Chrome DevTools on port ${port} returned no browser websocket URL`);
      active = { port, wsPath: "", file: null };
      url = version.webSocketDebuggerUrl;
    }
    const ws = new WebSocket(url);
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`WebSocket connect timed out: ${url}`)), 60000);
      ws.addEventListener("open", () => {
        clearTimeout(timer);
        resolve();
      }, { once: true });
      ws.addEventListener("error", (event) => {
        clearTimeout(timer);
        reject(new Error(`WebSocket error: ${event.message || "unknown"}`));
      }, { once: true });
    });
    const cdp = new CDP(ws);
    cdp.active = active;
    return cdp;
  }

  send(method, params = {}, sessionId = null, timeoutMs = 30000) {
    const id = this.nextId++;
    const message = { id, method, params };
    if (sessionId) message.sessionId = sessionId;
    const promise = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP command timed out: ${method}`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
    });
    this.ws.send(JSON.stringify(message));
    return promise;
  }
}

let cdpInstance = null;
let cdpPromise = null;
const awemeCaptures = new Map();
const awemePostCaptures = new Map();

async function captureAwemeDetail(cdp, message) {
  if (!message.sessionId) return;
  const capture = awemeCaptures.get(message.sessionId);
  if (!capture || capture.response) return;
  if (message.method === "Network.responseReceived") {
    const response = message.params?.response;
    if (!isTargetAwemeDetail(response?.url || "", capture.awemeId)) return;
    if (capture.requestId) return;
    capture.requestId = message.params.requestId;
    capture.responseInfo = { url: response.url, status: response.status, mime_type: response.mimeType };
    return;
  }
  if (message.method !== "Network.loadingFinished" || capture.pending || message.params?.requestId !== capture.requestId) return;
  capture.pending = true;
  try {
    const result = await cdp.send("Network.getResponseBody", { requestId: capture.requestId }, message.sessionId, 30000);
    const body = parseJsonResponseBody(result.body || "");
    if (body) {
      capture.response = {
        ...capture.responseInfo,
        captured_at: new Date().toISOString(),
        body,
      };
    }
  } catch (error) {
    capture.error = error.message;
  } finally {
    capture.pending = false;
  }
}

async function captureAwemePost(cdp, message) {
  if (!message.sessionId) return;
  const capture = awemePostCaptures.get(message.sessionId);
  if (!capture || capture.response) return;
  if (message.method === "Network.responseReceived") {
    const response = message.params?.response;
    if (!isTargetAwemePost(response?.url || "", capture.secUserId)) return;
    if (capture.requestId) return;
    capture.requestId = message.params.requestId;
    capture.responseInfo = { url: response.url, status: response.status, mime_type: response.mimeType };
    return;
  }
  if (message.method !== "Network.loadingFinished" || capture.pending || message.params?.requestId !== capture.requestId) return;
  capture.pending = true;
  try {
    const result = await cdp.send("Network.getResponseBody", { requestId: capture.requestId }, message.sessionId, 30000);
    const body = parseJsonResponseBody(result.body || "");
    if (body) {
      capture.response = {
        ...capture.responseInfo,
        captured_at: new Date().toISOString(),
        body,
      };
    }
  } catch (error) {
    capture.error = error.message;
  } finally {
    capture.pending = false;
  }
}
async function getCdp() {
  if (cdpInstance?.ws.readyState === WebSocket.OPEN) return cdpInstance;
  if (!cdpPromise) {
    cdpPromise = CDP.connect()
      .then((cdp) => {
        cdpInstance = cdp;
        cdp.onEvent((message) => {
          void captureAwemeDetail(cdp, message);
          void captureAwemePost(cdp, message);
        });
        cdpPromise = null;
        return cdp;
      })
      .catch((error) => {
        cdpPromise = null;
        throw error;
      });
  }
  return cdpPromise;
}

function sendJson(res, status, payload) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(payload));
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://127.0.0.1:${PORT}`);
    if (req.method === "GET" && url.pathname === "/health") {
      const cdp = await getCdp();
      sendJson(res, 200, {
        ok: true,
        connected: cdp.ws.readyState === WebSocket.OPEN,
        chrome_port: cdp.active?.port,
        devtools_active_port: cdp.active?.file,
      });
      return;
    }
    if (req.method === "POST" && url.pathname === "/new") {
      const body = await readBody(req);
      if (!body.url) throw new Error("Missing url");
      const cdp = await getCdp();
      const created = await cdp.send("Target.createTarget", {
        url: body.url,
        background: body.background ?? true,
      }, null, 30000);
      const attached = await cdp.send("Target.attachToTarget", { targetId: created.targetId, flatten: true }, null, 30000);
      await cdp.send("Runtime.enable", {}, attached.sessionId, 30000);
      await enableFreshNetworkCapture(cdp, attached.sessionId);
      sendJson(res, 200, { targetId: created.targetId, sessionId: attached.sessionId });
      return;
    }
    if (req.method === "POST" && url.pathname === "/attach") {
      const body = await readBody(req);
      if (!body.url) throw new Error("Missing url");
      const cdp = await getCdp();
      const targets = await cdp.send("Target.getTargets", {}, null, 30000);
      const target = selectReusableTarget(targets.targetInfos, body.url);
      if (!target) throw new Error("No matching open Chrome tab");
      const attached = await cdp.send("Target.attachToTarget", { targetId: target.targetId, flatten: true }, null, 30000);
      await cdp.send("Runtime.enable", {}, attached.sessionId, 30000);
      await enableFreshNetworkCapture(cdp, attached.sessionId);
      sendJson(res, 200, { targetId: target.targetId, sessionId: attached.sessionId, reused: true });
      return;
    }
    if (req.method === "POST" && url.pathname === "/aweme-detail/start") {
      const body = await readBody(req);
      if (!body.sessionId || !body.awemeId) throw new Error("Missing sessionId or awemeId");
      const cdp = await getCdp();
      await enableFreshNetworkCapture(cdp, body.sessionId);
      awemeCaptures.set(body.sessionId, { awemeId: String(body.awemeId), response: null, responseInfo: null, requestId: null, pending: false, error: null });
      sendJson(res, 200, { ok: true });
      return;
    }
    if (req.method === "POST" && url.pathname === "/aweme-detail/read") {
      const body = await readBody(req);
      if (!body.sessionId) throw new Error("Missing sessionId");
      const capture = awemeCaptures.get(body.sessionId);
      if (!capture) throw new Error("No aweme detail capture started for session");
      sendJson(res, 200, { ok: true, response: capture.response, pending: capture.pending, error: capture.error });
      return;
    }
    if (req.method === "POST" && url.pathname === "/aweme-post/start") {
      const body = await readBody(req);
      if (!body.sessionId || !body.secUserId) throw new Error("Missing sessionId or secUserId");
      const cdp = await getCdp();
      await enableFreshNetworkCapture(cdp, body.sessionId);
      awemePostCaptures.set(body.sessionId, { secUserId: String(body.secUserId), response: null, responseInfo: null, requestId: null, pending: false, error: null });
      sendJson(res, 200, { ok: true });
      return;
    }
    if (req.method === "POST" && url.pathname === "/aweme-post/read") {
      const body = await readBody(req);
      if (!body.sessionId) throw new Error("Missing sessionId");
      const capture = awemePostCaptures.get(body.sessionId);
      if (!capture) throw new Error("No aweme post capture started for session");
      sendJson(res, 200, { ok: true, response: capture.response, pending: capture.pending, error: capture.error });
      return;
    }
    if (req.method === "POST" && url.pathname === "/eval") {
      const body = await readBody(req);
      if (!body.sessionId || !body.expression) throw new Error("Missing sessionId or expression");
      const cdp = await getCdp();
      const timeoutMs = Number(body.timeoutMs || 300000);
      const result = await cdp.send("Runtime.evaluate", {
        expression: body.expression,
        awaitPromise: true,
        returnByValue: true,
        timeout: timeoutMs,
      }, body.sessionId, timeoutMs + 10000);
      if (result.exceptionDetails) {
        const text = result.exceptionDetails.exception?.description || result.exceptionDetails.text || JSON.stringify(result.exceptionDetails);
        sendJson(res, 500, { ok: false, error: text });
        return;
      }
      sendJson(res, 200, { ok: true, value: result.result?.value });
      return;
    }
    if (req.method === "POST" && url.pathname === "/close") {
      const body = await readBody(req);
      if (!body.targetId) throw new Error("Missing targetId");
      const cdp = await getCdp();
      await cdp.send("Target.closeTarget", { targetId: body.targetId }, null, 30000);
      if (body.sessionId) awemeCaptures.delete(body.sessionId);
      if (body.sessionId) awemePostCaptures.delete(body.sessionId);
      sendJson(res, 200, { ok: true });
      return;
    }
    if (req.method === "POST" && url.pathname === "/detach") {
      const body = await readBody(req);
      if (!body.sessionId) throw new Error("Missing sessionId");
      const cdp = await getCdp();
      await cdp.send("Target.detachFromTarget", { sessionId: body.sessionId }, null, 30000);
      awemeCaptures.delete(body.sessionId);
      awemePostCaptures.delete(body.sessionId);
      sendJson(res, 200, { ok: true });
      return;
    }
    sendJson(res, 404, { ok: false, error: "Not found" });
  } catch (error) {
    sendJson(res, 500, { ok: false, error: error.message });
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.error(`[douyin-cdp-bridge] listening on http://127.0.0.1:${PORT}`);
  getCdp().then((cdp) => {
    console.error(`[douyin-cdp-bridge] connected to Chrome port ${cdp.active.port}`);
  }).catch((error) => {
    console.error(`[douyin-cdp-bridge] Chrome connection failed: ${error.message}`);
  });
});
