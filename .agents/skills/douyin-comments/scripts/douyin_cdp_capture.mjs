import path from "node:path";

export function devToolsActivePortCandidates(platform, env, home) {
  const pathApi = platform === "win32" ? path.win32 : path.posix;
  const candidates = [];
  if (env.DOUYIN_CHROME_USER_DATA_DIR) candidates.push(pathApi.join(env.DOUYIN_CHROME_USER_DATA_DIR, "DevToolsActivePort"));
  if (platform === "win32") {
    const local = env.LOCALAPPDATA || "";
    candidates.push(pathApi.join(local, "Google", "Chrome", "User Data", "DevToolsActivePort"));
    candidates.push(pathApi.join(local, "Chromium", "User Data", "DevToolsActivePort"));
  } else if (platform === "darwin") {
    candidates.push(pathApi.join(home, "Library/Application Support/Google/Chrome/User Data/DevToolsActivePort"));
    candidates.push(pathApi.join(home, "Library/Application Support/Chromium/User Data/DevToolsActivePort"));
  } else {
    candidates.push(pathApi.join(home, ".config/google-chrome/DevToolsActivePort"));
    candidates.push(pathApi.join(home, ".config/chromium/DevToolsActivePort"));
  }
  return [...new Set(candidates)];
}

export function isTargetAwemeDetail(url, awemeId) {
  try {
    const parsed = new URL(url);
    return parsed.pathname.includes("aweme/detail") && parsed.searchParams.get("aweme_id") === String(awemeId);
  } catch {
    return false;
  }
}

export function isTargetAwemePost(url, secUserId) {
  try {
    const parsed = new URL(url);
    return parsed.pathname.includes("aweme/post") && parsed.searchParams.get("sec_user_id") === String(secUserId);
  } catch {
    return false;
  }
}

export function parseJsonResponseBody(text) {
  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

export function networkCaptureCommands() {
  return [
    ["Network.enable", {}],
    ["Network.setCacheDisabled", { cacheDisabled: true }],
  ];
}

export function selectReusableTarget(targetInfos, targetUrl) {
  const normalize = (value) => {
    try {
      const parsed = new URL(value);
      return `${parsed.origin}${parsed.pathname.replace(/\/$/, "")}`;
    } catch {
      return "";
    }
  };
  const wanted = normalize(targetUrl);
  return (targetInfos || []).find((target) => target?.type === "page" && normalize(target.url) === wanted) || null;
}
