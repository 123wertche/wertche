const $ = (selector) => document.querySelector(selector);
let creators = [], selected = new Set(), filter = "all", pipelineId = null, logOffset = 0;

async function api(path, options = {}) {
  const response = await fetch(path, {headers: {"Content-Type": "application/json"}, ...options});
  const data = (response.headers.get("content-type") || "").includes("json") ? await response.json() : {};
  if (!response.ok) throw new Error(data.error || data.message || `HTTP ${response.status}`);
  return data;
}
function notice(text, type = "") { $("#notice").textContent = text; $("#notice").className = type; }
function visibleCreators() { return creators.filter(item => filter === "all" || item.platform === filter); }
function renderCreators() {
  const list = $("#creator-list"); list.replaceChildren();
  for (const creator of visibleCreators()) {
    const label = document.createElement("label"); label.className = `creator ${selected.has(creator.local_id) ? "selected" : ""}`;
    label.setAttribute("aria-checked", selected.has(creator.local_id) ? "true" : "false");
    label.title = creator.homepage_url;
    const box = document.createElement("input"); box.type = "checkbox"; box.checked = selected.has(creator.local_id);
    box.addEventListener("change", () => { box.checked ? selected.add(creator.local_id) : selected.delete(creator.local_id); renderCreators(); });
    const text = document.createElement("span");
    const platform = document.createElement("span"); platform.className = "platform"; platform.textContent = creator.platform;
    const name = document.createElement("strong"); name.textContent = creator.display_name;
    const url = document.createElement("small"); url.textContent = creator.homepage_url;
    text.append(platform, name, url); label.append(box, text); list.append(label);
  }
  if (!list.children.length) list.textContent = "暂无博主，请在上方粘贴主页链接。";
  $("#creator-count").textContent = `已选 ${selected.size} / ${creators.length}`;
}
async function loadCreators(selectNew = false) {
  const data = await api("/api/creators"); creators = data.creators;
  if (selectNew) creators.forEach(item => selected.add(item.local_id));
  renderCreators();
}
async function addCreators() {
  const urls = $("#creator-urls").value.split(/\r?\n/).map(v => v.trim()).filter(Boolean);
  if (!urls.length) return notice("请先粘贴博主主页链接。", "error");
  try {
    const preview = await api("/api/creators/preview", {method: "POST", body: JSON.stringify({urls})});
    const merged = new Map(creators.map(item => [`${item.platform}:${item.platform_id}`, item]));
    preview.creators.forEach(item => merged.set(`${item.platform}:${item.platform_id}`, item));
    await api("/api/creators", {method: "PUT", body: JSON.stringify({creators: [...merged.values()]})});
    $("#creator-urls").value = ""; await loadCreators(true); notice(`已添加并去重，共 ${creators.length} 位博主。`, "success");
  } catch (error) { notice(error.message, "error"); }
}
function options() { return {videos_per_creator: Number($("#video-count").value), model: $("#model").value, device: $("#device").value, transcribe: $("#transcribe").checked, comments: $("#comments").checked}; }
async function runPipeline() {
  if (!selected.size) return notice("请至少选择一位博主。", "error");
  const button = $("#run-pipeline"); button.disabled = true;
  try {
    const data = await api("/api/pipelines", {method: "POST", body: JSON.stringify({selected_creator_ids: [...selected], options: options()})});
    pipelineId = data.pipeline.id; logOffset = 0; $("#pipeline-log").textContent = ""; $("#confirmation").hidden = true;
    notice("一键流程已启动，正在执行预检和候选 dry-run。", "success"); await pollPipeline();
  } catch (error) {
    if (error.message.startsWith("pipeline already running: ")) {
      pipelineId = error.message.split(": ", 2)[1];
      logOffset = 0; $("#pipeline-log").textContent = "";
      notice("已有流程正在运行，已自动接入当前进度。", "success");
      await pollPipeline();
      return;
    }
    notice(error.message, "error"); button.disabled = false;
  }
}
function progressFor(status) { return ({dry_run_queued:5,running:35,awaiting_confirmation:50,execution_queued:55,succeeded:100,failed:100})[status] || 10; }
async function attachActivePipeline() {
  const data = await api("/api/pipelines");
  const activeStatuses = new Set(["dry_run_queued", "running", "awaiting_confirmation", "execution_queued"]);
  const pipeline = data.pipelines.find(item => activeStatuses.has(item.status)) || data.pipelines[0];
  if (!pipeline) return false;
  pipelineId = pipeline.id; logOffset = 0; $("#pipeline-log").textContent = "";
  $("#run-pipeline").disabled = activeStatuses.has(pipeline.status);
  await pollPipeline(false);
  return true;
}
async function pollPipeline(recoverMissing = true) {
  if (!pipelineId) return;
  try {
    const data = await api(`/api/pipelines/${encodeURIComponent(pipelineId)}`), p = data.pipeline;
    $("#pipeline-status").textContent = p.status; $("#current-step").textContent = p.current_step || p.phase; $("#progress-bar").style.width = `${progressFor(p.status)}%`;
    const log = await api(`/api/pipelines/${encodeURIComponent(pipelineId)}/log?offset=${logOffset}`);
    if (log.text) { $("#pipeline-log").textContent += log.text; $("#pipeline-log").scrollTop = $("#pipeline-log").scrollHeight; } logOffset = log.next_offset;
    if (p.status === "awaiting_confirmation") { $("#confirmation").hidden = false; $("#confirmation-phrase").textContent = p.confirmation_phrase; $("#run-pipeline").disabled = false; }
    if (["succeeded","failed"].includes(p.status)) { $("#run-pipeline").disabled = false; notice(p.status === "succeeded" ? "流程已完成，请查看结果与导出文件。" : `流程失败：${p.error || "请查看日志"}`, p.status === "succeeded" ? "success" : "error"); await loadArtifacts(); }
  } catch (error) {
    if (recoverMissing && error.message === "pipeline not found") {
      pipelineId = null; logOffset = 0;
      if (await attachActivePipeline()) {
        notice("服务已重启，已自动恢复最新流程状态。", "success");
      } else {
        $("#run-pipeline").disabled = false;
        notice("服务已重启，请重新开始流程。", "error");
      }
      return;
    }
    notice(error.message, "error");
  }
}
async function confirmPipeline() {
  try {
    await api(`/api/pipelines/${encodeURIComponent(pipelineId)}/confirm`, {method:"POST", body:JSON.stringify({confirmation_phrase:$("#confirmation-input").value.trim()})});
    $("#confirmation").hidden = true; notice("已确认，开始下载、转写与飞书同步。", "success");
  } catch (error) { notice(error.message, "error"); }
}
async function loadHealth(force = false) {
  try { const data = await api(`/api/health${force ? "?force=1" : ""}`), root = $("#health-cards"); root.replaceChildren();
    Object.entries(data).filter(([k]) => !["listen_host","browser"].includes(k)).forEach(([name,value]) => { const card=document.createElement("article"), title=document.createElement("strong"), detail=document.createElement("small"); title.textContent=name.replaceAll("_"," "); detail.textContent=typeof value === "object" ? `${value.status}: ${value.detail}` : String(value); card.append(title,detail); root.append(card); });
  } catch (error) { notice(error.message,"error"); }
}
async function loadArtifacts(){try{const data=await api("/api/artifacts"),list=$("#artifact-list");list.replaceChildren();[...(data.latest_manifests||[]),...(data.recent_files||[])].slice(0,12).forEach(value=>{const li=document.createElement("li");li.textContent=value;list.append(li)});}catch(error){notice(error.message,"error")}}
async function startSimpleTask(action){try{await api("/api/tasks",{method:"POST",body:JSON.stringify({action,params:{}})});notice(`${action} 已启动，请在日志目录查看结果。`,"success")}catch(error){notice(error.message,"error")}}

