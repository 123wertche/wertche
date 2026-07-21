import assert from "node:assert/strict";
import test from "node:test";

import * as capture from "./douyin_cdp_capture.mjs";

const { devToolsActivePortCandidates, isTargetAwemeDetail, isTargetAwemePost, networkCaptureCommands, parseJsonResponseBody } = capture;

test("selects an already open creator tab without matching query strings", () => {
  assert.equal(typeof capture.selectReusableTarget, "function");
  const selected = capture.selectReusableTarget([
    { targetId: "home", type: "page", url: "https://www.douyin.com/" },
    { targetId: "creator", type: "page", url: "https://www.douyin.com/user/creator-id?from_tab_name=main" },
  ], "https://www.douyin.com/user/creator-id");

  assert.equal(selected?.targetId, "creator");
});

test("accepts only the requested aweme detail response", () => {
  assert.equal(isTargetAwemeDetail("https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=123", "123"), true);
  assert.equal(isTargetAwemeDetail("https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=999", "123"), false);
  assert.equal(isTargetAwemeDetail("https://www.douyin.com/aweme/v1/web/aweme/list/", "123"), false);
});

test("parses only JSON response text", () => {
  assert.deepEqual(parseJsonResponseBody('{"aweme_detail":{"aweme_id":"123"}}'), { aweme_detail: { aweme_id: "123" } });
  assert.equal(parseJsonResponseBody("<html>blocked</html>"), null);
});

test("accepts only the requested creator post response", () => {
  assert.equal(isTargetAwemePost("https://www.douyin.com/aweme/v1/web/aweme/post/?sec_user_id=creator-123", "creator-123"), true);
  assert.equal(isTargetAwemePost("https://www.douyin.com/aweme/v1/web/aweme/post/?sec_user_id=other", "creator-123"), false);
  assert.equal(isTargetAwemePost("https://www.douyin.com/aweme/v1/web/aweme/detail/?sec_user_id=creator-123", "creator-123"), false);
});

test("prefers the project Chrome profile DevToolsActivePort", () => {
  const candidates = devToolsActivePortCandidates("win32", { DOUYIN_CHROME_USER_DATA_DIR: "C:\\project-profile", LOCALAPPDATA: "C:\\local" }, "C:\\home");
  assert.equal(candidates[0], "C:\\project-profile\\DevToolsActivePort");
});

test("fresh network capture disables Chrome cache before navigation", () => {
  assert.deepEqual(networkCaptureCommands(), [
    ["Network.enable", {}],
    ["Network.setCacheDisabled", { cacheDisabled: true }],
  ]);
});