$("#add-creators").addEventListener("click", addCreators); $("#run-pipeline").addEventListener("click", runPipeline); $("#confirm-pipeline").addEventListener("click", confirmPipeline);
$("#refresh").addEventListener("click",()=>Promise.all([loadCreators(),loadHealth(true),loadArtifacts()]));
document.querySelectorAll("[data-filter]").forEach(button=>button.addEventListener("click",()=>{filter=button.dataset.filter;document.querySelectorAll("[data-filter]").forEach(v=>v.classList.toggle("active",v===button));renderCreators()}));
$("#select-visible").addEventListener("click",()=>{visibleCreators().forEach(item=>selected.add(item.local_id));renderCreators()}); $("#clear-selection").addEventListener("click",()=>{selected.clear();renderCreators()});
document.querySelectorAll("[data-lifecycle]").forEach(button=>button.addEventListener("click",async()=>{try{const name=button.dataset.lifecycle,path=name==="connection"?"/api/connection":`/api/${name}/start`;await api(path,name==="connection"?{}:{method:"POST",body:"{}"});notice(`${name} 操作成功。`,"success");await loadHealth(true)}catch(error){notice(error.message,"error")}}));
document.querySelectorAll("[data-action]").forEach(button=>button.addEventListener("click",()=>startSimpleTask(button.dataset.action)));

async function init(){try{await Promise.all([loadCreators(true),loadHealth(),loadArtifacts()]);await api("/api/ready");await attachActivePipeline()}catch(error){notice(error.message,"error")}setInterval(()=>{if(!document.hidden){pollPipeline();}},2000);setInterval(()=>{if(!document.hidden)loadHealth();},30000)}init();
