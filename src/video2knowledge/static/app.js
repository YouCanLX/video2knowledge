const select = (selector) => document.querySelector(selector);
const results = select("#results");
const jobs = select("#jobs");
const queueStatus = select("#queue-status");
const queueSummary = select("#queue-summary");
const queueToggle = select("#queue-toggle");
const queueContent = select("#queue-content");
const queueCreatorFilter = select("#queue-creator-filter");
const queueCollectionFilter = select("#queue-collection-filter");
const queueStatusFilter = select("#queue-status-filter");
const queueYearFilter = select("#queue-year-filter");
const queueMonthFilter = select("#queue-month-filter");
const queueDayFilter = select("#queue-day-filter");
const selectVisibleJobs = select("#select-visible-jobs");
const selectedJobsCount = select("#selected-jobs-count");
const restartSelectedJobs = select("#restart-selected-jobs");
const deleteSelectedJobs = select("#delete-selected-jobs");
const urlStatus = select("#url-status");
const creatorStatus = select("#creator-status");
const creatorBrowser = select("#creator-browser");
const creatorContent = select("#creator-content");
const settingsStatus = select("#settings-status");
const settingsToggle = select("#settings-toggle");
const settingsContent = select("#settings-content");
const downloadHistoryList = select("#download-history-list");
const downloadHistorySummary = select("#download-history-summary");
const downloadHistoryStatus = select("#download-history-status");
const downloadHistoryToggle = select("#download-history-toggle");
const downloadHistoryContent = select("#download-history-content");
const addVideosTab = select("#add-videos-tab");
const downloadHistoryTab = select("#download-history-tab");
const addVideosPage = select("#add-videos-page");
const downloadHistoryPage = select("#download-history-page");
const requestProgressStack = select("#request-progress-stack");
const preflightDialog = select("#preflight-dialog");
const isStaticPreview = window.location.protocol === "file:";
const REQUEST_PROGRESS_STORAGE_KEY = "v2k.request-progress.v2";
const REQUEST_LAST_INTERACTION_KEY = "v2k.request-progress.last-interaction";
const REQUEST_IDLE_TIMEOUT_MS = 60 * 60 * 1000;
let searchResults = [];
let latestJobs = [];
const expandedFileJobs = new Set();
const expandedQueueJobs = new Set();
const expandedQueueDates = new Set();
const selectedQueueJobs = new Set();
const trackedRequests = new Map();
const downloadHistoryGroups = new Map();
let creatorState = null;
let lastUserInteraction = Number(localStorage.getItem(REQUEST_LAST_INTERACTION_KEY)) || Date.now();
let draggingRequestId = null;
let processingPreflightActive = false;
let jobsPollingActive = false;
let jobPollTimer = null;
let historyPollTimer = null;
let mlxPollTimer = null;

function jobNeedsPolling(job) {
  return Boolean(job.session_active)
    && !["complete", "failed", "paused"].includes(job.status);
}

function scheduleJobPolling() {
  clearTimeout(jobPollTimer);
  jobPollTimer = null;
  if (!document.hidden && jobsPollingActive) {
    jobPollTimer = setTimeout(pollJobs, 2500);
  }
}

function scheduleHistoryPolling() {
  clearTimeout(historyPollTimer);
  historyPollTimer = null;
  if (!document.hidden && jobsPollingActive && !downloadHistoryPage.hidden) {
    historyPollTimer = setTimeout(pollDownloadHistory, 10000);
  }
}

function scheduleMlxPolling(status) {
  clearTimeout(mlxPollTimer);
  mlxPollTimer = null;
  const shouldPoll = status?.state === "starting";
  if (!document.hidden && shouldPoll) {
    mlxPollTimer = setTimeout(pollMlxStatus, status.state === "starting" ? 2500 : 10000);
  }
}

function stopNetworkPolling() {
  clearTimeout(jobPollTimer);
  clearTimeout(historyPollTimer);
  clearTimeout(mlxPollTimer);
  jobPollTimer = null;
  historyPollTimer = null;
  mlxPollTimer = null;
}

let lastNetworkRefreshAt = 0;

function refreshNetworkState(force = false) {
  if (document.hidden) return;
  const now = Date.now();
  if (!force && now - lastNetworkRefreshAt < 30000) return;
  lastNetworkRefreshAt = now;
  pollJobs();
  pollMlxStatus();
  if (!downloadHistoryPage.hidden) pollDownloadHistory();
}

function activateAppTab(name, focus = false) {
  const showHistory = name === "history";
  addVideosTab.setAttribute("aria-selected", String(!showHistory));
  downloadHistoryTab.setAttribute("aria-selected", String(showHistory));
  addVideosTab.tabIndex = showHistory ? -1 : 0;
  downloadHistoryTab.tabIndex = showHistory ? 0 : -1;
  addVideosPage.hidden = showHistory;
  downloadHistoryPage.hidden = !showHistory;
  if (focus) (showHistory ? downloadHistoryTab : addVideosTab).focus();
}

function requestId() {
  return globalThis.crypto?.randomUUID?.()
    || `request-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function openRuntimeSettings() {
  settingsToggle.setAttribute("aria-expanded", "true");
  settingsContent.hidden = false;
  select(".settings-toggle-label").textContent = "Collapse";
  settingsToggle.scrollIntoView({ behavior: "smooth", block: "start" });
}

function showPreflightConfirmation(report) {
  select("#preflight-checks").innerHTML = report.checks.map((check) => `
    <div class="preflight-check ${check.ready ? "ready" : "unready"}">
      <span class="preflight-check-state" aria-hidden="true">${check.ready ? "✓" : "!"}</span>
      <strong>${escapeHtml(check.label)}</strong>
      <small>${escapeHtml(check.message)}</small>
    </div>
  `).join("");
  preflightDialog.showModal();
  return new Promise((resolve) => {
    const finish = (decision) => {
      preflightDialog.close();
      select("#preflight-cancel").removeEventListener("click", cancel);
      select("#preflight-settings").removeEventListener("click", review);
      select("#preflight-continue").removeEventListener("click", continueAnyway);
      preflightDialog.removeEventListener("cancel", cancelDialog);
      resolve(decision);
    };
    const cancel = () => finish("cancel");
    const review = () => finish("settings");
    const continueAnyway = () => finish("continue");
    const cancelDialog = (event) => {
      event.preventDefault();
      finish("cancel");
    };
    select("#preflight-cancel").addEventListener("click", cancel);
    select("#preflight-settings").addEventListener("click", review);
    select("#preflight-continue").addEventListener("click", continueAnyway);
    preflightDialog.addEventListener("cancel", cancelDialog);
  });
}

async function confirmProcessingServices(synthesize = false) {
  if (processingPreflightActive) return false;
  processingPreflightActive = true;
  try {
    let report;
    try {
      report = await requestJson(`/api/runtime/preflight?synthesize=${String(synthesize)}`);
    } catch (error) {
      report = {
        ready: false,
        checks: [{
          label: "Readiness check",
          ready: false,
          message: error.message,
        }],
      };
    }
    if (report.ready) return true;
    const decision = await showPreflightConfirmation(report);
    if (decision === "settings") openRuntimeSettings();
    return decision === "continue";
  } finally {
    processingPreflightActive = false;
  }
}

function saveTrackedRequests() {
  localStorage.setItem(REQUEST_PROGRESS_STORAGE_KEY, JSON.stringify([...trackedRequests.values()]));
}

function loadTrackedRequests() {
  try {
    const stored = JSON.parse(localStorage.getItem(REQUEST_PROGRESS_STORAGE_KEY) || "[]");
    stored.forEach((request) => {
      if (request?.id && request?.label) trackedRequests.set(request.id, request);
    });
  } catch (_error) {
    localStorage.removeItem(REQUEST_PROGRESS_STORAGE_KEY);
  }
}

function beginRequestProgress(label, message = "Preparing the request…") {
  const id = requestId();
  trackedRequests.set(id, {
    id,
    label,
    message,
    jobIds: null,
    state: "submitting",
    createdAt: Date.now(),
    completedAt: null,
  });
  saveTrackedRequests();
  renderRequestProgress(latestJobs);
  return id;
}

function trackRequestJobs(id, jobIds, label) {
  const request = trackedRequests.get(id);
  if (!request) return;
  Object.assign(request, { label, jobIds, state: "active", message: "" });
  saveTrackedRequests();
  renderRequestProgress(latestJobs);
}

function failRequestProgress(id, message) {
  const request = trackedRequests.get(id);
  if (!request) return;
  Object.assign(request, {
    state: "failed",
    message,
    completedAt: Date.now(),
  });
  saveTrackedRequests();
  renderRequestProgress(latestJobs);
}

function requestProgressState(request, allJobs) {
  if (!request.jobIds) {
    return {
      className: request.state === "failed" ? "failed" : "active",
      kicker: request.state === "failed" ? "Request failed" : "Submitting request",
      percent: request.state === "failed" ? 100 : null,
      countsText: request.message,
      detail: request.state === "failed"
        ? "No additional jobs were added by this request."
        : "Waiting for the jobs to enter the processing queue.",
      complete: request.state === "failed",
    };
  }
  const requestJobIds = new Set(request.jobIds);
  const jobsForRequest = allJobs.filter((job) => requestJobIds.has(job.id));
  const counts = { complete: 0, failed: 0, queued: 0, paused: 0, running: 0 };
  jobsForRequest.forEach((job) => {
    if (["complete", "failed", "queued", "paused"].includes(job.status)) {
      counts[job.status] += 1;
    } else if (job.status === "pausing") {
      counts.paused += 1;
    } else {
      counts.running += 1;
    }
  });
  const total = request.jobIds.length;
  const finished = counts.complete + counts.failed;
  const unavailable = total - jobsForRequest.length;
  const percent = total ? Math.round((finished / total) * 100) : 0;
  const complete = finished === total;
  return {
    className: complete ? (counts.failed ? "finished-with-errors" : "finished") : "active",
    kicker: complete
      ? (counts.failed ? "Request finished with failures" : "Request complete")
      : "Request progress",
    percent,
    countsText: `${finished} of ${total} finished · ${percent}%`,
    detail: [
      `${counts.complete} complete`, `${counts.failed} failed`,
      `${counts.running} running`, `${counts.queued} queued`, `${counts.paused} paused`,
      unavailable ? `${unavailable} pending status` : "",
    ].filter(Boolean).join(" · "),
    complete,
  };
}

function renderRequestProgress(allJobs) {
  if (draggingRequestId) return;
  let changed = false;
  const cards = [...trackedRequests.values()]
    .sort((left, right) => right.createdAt - left.createdAt)
    .map((request, index) => {
      const state = requestProgressState(request, allJobs);
      if (state.complete && !request.completedAt) {
        request.completedAt = Date.now();
        changed = true;
      }
      const bodyId = `request-progress-body-${index}`;
      return {
        positioned: Boolean(request.position),
        html: `
        <article class="request-progress-card ${state.className} ${request.collapsed ? "collapsed" : ""}"
          data-request-card="${escapeHtml(request.id)}">
          <div class="request-progress-heading" data-drag-request="${escapeHtml(request.id)}">
            <div>
              <small>${escapeHtml(state.kicker)}</small>
              <strong title="${escapeHtml(request.label)}">${escapeHtml(request.label)}</strong>
            </div>
            <div class="request-progress-controls">
              <button type="button" class="request-progress-toggle"
                data-toggle-request="${escapeHtml(request.id)}"
                aria-expanded="${String(!request.collapsed)}" aria-controls="${bodyId}"
                aria-label="${request.collapsed ? "Expand" : "Collapse"} ${escapeHtml(request.label)} progress">
                ${request.collapsed ? "+" : "−"}
              </button>
              <button type="button" class="request-progress-close" data-close-request="${escapeHtml(request.id)}"
                aria-label="Close ${escapeHtml(request.label)} progress">×</button>
            </div>
          </div>
          <div class="request-progress-body" id="${bodyId}" ${request.collapsed ? "hidden" : ""}>
            <progress max="100" ${state.percent === null ? "" : `value="${state.percent}"`}></progress>
            <div class="request-progress-counts">${escapeHtml(state.countsText)}</div>
            <small>${escapeHtml(state.detail)}</small>
          </div>
        </article>
      `,
      };
    });
  requestProgressStack.innerHTML = `
    <div class="request-progress-dock">
      ${cards.filter((card) => !card.positioned).map((card) => card.html).join("")}
    </div>
    <div class="request-progress-canvas">
      ${cards.filter((card) => card.positioned).map((card) => card.html).join("")}
    </div>
  `;
  requestProgressStack.querySelectorAll("[data-request-card]").forEach((card) => {
    const request = trackedRequests.get(card.dataset.requestCard);
    if (!request) return;
    applyRequestCardPosition(card, request.position);
    enableRequestCardDragging(card, request);
  });
  requestProgressStack.querySelectorAll("[data-toggle-request]").forEach((button) => {
    button.addEventListener("click", () => {
      const request = trackedRequests.get(button.dataset.toggleRequest);
      if (!request) return;
      request.collapsed = !request.collapsed;
      saveTrackedRequests();
      renderRequestProgress(latestJobs);
    });
  });
  requestProgressStack.querySelectorAll("[data-close-request]").forEach((button) => {
    button.addEventListener("click", () => {
      trackedRequests.delete(button.dataset.closeRequest);
      saveTrackedRequests();
      renderRequestProgress(latestJobs);
    });
  });
  if (changed) saveTrackedRequests();
}

function applyRequestCardPosition(card, position) {
  if (!position || !Number.isFinite(Number(position.x)) || !Number.isFinite(Number(position.y))) {
    return;
  }
  card.classList.add("positioned");
  const maxX = Math.max(8, window.innerWidth - card.offsetWidth - 8);
  const maxY = Math.max(8, window.innerHeight - card.offsetHeight - 8);
  card.style.left = `${Math.min(Math.max(8, Number(position.x)), maxX)}px`;
  card.style.top = `${Math.min(Math.max(8, Number(position.y)), maxY)}px`;
}

function enableRequestCardDragging(card, request) {
  const handle = card.querySelector("[data-drag-request]");
  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || event.target.closest("button")) return;
    event.preventDefault();
    noteUserInteraction();
    draggingRequestId = request.id;
    const bounds = card.getBoundingClientRect();
    const offsetX = event.clientX - bounds.left;
    const offsetY = event.clientY - bounds.top;
    requestProgressStack.append(card);
    card.classList.add("positioned", "dragging");
    card.style.left = `${bounds.left}px`;
    card.style.top = `${bounds.top}px`;
    handle.setPointerCapture(event.pointerId);

    const move = (moveEvent) => {
      const maxX = Math.max(8, window.innerWidth - card.offsetWidth - 8);
      const maxY = Math.max(8, window.innerHeight - card.offsetHeight - 8);
      const x = Math.min(Math.max(8, moveEvent.clientX - offsetX), maxX);
      const y = Math.min(Math.max(8, moveEvent.clientY - offsetY), maxY);
      card.style.left = `${x}px`;
      card.style.top = `${y}px`;
    };
    const finish = () => {
      if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", finish);
      handle.removeEventListener("pointercancel", finish);
      request.position = {
        x: Number.parseFloat(card.style.left),
        y: Number.parseFloat(card.style.top),
      };
      draggingRequestId = null;
      card.classList.remove("dragging");
      saveTrackedRequests();
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", finish);
    handle.addEventListener("pointercancel", finish);
  });
}

function noteUserInteraction() {
  lastUserInteraction = Date.now();
  localStorage.setItem(REQUEST_LAST_INTERACTION_KEY, String(lastUserInteraction));
}

function requestProgressWatchdog() {
  const now = Date.now();
  let changed = false;
  trackedRequests.forEach((request, id) => {
    if (request.completedAt
        && now - Math.max(request.completedAt, lastUserInteraction) >= REQUEST_IDLE_TIMEOUT_MS) {
      trackedRequests.delete(id);
      changed = true;
    }
  });
  if (changed) {
    saveTrackedRequests();
    renderRequestProgress(latestJobs);
  }
}

function updateQueueSelectionControls() {
  const visible = [...jobs.querySelectorAll("[data-select-job]:not(:disabled)")];
  const selectedVisible = visible.filter((input) => selectedQueueJobs.has(input.dataset.selectJob));
  selectVisibleJobs.disabled = visible.length === 0;
  selectVisibleJobs.checked = visible.length > 0 && selectedVisible.length === visible.length;
  selectVisibleJobs.indeterminate = selectedVisible.length > 0 && selectedVisible.length < visible.length;
  selectedJobsCount.textContent = `${selectedQueueJobs.size} selected`;
  const failedCount = latestJobs.filter(
    (job) => job.status === "failed" && selectedQueueJobs.has(job.id),
  ).length;
  restartSelectedJobs.disabled = failedCount === 0;
  restartSelectedJobs.textContent = failedCount > 0
    ? `Restart failed (${failedCount})`
    : "Restart failed";
  deleteSelectedJobs.disabled = selectedQueueJobs.size === 0;
}

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[character],
  );
}

function imageSource(url) {
  return url ? `/api/bilibili/image?url=${encodeURIComponent(url)}` : "";
}

function safeExternalUrl(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch (_error) {
    return "";
  }
}

function formatJobTime(value) {
  if (!value) return "";
  const timestamp = String(value).includes("T") ? String(value) : `${value.replace(" ", "T")}Z`;
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString([], {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function historyGroupKey(entry) {
  const source = entry.source;
  if (source.collection_title || source.collection_id) {
    return [
      "collection",
      source.author_id || source.author,
      source.collection_kind,
      source.collection_id || source.collection_title,
    ].join(":");
  }
  return `video:${source.source_id}`;
}

function renderDownloadHistory(entries) {
  downloadHistoryGroups.clear();
  entries.forEach((entry) => {
    const key = historyGroupKey(entry);
    if (!downloadHistoryGroups.has(key)) {
      downloadHistoryGroups.set(key, {
        key,
        isCollection: key.startsWith("collection:"),
        title: entry.source.collection_title || entry.source.title,
        author: entry.source.author || "Unknown creator",
        coverUrl: entry.source.cover_url,
        entries: [],
      });
    }
    downloadHistoryGroups.get(key).entries.push(entry);
  });
  const groups = [...downloadHistoryGroups.values()];
  const collections = groups.filter((group) => group.isCollection).length;
  const singles = groups.length - collections;
  downloadHistorySummary.textContent = entries.length
    ? `${entries.length} videos · ${collections} collections · ${singles} individual`
    : "No local download history yet";
  downloadHistoryList.innerHTML = groups.length ? groups.map((group) => {
    const statusCounts = { complete: 0, failed: 0, queued: 0, running: 0 };
    group.entries.forEach((entry) => {
      if (["complete", "failed", "queued"].includes(entry.status)) {
        statusCounts[entry.status] += 1;
      } else {
        statusCounts.running += 1;
      }
    });
    const active = statusCounts.queued + statusCounts.running;
    const latest = group.entries[0];
    const sourceUrl = !group.isCollection ? safeExternalUrl(latest.source.url) : "";
    const statusText = [
      statusCounts.complete ? `${statusCounts.complete} complete` : "",
      statusCounts.failed ? `${statusCounts.failed} failed` : "",
      statusCounts.running ? `${statusCounts.running} running` : "",
      statusCounts.queued ? `${statusCounts.queued} queued` : "",
    ].filter(Boolean).join(" · ");
    return `
      <article class="download-history-card">
        ${group.coverUrl
          ? `<img src="${escapeHtml(imageSource(group.coverUrl))}" alt="" loading="lazy">`
          : '<div class="download-history-placeholder" aria-hidden="true">V</div>'}
        <div class="download-history-info">
          <span class="history-kind">${group.isCollection ? "Collection" : "Video"}</span>
          <strong title="${escapeHtml(group.title)}">${escapeHtml(group.title)}</strong>
          <small>${escapeHtml(group.author)} · ${group.entries.length} video${group.entries.length === 1 ? "" : "s"}</small>
          <small>${escapeHtml(statusText || "Pending")} · ${escapeHtml(formatJobTime(latest.created_at))}</small>
          ${sourceUrl ? `<a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">Open video ↗</a>` : ""}
        </div>
        <div class="download-history-actions">
          <button type="button" class="secondary" data-delete-history="${escapeHtml(group.key)}">
            Delete history
          </button>
          <button type="button" class="danger" data-delete-history-files="${escapeHtml(group.key)}"
            ${active ? "disabled title=\"Wait for active downloads to finish\"" : ""}>
            Delete history &amp; files
          </button>
        </div>
      </article>
    `;
  }).join("") : '<div class="empty">No local download history yet</div>';
  downloadHistoryList.querySelectorAll("[data-delete-history]").forEach((button) => {
    button.addEventListener("click", () => deleteDownloadHistoryGroup(
      button.dataset.deleteHistory, false,
    ));
  });
  downloadHistoryList.querySelectorAll("[data-delete-history-files]").forEach((button) => {
    button.addEventListener("click", () => deleteDownloadHistoryGroup(
      button.dataset.deleteHistoryFiles, true,
    ));
  });
}

async function pollDownloadHistory() {
  clearTimeout(historyPollTimer);
  historyPollTimer = null;
  try {
    const entries = await requestJson("/api/download-history?limit=5000");
    renderDownloadHistory(entries);
  } catch (error) {
    downloadHistorySummary.textContent = "History unavailable";
    downloadHistoryList.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  } finally {
    scheduleHistoryPolling();
  }
}

async function deleteDownloadHistoryGroup(key, deleteFiles) {
  const group = downloadHistoryGroups.get(key);
  if (!group) return;
  const target = group.isCollection
    ? `collection “${group.title}” and its ${group.entries.length} video record(s)`
    : `video history “${group.title}”`;
  const warning = deleteFiles
    ? `Delete ${target} and all downloaded/generated local files? This cannot be undone.`
    : `Delete ${target}? Local files and Processing Queue records will be kept.`;
  if (!window.confirm(warning)) return;
  downloadHistoryStatus.textContent = "Deleting local history…";
  try {
    const result = await requestJson("/api/download-history/batch-delete", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        source_ids: group.entries.map((entry) => entry.source.source_id),
        delete_files: deleteFiles,
      }),
    });
    downloadHistoryStatus.textContent = deleteFiles
      ? `${result.count} record(s) and ${result.removed_files.length} local file(s) deleted.`
      : `${result.count} local history record(s) deleted; files were kept.`;
    await pollDownloadHistory();
  } catch (error) {
    downloadHistoryStatus.textContent = error.message;
  }
}

function jobCreatedDateParts(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  return match ? { year: match[1], month: match[2], day: match[3] } : null;
}

function jobCreatedDateKey(value) {
  const parts = jobCreatedDateParts(value);
  return parts ? `${parts.year}-${parts.month}-${parts.day}` : "Unknown date";
}

function jobMatchesStatusFilter(job, filter) {
  if (!filter) return true;
  if (filter === "running") {
    return !["complete", "failed", "queued", "paused", "pausing"].includes(job.status);
  }
  if (filter === "paused") {
    return ["paused", "pausing"].includes(job.status);
  }
  return job.status === filter;
}

function setDateFilterOptions(data) {
  const selectedYear = queueYearFilter.value;
  const selectedMonth = queueMonthFilter.value;
  const selectedDay = queueDayFilter.value;
  const dates = data.map((job) => jobCreatedDateParts(job.created_at)).filter(Boolean);
  const years = [...new Set(dates.map((date) => date.year))].sort().reverse();
  queueYearFilter.innerHTML = `
    <option value="">All years</option>
    ${years.map((year) => `<option value="${year}">${year}</option>`).join("")}
  `;
  if (years.includes(selectedYear)) queueYearFilter.value = selectedYear;

  const months = queueYearFilter.value
    ? [...new Set(dates.filter((date) => date.year === queueYearFilter.value)
      .map((date) => date.month))].sort()
    : [];
  queueMonthFilter.innerHTML = `
    <option value="">All months</option>
    ${months.map((month) => `<option value="${month}">${month}</option>`).join("")}
  `;
  queueMonthFilter.disabled = !queueYearFilter.value;
  if (months.includes(selectedMonth)) queueMonthFilter.value = selectedMonth;

  const days = queueYearFilter.value && queueMonthFilter.value
    ? [...new Set(dates.filter((date) => date.year === queueYearFilter.value
      && date.month === queueMonthFilter.value).map((date) => date.day))].sort()
    : [];
  queueDayFilter.innerHTML = `
    <option value="">All days</option>
    ${days.map((day) => `<option value="${day}">${day}</option>`).join("")}
  `;
  queueDayFilter.disabled = !queueMonthFilter.value;
  if (days.includes(selectedDay)) queueDayFilter.value = selectedDay;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || `Request failed with status ${response.status}`);
  }
  return data;
}

function renderCreators() {
  if (!searchResults.length) {
    results.innerHTML = '<div class="empty">No matching results</div>';
    return;
  }
  results.innerHTML = searchResults.map((creator) => `
    <article class="video">
      <img src="${escapeHtml(imageSource(creator.avatar))}" alt="" loading="lazy">
      <div>
        <h3>${escapeHtml(creator.name)}</h3>
        <div class="meta">
          ${creator.fans} followers · ${creator.videos} videos<br>
          ${escapeHtml(creator.description)}
        </div>
      </div>
      <button type="button" data-creator="${escapeHtml(creator.name)}">Find Videos</button>
    </article>
  `).join("");
  results.querySelectorAll("[data-creator]").forEach((button) => {
    button.addEventListener("click", () => {
      select("#search-kind").value = "videos";
      select("#search-query").value = button.dataset.creator;
      select("#search-form").requestSubmit();
    });
  });
}

function renderVideos() {
  const chargingOnly = select("#charging-only").checked;
  const tag = select("#tag-filter").value.trim().toLowerCase();
  const filtered = searchResults.filter((video) => (
    (!chargingOnly || video.is_charging)
    && (!tag || (video.tags || []).some((value) => value.toLowerCase().includes(tag)))
  ));
  if (!filtered.length) {
    results.innerHTML = '<div class="empty">No matching results</div>';
    return;
  }
  results.innerHTML = filtered.map((video, index) => `
    <article class="video">
      <img src="${escapeHtml(imageSource(video.cover_url))}" alt="" loading="lazy">
      <div>
        <h3>
          ${escapeHtml(video.title)}
          ${video.is_charging ? '<span class="badge">Charging</span>' : ""}
        </h3>
        <div class="meta">
          ${escapeHtml(video.author)} · ${Math.round(video.duration / 60)} minutes ·
          ${(video.tags || []).map(escapeHtml).join(" / ")}
        </div>
      </div>
      <button type="button" data-video-index="${index}">Transcribe</button>
    </article>
  `).join("");
  results.querySelectorAll("[data-video-index]").forEach((button) => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await submitVideo(filtered[Number(button.dataset.videoIndex)]);
      } finally {
        button.disabled = false;
      }
    });
  });
}

function renderResults() {
  if (select("#search-kind").value === "creators") {
    renderCreators();
  } else {
    renderVideos();
  }
}

function collectionKey(kind, id) {
  return `${kind}:${id}`;
}

function videoChoice(video, parentCollectionKey = "") {
  const collectionSelection = parentCollectionKey
    ? creatorState.selectedCollections.get(parentCollectionKey)
    : null;
  const selectedByCollection = collectionSelection
    && !collectionSelection.excludedVideoIds.has(video.source_id);
  const checked = selectedByCollection || creatorState.selectedVideos.has(video.source_id);
  return `
    <label class="creator-video">
      <input type="checkbox" data-creator-video="${escapeHtml(video.source_id)}"
        ${parentCollectionKey ? `data-parent-collection="${escapeHtml(parentCollectionKey)}"` : ""}
        ${checked ? "checked" : ""}>
      <img src="${escapeHtml(imageSource(video.cover_url))}" alt="" loading="lazy">
      <span>
        <strong>${escapeHtml(video.title)}</strong>
        <small>${Math.max(1, Math.round(Number(video.duration || 0) / 60))} min</small>
      </span>
    </label>
  `;
}

function renderCreatorBrowser() {
  if (!creatorState) {
    creatorBrowser.hidden = true;
    return;
  }
  creatorBrowser.hidden = false;
  const state = creatorState;
  const wholeCollections = [...state.selectedCollections.values()].filter(
    (selection) => selection.excludedVideoIds.size === 0,
  ).length;
  const partialCollections = state.selectedCollections.size - wholeCollections;
  const selectedVideos = state.selectedVideos.size;
  const uploadItems = state.uploads.items.map((video) => videoChoice(video)).join("");
  creatorContent.innerHTML = `
    <div class="creator-profile">
      <img src="${escapeHtml(imageSource(state.creator.avatar))}" alt="" loading="lazy">
      <div>
        <span class="eyebrow">Creator library</span>
        <h3>${escapeHtml(state.creator.name)}</h3>
        <p>${escapeHtml(state.creator.description || `UID ${state.creator.id}`)}</p>
      </div>
    </div>

    <div class="batch-actions">
      <button type="button" data-batch-scope="all-collections"
        ${state.batching || !state.collectionTotal ? "disabled" : ""}>
        Process all ${state.collectionTotal || ""} collections
      </button>
      <button type="button" class="secondary" data-batch-scope="all-uploads"
        ${state.batching ? "disabled" : ""}>Process every upload</button>
      <p>Both options fetch every page in the background, remove duplicates, and add videos to the serial queue.</p>
    </div>

    <details class="creator-source" ${state.uploads.expanded ? "open" : ""}>
      <summary data-expand-uploads>
        <span><strong>All uploads</strong><small>Includes videos that are not in a collection</small></span>
        <span>${state.uploads.total ? `${state.uploads.items.length} of ${state.uploads.total}` : "Browse"}</span>
      </summary>
      <div class="creator-video-list">
        ${state.uploads.loading && !uploadItems ? '<div class="empty compact">Loading uploads…</div>' : uploadItems}
      </div>
      ${state.uploads.hasMore ? '<button type="button" class="load-more" data-more-uploads>Load more uploads</button>' : ""}
    </details>

    <div class="collection-heading">
      <div><span class="eyebrow">Collections</span><h3>Choose whole collections or individual videos</h3></div>
      <span>${state.collections.length} of ${state.collectionTotal} shown</span>
    </div>
    <div class="collection-list">
      ${state.collections.map((collection) => {
        const key = collectionKey(collection.kind, collection.id);
        const collectionSelection = state.selectedCollections.get(key);
        const wholeSelected = collectionSelection?.excludedVideoIds.size === 0;
        const hasSelectedLoadedVideo = collection.videos.some(
          (video) => state.selectedVideos.has(video.source_id),
        );
        const partialSelected = Boolean(
          (collectionSelection && !wholeSelected) || (!collectionSelection && hasSelectedLoadedVideo),
        );
        return `
          <article class="collection-card ${wholeSelected ? "selected" : ""} ${partialSelected ? "partial" : ""}">
            <div class="collection-summary">
              <label class="collection-check">
                <input type="checkbox" data-creator-collection="${escapeHtml(key)}"
                  data-partial="${partialSelected}"
                  ${wholeSelected ? "checked" : ""}>
                <img src="${escapeHtml(imageSource(collection.cover_url))}" alt="" loading="lazy">
                <span>
                  <strong>${escapeHtml(collection.title)}</strong>
                  <small>${collection.total} videos · ${collection.kind === "season" ? "collection" : "series"}</small>
                </span>
              </label>
              <button type="button" class="secondary compact-button"
                data-expand-collection="${escapeHtml(key)}">
                ${collection.expanded ? "Hide videos" : "Choose videos"}
              </button>
            </div>
            ${collection.expanded ? `
              <div class="creator-video-list">
                ${collection.loading && !collection.videos.length
                  ? '<div class="empty compact">Loading videos…</div>'
                  : collection.videos.map((video) => videoChoice(video, key)).join("")}
              </div>
              ${collection.hasMore ? `<button type="button" class="load-more"
                data-more-collection="${escapeHtml(key)}">Load more videos</button>` : ""}
            ` : ""}
          </article>
        `;
      }).join("") || '<div class="empty compact">No public collections found</div>'}
    </div>
    ${state.collectionsHasMore ? '<button type="button" class="load-more wide" data-more-collections>Load more collections</button>' : ""}

    <div class="selection-bar">
      <span><strong>${wholeCollections}</strong> whole, <strong>${partialCollections}</strong> partial collections and <strong>${selectedVideos}</strong> individual videos selected</span>
      <button type="button" data-batch-scope="selected"
        ${state.batching || (!state.selectedCollections.size && !selectedVideos) ? "disabled" : ""}>
        Add selection to queue
      </button>
    </div>
  `;
  bindCreatorControls();
}

function rememberVideos(videos) {
  videos.forEach((video) => creatorState.videoIndex.set(video.source_id, video));
}

async function loadMoreCollections() {
  if (!creatorState || creatorState.collectionsLoading) return;
  creatorState.collectionsLoading = true;
  renderCreatorBrowser();
  try {
    const page = creatorState.collectionPage + 1;
    const data = await requestJson(
      `/api/creators/${creatorState.creator.id}/collections?page=${page}&page_size=6`,
    );
    data.items.forEach((item) => {
      const key = collectionKey(item.kind, item.id);
      if (!creatorState.collectionIndex.has(key)) {
        const collection = {
          ...item,
          expanded: false,
          loading: false,
          videos: [],
          videoPage: 0,
          hasMore: item.total > 0,
        };
        creatorState.collectionIndex.set(key, collection);
        creatorState.collections.push(collection);
      }
    });
    creatorState.collectionPage = data.page;
    creatorState.collectionTotal = data.total;
    creatorState.collectionsHasMore = data.has_more;
  } catch (error) {
    creatorStatus.textContent = error.message;
  } finally {
    creatorState.collectionsLoading = false;
    renderCreatorBrowser();
  }
}

async function loadMoreUploads() {
  if (!creatorState || creatorState.uploads.loading) return;
  creatorState.uploads.loading = true;
  renderCreatorBrowser();
  try {
    const page = creatorState.uploads.page + 1;
    const data = await requestJson(
      `/api/creators/${creatorState.creator.id}/videos?page=${page}&page_size=12`,
    );
    rememberVideos(data.items);
    creatorState.uploads.items.push(...data.items.filter(
      (item) => !creatorState.uploads.items.some((video) => video.source_id === item.source_id),
    ));
    creatorState.uploads.page = data.page;
    creatorState.uploads.total = data.total;
    creatorState.uploads.hasMore = data.has_more;
  } catch (error) {
    creatorStatus.textContent = error.message;
  } finally {
    creatorState.uploads.loading = false;
    renderCreatorBrowser();
  }
}

async function loadMoreCollectionVideos(key) {
  const collection = creatorState?.collectionIndex.get(key);
  if (!collection || collection.loading) return;
  collection.loading = true;
  renderCreatorBrowser();
  try {
    const page = collection.videoPage + 1;
    const data = await requestJson(
      `/api/creators/${creatorState.creator.id}/collections/${collection.kind}/${collection.id}/videos?page=${page}&page_size=12`,
    );
    const contextualItems = data.items.map((item) => ({
      ...item,
      collection_kind: collection.kind,
      collection_id: collection.id,
      collection_title: collection.title,
    }));
    rememberVideos(contextualItems);
    collection.videos.push(...contextualItems.filter(
      (item) => !collection.videos.some((video) => video.source_id === item.source_id),
    ));
    collection.videoPage = data.page;
    collection.hasMore = data.has_more;
  } catch (error) {
    creatorStatus.textContent = error.message;
  } finally {
    collection.loading = false;
    renderCreatorBrowser();
  }
}

async function submitCreatorBatch(scope) {
  const state = creatorState;
  if (!state || state.batching) return;
  const payload = {
    creator_id: state.creator.id,
    all_collections: scope === "all-collections",
    all_uploads: scope === "all-uploads",
    collections: scope === "selected" ? [...state.selectedCollections.values()].map(
      (selection) => ({
        kind: selection.kind,
        id: selection.id,
        title: selection.title,
        excluded_video_ids: [...selection.excludedVideoIds],
      }),
    ) : [],
    videos: scope === "selected" ? [...state.selectedVideos.values()] : [],
    language: "zh-CN",
    synthesize: false,
    force_refresh: select("#force-refresh").checked,
  };
  if (scope !== "selected") {
    const label = scope === "all-uploads" ? "every upload" : "every video in all collections";
    if (!window.confirm(`Add ${label} to the serial processing queue?`)) return;
  }
  state.batching = true;
  creatorStatus.textContent = "Checking processing services…";
  renderCreatorBrowser();
  if (!await confirmProcessingServices(payload.synthesize)) {
    creatorStatus.textContent = "Request cancelled. Make the processing services ready, then try again.";
    state.batching = false;
    renderCreatorBrowser();
    return;
  }
  creatorStatus.textContent = "Expanding the selection across all pages…";
  const requestLabel = `${state.creator.name} · ${scope === "all-collections" ? "all collections" : scope === "all-uploads" ? "all uploads" : "selected videos"}`;
  const progressRequestId = beginRequestProgress(
    requestLabel, "Expanding the selection across all pages…",
  );
  renderCreatorBrowser();
  try {
    const data = await requestJson("/api/jobs/creator-batch", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    creatorStatus.textContent = `${data.submitted} unique videos added to the serial queue.`;
    trackRequestJobs(progressRequestId, data.job_ids, requestLabel);
    state.selectedCollections.clear();
    state.selectedVideos.clear();
    await Promise.all([pollJobs(), pollDownloadHistory()]);
  } catch (error) {
    creatorStatus.textContent = error.message;
    failRequestProgress(progressRequestId, error.message);
  } finally {
    state.batching = false;
    renderCreatorBrowser();
  }
}

function bindCreatorControls() {
  creatorContent.querySelectorAll("[data-creator-collection]").forEach((input) => {
    input.indeterminate = input.dataset.partial === "true";
    input.addEventListener("change", () => {
      const collection = creatorState.collectionIndex.get(input.dataset.creatorCollection);
      if (input.checked) {
        creatorState.selectedCollections.set(input.dataset.creatorCollection, {
          kind: collection.kind,
          id: collection.id,
          title: collection.title,
          excludedVideoIds: new Set(),
        });
      } else {
        creatorState.selectedCollections.delete(input.dataset.creatorCollection);
      }
      renderCreatorBrowser();
    });
  });
  creatorContent.querySelectorAll("[data-creator-video]").forEach((input) => {
    input.addEventListener("change", () => {
      const sourceId = input.dataset.creatorVideo;
      const parentKey = input.dataset.parentCollection;
      const collectionSelection = parentKey
        ? creatorState.selectedCollections.get(parentKey)
        : null;
      if (collectionSelection) {
        if (input.checked) {
          collectionSelection.excludedVideoIds.delete(sourceId);
        } else {
          collectionSelection.excludedVideoIds.add(sourceId);
          creatorState.selectedVideos.delete(sourceId);
        }
      } else if (input.checked) {
        creatorState.selectedVideos.set(sourceId, creatorState.videoIndex.get(sourceId));
      } else {
        creatorState.selectedVideos.delete(sourceId);
      }
      renderCreatorBrowser();
    });
  });
  creatorContent.querySelectorAll("[data-expand-collection]").forEach((button) => {
    button.addEventListener("click", () => {
      const collection = creatorState.collectionIndex.get(button.dataset.expandCollection);
      collection.expanded = !collection.expanded;
      renderCreatorBrowser();
      if (collection.expanded && !collection.videoPage) loadMoreCollectionVideos(button.dataset.expandCollection);
    });
  });
  creatorContent.querySelector("[data-expand-uploads]")?.addEventListener("click", (event) => {
    event.preventDefault();
    creatorState.uploads.expanded = !creatorState.uploads.expanded;
    renderCreatorBrowser();
    if (creatorState.uploads.expanded && !creatorState.uploads.page) loadMoreUploads();
  });
  creatorContent.querySelector("[data-more-collections]")?.addEventListener("click", loadMoreCollections);
  creatorContent.querySelector("[data-more-uploads]")?.addEventListener("click", loadMoreUploads);
  creatorContent.querySelectorAll("[data-more-collection]").forEach((button) => {
    button.addEventListener("click", () => loadMoreCollectionVideos(button.dataset.moreCollection));
  });
  creatorContent.querySelectorAll("[data-batch-scope]").forEach((button) => {
    button.addEventListener("click", () => submitCreatorBatch(button.dataset.batchScope));
  });
}

select("#creator-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  creatorStatus.textContent = "Resolving creator and collections…";
  creatorState = null;
  renderCreatorBrowser();
  try {
    const creator = await requestJson(
      `/api/creators/from-url?url=${encodeURIComponent(select("#creator-url").value)}`,
    );
    creatorState = {
      creator,
      batching: false,
      collections: [],
      collectionIndex: new Map(),
      collectionPage: 0,
      collectionTotal: 0,
      collectionsHasMore: false,
      collectionsLoading: false,
      uploads: { items: [], page: 0, total: 0, hasMore: true, expanded: false, loading: false },
      selectedCollections: new Map(),
      selectedVideos: new Map(),
      videoIndex: new Map(),
    };
    renderCreatorBrowser();
    await loadMoreCollections();
    creatorStatus.textContent = `Loaded ${creatorState.collectionTotal} collections for ${creator.name}.`;
  } catch (error) {
    creatorStatus.textContent = error.message;
    creatorState = null;
    renderCreatorBrowser();
  } finally {
    button.disabled = false;
  }
});

function jobPayload(extra) {
  return JSON.stringify({
    ...extra,
    language: "zh-CN",
    synthesize: false,
    force_refresh: select("#force-refresh").checked,
  });
}

select("#search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  results.innerHTML = '<div class="empty">Searching…</div>';
  const kind = select("#search-kind").value;
  const endpoint = kind === "creators" ? "/api/creators" : "/api/search";
  try {
    searchResults = await requestJson(
      `${endpoint}?q=${encodeURIComponent(select("#search-query").value)}`,
    );
    renderResults();
  } catch (error) {
    results.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  }
});

select("#url-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  let progressRequestId = null;
  try {
    urlStatus.textContent = "Checking processing services…";
    if (!await confirmProcessingServices(false)) {
      urlStatus.textContent = "Request cancelled. Make the processing services ready, then try again.";
      return;
    }
    urlStatus.textContent = "Resolving video…";
    progressRequestId = beginRequestProgress("Bilibili video", "Resolving video details…");
    const data = await requestJson("/api/jobs/url", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: jobPayload({ url: select("#video-url").value }),
    });
    urlStatus.textContent = `Added to queue: ${data.video.title}`;
    trackRequestJobs(progressRequestId, [data.id], data.video.title);
    select("#video-url").value = "";
    await Promise.all([pollJobs(), pollDownloadHistory()]);
  } catch (error) {
    urlStatus.textContent = error.message;
    if (progressRequestId) failRequestProgress(progressRequestId, error.message);
  } finally {
    button.disabled = false;
  }
});

async function submitVideo(video) {
  urlStatus.textContent = "Checking processing services…";
  if (!await confirmProcessingServices(false)) {
    urlStatus.textContent = "Request cancelled. Make the processing services ready, then try again.";
    return;
  }
  const progressRequestId = beginRequestProgress(video.title, "Adding video to the queue…");
  try {
    const data = await requestJson("/api/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: jobPayload({ video }),
    });
    trackRequestJobs(progressRequestId, [data.id], video.title);
    await Promise.all([pollJobs(), pollDownloadHistory()]);
  } catch (error) {
    urlStatus.textContent = error.message;
    failRequestProgress(progressRequestId, error.message);
  }
}

async function pollJobs() {
  clearTimeout(jobPollTimer);
  jobPollTimer = null;
  const wasPolling = jobsPollingActive;
  try {
    const data = await requestJson("/api/jobs?limit=5000");
    latestJobs = data;
    jobsPollingActive = data.some(jobNeedsPolling);
    const existingJobIds = new Set(data.map((job) => job.id));
    [...selectedQueueJobs].forEach((jobId) => {
      if (!existingJobIds.has(jobId)) selectedQueueJobs.delete(jobId);
    });
    const selectedCreator = queueCreatorFilter.value;
    const selectedCollection = queueCollectionFilter.value;
    const creators = [...new Set(data.map((job) => job.source.author || "Unknown creator"))]
      .sort((left, right) => left.localeCompare(right));
    queueCreatorFilter.innerHTML = `
      <option value="">All creators</option>
      ${creators.map((creator) => `<option value="${escapeHtml(creator)}">${escapeHtml(creator)}</option>`).join("")}
    `;
    if (creators.includes(selectedCreator)) queueCreatorFilter.value = selectedCreator;
    const collections = [...new Set(data.map((job) => job.source.collection_title).filter(Boolean))]
      .sort((left, right) => left.localeCompare(right));
    const hasUnassigned = data.some((job) => !job.source.collection_title);
    queueCollectionFilter.innerHTML = `
      <option value="">All collections</option>
      ${collections.map((collection) => `<option value="${escapeHtml(collection)}">${escapeHtml(collection)}</option>`).join("")}
      ${hasUnassigned ? '<option value="__none__">No collection data</option>' : ""}
    `;
    if (collections.includes(selectedCollection)
        || (selectedCollection === "__none__" && hasUnassigned)) {
      queueCollectionFilter.value = selectedCollection;
    }
    setDateFilterOptions(data);
    const filteredData = data.filter((job) => {
      const creatorMatches = !queueCreatorFilter.value
        || (job.source.author || "Unknown creator") === queueCreatorFilter.value;
      const collectionMatches = !queueCollectionFilter.value
        || (queueCollectionFilter.value === "__none__"
          ? !job.source.collection_title
          : job.source.collection_title === queueCollectionFilter.value);
      const created = jobCreatedDateParts(job.created_at);
      const yearMatches = !queueYearFilter.value || created?.year === queueYearFilter.value;
      const monthMatches = !queueMonthFilter.value || created?.month === queueMonthFilter.value;
      const dayMatches = !queueDayFilter.value || created?.day === queueDayFilter.value;
      const statusMatches = jobMatchesStatusFilter(job, queueStatusFilter.value);
      return creatorMatches && collectionMatches && yearMatches && monthMatches
        && dayMatches && statusMatches;
    });
    const activeJobs = filteredData.filter(jobNeedsPolling).length;
    queueSummary.textContent = data.length
      ? `${filteredData.length}${filteredData.length !== data.length ? ` of ${data.length}` : ""} jobs${activeJobs ? ` · ${activeJobs} active` : ""}`
      : "No jobs";
    const renderJob = (job) => {
      const outputEntries = Object.entries(job.outputs || {});
      const expanded = expandedQueueJobs.has(job.id);
      const author = job.source.author || "Unknown creator";
      const collectionTitle = job.source.collection_title || "No collection data";
      const sourceUrl = safeExternalUrl(job.source.url);
      const timeValue = job.downloaded_at || job.created_at;
      const timePrefix = job.downloaded_at ? "Downloaded" : "Added";
      const outputPaths = job.status === "complete" && outputEntries.length
        ? `<details class="job-files" data-file-list="${escapeHtml(job.id)}"
            ${expandedFileJobs.has(job.id) ? "open" : ""}>
            <summary>
              <span>Files</span>
              <small>${outputEntries.length} outputs · hover to expand</small>
            </summary>
            <div class="job-file-list">
              ${outputEntries.map(([kind, path]) => `
              <div class="job-file">
                <div class="job-file-info">
                  <span>${escapeHtml(kind.replaceAll("_", " "))}</span>
                  <code>${escapeHtml(path)}</code>
                </div>
                <div class="job-file-actions">
                  <button type="button" class="secondary" data-output-action="open"
                    data-output-job="${escapeHtml(job.id)}" data-output-key="${escapeHtml(kind)}">
                    Open File
                  </button>
                  <button type="button" class="secondary" data-output-action="reveal"
                    data-output-job="${escapeHtml(job.id)}" data-output-key="${escapeHtml(kind)}">
                    Show in Finder
                  </button>
                </div>
              </div>
              `).join("")}
            </div>
          </details>`
        : "";
      const canDelete = ["complete", "failed"].includes(job.status) || !job.session_active;
      const canRestart = job.status === "failed";
      const canResume = job.status === "paused" || job.status === "pausing";
      const canPause = !canDelete && !canResume;
      const executionAction = canRestart ? "restart" : (canResume ? "resume" : "pause");
      const executionLabel = canRestart ? "Restart" : (canResume ? "Resume" : "Pause");
      return `
      <div class="job">
        <div class="job-header">
          <label class="job-selector" title="Select this history record">
            <input type="checkbox" data-select-job="${escapeHtml(job.id)}"
              ${selectedQueueJobs.has(job.id) ? "checked" : ""} ${canDelete ? "" : "disabled"}>
            <span class="sr-only">Select ${escapeHtml(job.source.title)}</span>
          </label>
          <button type="button" class="job-summary" data-toggle-job="${escapeHtml(job.id)}"
            aria-expanded="${expanded}">
            <span class="job-summary-main">
              <strong>${escapeHtml(job.source.title)}</strong>
              <span class="job-tags">
                <span class="creator-tag">${escapeHtml(author)}</span>
                <span class="collection-tag">${escapeHtml(collectionTitle)}</span>
                <time datetime="${escapeHtml(timeValue)}">${timePrefix} ${escapeHtml(formatJobTime(timeValue))}</time>
              </span>
            </span>
            <span class="job-summary-side">
              <span class="job-status ${escapeHtml(job.status)}">${escapeHtml(job.status)}</span>
              <span class="job-disclosure" aria-hidden="true">${expanded ? "−" : "+"}</span>
            </span>
          </button>
          ${job.status === "complete" || (canDelete && !canRestart) ? "" : `<button type="button"
            class="job-control ${executionAction}"
            data-${executionAction}-job="${escapeHtml(job.id)}"
            title="${executionLabel} processing"
            aria-label="${executionLabel} ${escapeHtml(job.source.title)}"
            ${canPause || canResume || canRestart ? "" : "disabled"}>${executionLabel}</button>`}
          <button type="button" class="quick-delete" data-quick-delete-job="${escapeHtml(job.id)}"
            title="Delete history record" aria-label="Delete ${escapeHtml(job.source.title)}"
            ${canDelete ? "" : "disabled"}>×</button>
        </div>
        <div class="bar"><i style="width: ${job.progress * 100}%"></i></div>
        <div class="job-body" ${expanded ? "" : "hidden"}>
          <small>${escapeHtml(job.message)}</small>
          <div class="job-source-link">
            <span>Source video</span>
            ${sourceUrl ? `
              <div>
                <a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer"
                  title="Open original video">${escapeHtml(sourceUrl)}</a>
                <button type="button" class="secondary" data-copy-job-link="${escapeHtml(sourceUrl)}">
                  Copy link
                </button>
              </div>
            ` : '<small>Source link unavailable</small>'}
          </div>
          ${outputPaths}
          <div class="job-actions">
            <button type="button" class="secondary" data-delete-job="${escapeHtml(job.id)}"
              ${canDelete ? "" : "disabled"}>Delete Record</button>
            <button type="button" class="danger" data-delete-files="${escapeHtml(job.id)}"
              ${canDelete ? "" : "disabled"}>Delete Record &amp; Files</button>
          </div>
        </div>
      </div>
    `;
    };
    const jobsByDate = new Map();
    filteredData.forEach((job) => {
      const dateKey = jobCreatedDateKey(job.created_at);
      if (!jobsByDate.has(dateKey)) jobsByDate.set(dateKey, []);
      jobsByDate.get(dateKey).push(job);
    });
    jobs.innerHTML = filteredData.length ? [...jobsByDate.entries()].map(([date, dateJobs]) => {
      const active = dateJobs.filter(jobNeedsPolling).length;
      return `
        <details class="queue-date-group" data-queue-date="${escapeHtml(date)}"
          ${expandedQueueDates.has(date) ? "open" : ""}>
          <summary>
            <span>${escapeHtml(date)}</span>
            <small>${dateJobs.length} job${dateJobs.length === 1 ? "" : "s"}${active ? ` · ${active} active` : ""}</small>
          </summary>
          <div class="queue-date-jobs">${dateJobs.map(renderJob).join("")}</div>
        </details>
      `;
    }).join("") : '<div class="empty">No jobs match the current filters</div>';
    jobs.querySelectorAll("[data-queue-date]").forEach((group) => {
      group.addEventListener("toggle", () => {
        if (group.open) expandedQueueDates.add(group.dataset.queueDate);
        else expandedQueueDates.delete(group.dataset.queueDate);
      });
    });
    jobs.querySelectorAll("[data-toggle-job]").forEach((button) => {
      button.addEventListener("click", () => {
        const jobId = button.dataset.toggleJob;
        if (expandedQueueJobs.has(jobId)) {
          expandedQueueJobs.delete(jobId);
        } else {
          expandedQueueJobs.add(jobId);
        }
        pollJobs();
      });
    });
    jobs.querySelectorAll("[data-delete-job]").forEach((button) => {
      button.addEventListener("click", () => deleteJob(button.dataset.deleteJob, false));
    });
    jobs.querySelectorAll("[data-delete-files]").forEach((button) => {
      button.addEventListener("click", () => deleteJob(button.dataset.deleteFiles, true));
    });
    jobs.querySelectorAll("[data-quick-delete-job]").forEach((button) => {
      button.addEventListener("click", () => deleteJob(button.dataset.quickDeleteJob, false));
    });
    jobs.querySelectorAll("[data-pause-job]").forEach((button) => {
      button.addEventListener("click", () => updateJobExecution(button.dataset.pauseJob, "pause"));
    });
    jobs.querySelectorAll("[data-resume-job]").forEach((button) => {
      button.addEventListener("click", () => updateJobExecution(button.dataset.resumeJob, "resume"));
    });
    jobs.querySelectorAll("[data-restart-job]").forEach((button) => {
      button.addEventListener("click", () => updateJobExecution(button.dataset.restartJob, "restart"));
    });
    jobs.querySelectorAll("[data-select-job]").forEach((input) => {
      input.addEventListener("change", () => {
        if (input.checked) selectedQueueJobs.add(input.dataset.selectJob);
        else selectedQueueJobs.delete(input.dataset.selectJob);
        updateQueueSelectionControls();
      });
    });
    jobs.querySelectorAll("[data-copy-job-link]").forEach((button) => {
      button.addEventListener("click", () => copyJobLink(button.dataset.copyJobLink));
    });
    jobs.querySelectorAll("[data-output-action]").forEach((button) => {
      button.addEventListener("click", () => openJobOutput(
        button.dataset.outputJob,
        button.dataset.outputKey,
        button.dataset.outputAction,
      ));
    });
    jobs.querySelectorAll("[data-file-list]").forEach((fileList) => {
      const jobId = fileList.dataset.fileList;
      let collapseTimer;
      const expand = () => {
        clearTimeout(collapseTimer);
        fileList.open = true;
        expandedFileJobs.add(jobId);
      };
      const collapseWhenInactive = () => {
        clearTimeout(collapseTimer);
        collapseTimer = setTimeout(() => {
          const pointerInside = fileList.matches(":hover");
          const focusInside = fileList.contains(document.activeElement);
          if (!pointerInside && !focusInside) {
            fileList.open = false;
            expandedFileJobs.delete(jobId);
          }
        }, 450);
      };
      fileList.addEventListener("mouseenter", expand);
      fileList.addEventListener("mouseleave", collapseWhenInactive);
      fileList.addEventListener("focusin", expand);
      fileList.addEventListener("focusout", collapseWhenInactive);
      fileList.addEventListener("toggle", () => {
        if (fileList.open) {
          expandedFileJobs.add(jobId);
        } else {
          expandedFileJobs.delete(jobId);
        }
      });
      if (fileList.matches(":hover")) expand();
    });
    updateQueueSelectionControls();
    renderRequestProgress(data);
    if (wasPolling && !jobsPollingActive) pollDownloadHistory();
  } catch (error) {
    queueSummary.textContent = "Queue unavailable";
    jobs.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  } finally {
    scheduleJobPolling();
    scheduleHistoryPolling();
  }
}

async function openJobOutput(jobId, outputKey, action) {
  queueStatus.textContent = action === "reveal" ? "Opening Finder…" : "Opening file…";
  try {
    const result = await requestJson(
      `/api/jobs/${encodeURIComponent(jobId)}/outputs/${encodeURIComponent(outputKey)}/${action}`,
      { method: "POST" },
    );
    queueStatus.textContent = action === "reveal"
      ? `Revealed in Finder: ${result.path}`
      : `Opened: ${result.path}`;
  } catch (error) {
    queueStatus.textContent = error.message;
  }
}

async function copyJobLink(url) {
  try {
    await navigator.clipboard.writeText(url);
    queueStatus.textContent = "Video link copied to the clipboard.";
  } catch (_error) {
    const input = document.createElement("textarea");
    input.value = url;
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.append(input);
    input.select();
    const copied = document.execCommand("copy");
    input.remove();
    queueStatus.textContent = copied
      ? "Video link copied to the clipboard."
      : "Could not copy the video link. Select the URL and copy it manually.";
  }
}

async function updateJobExecution(jobId, action) {
  if (action === "restart") {
    const job = latestJobs.find((candidate) => candidate.id === jobId);
    queueStatus.textContent = "Checking processing services…";
    if (!await confirmProcessingServices(Boolean(job?.synthesize))) {
      queueStatus.textContent = "Restart cancelled. Make the processing services ready, then try again.";
      return;
    }
  }
  queueStatus.textContent = action === "pause"
    ? "Requesting a safe pause…"
    : (action === "restart" ? "Restarting failed task…" : "Resuming…");
  try {
    const job = await requestJson(
      `/api/jobs/${encodeURIComponent(jobId)}/${action}`,
      { method: "POST" },
    );
    if (action === "restart") {
      reactivateTrackedRequests([jobId]);
    }
    queueStatus.textContent = action === "pause"
      ? (job.status === "paused"
        ? "Task paused. Its completed progress has been kept."
        : "Pause requested. The current step will finish safely before the task pauses.")
      : (action === "restart" ? "Failed task restarted and added to the queue." : "Task resumed.");
    await Promise.all([pollJobs(), pollDownloadHistory()]);
  } catch (error) {
    queueStatus.textContent = error.message;
  }
}

function reactivateTrackedRequests(jobIds) {
  trackedRequests.forEach((request) => {
    if (request.jobIds?.some((jobId) => jobIds.includes(jobId))) {
      request.state = "active";
      request.completedAt = null;
    }
  });
  saveTrackedRequests();
}

async function restartSelectedFailedJobs() {
  const jobIds = latestJobs
    .filter((job) => job.status === "failed" && selectedQueueJobs.has(job.id))
    .map((job) => job.id);
  if (!jobIds.length) return;
  if (!window.confirm(`Restart ${jobIds.length} selected failed task(s)?`)) return;

  const needsSynthesis = latestJobs.some(
    (job) => jobIds.includes(job.id) && Boolean(job.synthesize),
  );
  queueStatus.textContent = "Checking processing services…";
  if (!await confirmProcessingServices(needsSynthesis)) {
    queueStatus.textContent = "Restart cancelled. Make the processing services ready, then try again.";
    return;
  }

  queueStatus.textContent = `Restarting ${jobIds.length} failed task(s)…`;
  restartSelectedJobs.disabled = true;
  try {
    const result = await requestJson("/api/jobs/batch-restart", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ job_ids: jobIds }),
    });
    result.restarted.forEach((jobId) => selectedQueueJobs.delete(jobId));
    reactivateTrackedRequests(result.restarted);
    queueStatus.textContent = `${result.count} failed task(s) restarted and added to the queue.`;
    await Promise.all([pollJobs(), pollDownloadHistory()]);
  } catch (error) {
    queueStatus.textContent = error.message;
    updateQueueSelectionControls();
  }
}

async function deleteJob(jobId, deleteFiles) {
  const warning = deleteFiles
    ? "Delete this queue record and its downloaded/generated local files? This cannot be undone."
    : "Delete this queue record? Local files will be kept.";
  if (!window.confirm(warning)) return;
  queueStatus.textContent = "Deleting…";
  try {
    const result = await requestJson(
      `/api/jobs/${encodeURIComponent(jobId)}?delete_files=${deleteFiles}`,
      { method: "DELETE" },
    );
    queueStatus.textContent = deleteFiles
      ? `Record deleted; ${result.removed_files.length} local file(s) removed.`
      : "Queue record deleted; local files were kept.";
    selectedQueueJobs.delete(jobId);
    await pollJobs();
  } catch (error) {
    queueStatus.textContent = error.message;
  }
}

async function deleteSelectedJobRecords() {
  const jobIds = [...selectedQueueJobs];
  if (!jobIds.length) return;
  if (!window.confirm(`Delete ${jobIds.length} selected history record(s)? Local files will be kept.`)) return;
  queueStatus.textContent = `Deleting ${jobIds.length} record(s)…`;
  deleteSelectedJobs.disabled = true;
  try {
    const result = await requestJson("/api/jobs/batch-delete", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ job_ids: jobIds }),
    });
    selectedQueueJobs.clear();
    queueStatus.textContent = `${result.count} history record(s) deleted; local files were kept.`;
    await pollJobs();
  } catch (error) {
    queueStatus.textContent = error.message;
    updateQueueSelectionControls();
  }
}

function toggleLlmSettings() {
  const useApi = select("#llm-backend").value === "openai_compatible";
  select("#codex-settings").hidden = useApi;
  select("#api-settings").hidden = !useApi;
  select("#codex-settings").querySelectorAll("input").forEach((input) => {
    input.disabled = useApi;
  });
  select("#api-settings").querySelectorAll("input").forEach((input) => {
    input.disabled = !useApi;
  });
}

function runtimeSettingsPayload() {
  return {
    media_dir: select("#media-dir").value.trim(),
    library_dir: select("#library-dir").value.trim(),
    mlx_base_url: select("#mlx-base-url").value.trim(),
    mlx_audio_command: select("#mlx-command").value.trim(),
    llm_backend: select("#llm-backend").value,
    codex_cli_path: select("#codex-cli-path").value.trim(),
    codex_model: select("#codex-model").value.trim(),
    codex_timeout_seconds: Number(select("#codex-timeout").value),
    llm_base_url: select("#llm-base-url").value.trim(),
    llm_model: select("#llm-model").value.trim(),
  };
}

async function saveSettings() {
  const data = await requestJson("/api/settings", {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(runtimeSettingsPayload()),
  });
  settingsStatus.textContent = "Settings saved.";
  return data;
}

async function loadSettings() {
  try {
    const data = await requestJson("/api/settings");
    select("#media-dir").value = data.media_dir;
    select("#library-dir").value = data.library_dir;
    select("#mlx-base-url").value = data.mlx_base_url;
    select("#mlx-command").value = data.mlx_audio_command;
    select("#llm-backend").value = data.llm_backend;
    select("#codex-cli-path").value = data.codex_cli_path;
    select("#codex-model").value = data.codex_model;
    select("#codex-timeout").value = data.codex_timeout_seconds;
    select("#llm-base-url").value = data.llm_base_url;
    select("#llm-model").value = data.llm_model;
    toggleLlmSettings();
  } catch (error) {
    settingsStatus.textContent = error.message;
  }
}

function renderMlxStatus(status) {
  const badge = select("#mlx-state");
  badge.className = `service-badge ${status.state}`;
  badge.textContent = status.state;
  select("#mlx-message").textContent = status.pid
    ? `${status.message} (PID ${status.pid})`
    : status.message;
  select("#mlx-log").textContent = status.log_tail || "No managed-process log yet.";
  select("#mlx-start").disabled = status.reachable || (status.managed && status.state === "starting");
  select("#mlx-stop").disabled = !status.managed;
}

async function pollMlxStatus() {
  clearTimeout(mlxPollTimer);
  mlxPollTimer = null;
  try {
    const status = await requestJson("/api/mlx/status");
    renderMlxStatus(status);
    scheduleMlxPolling(status);
  } catch (error) {
    select("#mlx-message").textContent = error.message;
    scheduleMlxPolling(null);
  }
}

select("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  settingsStatus.textContent = "Saving…";
  try {
    await saveSettings();
    await pollMlxStatus();
  } catch (error) {
    settingsStatus.textContent = error.message;
  }
});

select("#llm-backend").addEventListener("change", toggleLlmSettings);
select("#mlx-start").addEventListener("click", async () => {
  if (!select("#settings-form").reportValidity()) return;
  settingsStatus.textContent = "Saving settings…";
  try {
    await saveSettings();
    const status = await requestJson("/api/mlx/start", { method: "POST" });
    renderMlxStatus(status);
    scheduleMlxPolling(status);
  } catch (error) {
    settingsStatus.textContent = error.message;
  }
});

select("#mlx-stop").addEventListener("click", async () => {
  try {
    const status = await requestJson("/api/mlx/stop", { method: "POST" });
    renderMlxStatus(status);
    scheduleMlxPolling(status);
  } catch (error) {
    settingsStatus.textContent = error.message;
  }
});

select("#charging-only").addEventListener("change", renderResults);
select("#tag-filter").addEventListener("input", renderResults);
select("#refresh-download-history").addEventListener("click", pollDownloadHistory);
addVideosTab.addEventListener("click", () => {
  activateAppTab("add");
  scheduleHistoryPolling();
});
downloadHistoryTab.addEventListener("click", () => {
  activateAppTab("history");
  if (!isStaticPreview) Promise.all([pollJobs(), pollDownloadHistory()]);
});
[addVideosTab, downloadHistoryTab].forEach((tab) => {
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const target = tab === addVideosTab ? "history" : "add";
    activateAppTab(target, true);
    if (!isStaticPreview && target === "history") {
      Promise.all([pollJobs(), pollDownloadHistory()]);
    } else if (target === "add") {
      scheduleHistoryPolling();
    }
  });
});
downloadHistoryToggle.addEventListener("click", () => {
  const expanded = downloadHistoryToggle.getAttribute("aria-expanded") === "true";
  downloadHistoryToggle.setAttribute("aria-expanded", String(!expanded));
  downloadHistoryContent.hidden = expanded;
  select(".download-history-toggle-label").textContent = expanded ? "Expand" : "Collapse";
});
queueToggle.addEventListener("click", () => {
  const expanded = queueToggle.getAttribute("aria-expanded") === "true";
  queueToggle.setAttribute("aria-expanded", String(!expanded));
  queueContent.hidden = expanded;
  select(".queue-toggle-label").textContent = expanded ? "Expand" : "Collapse";
});
queueCreatorFilter.addEventListener("change", pollJobs);
queueCollectionFilter.addEventListener("change", pollJobs);
queueStatusFilter.addEventListener("change", pollJobs);
queueYearFilter.addEventListener("change", () => {
  queueMonthFilter.value = "";
  queueDayFilter.value = "";
  pollJobs();
});
queueMonthFilter.addEventListener("change", () => {
  queueDayFilter.value = "";
  pollJobs();
});
queueDayFilter.addEventListener("change", pollJobs);
selectVisibleJobs.addEventListener("change", () => {
  jobs.querySelectorAll("[data-select-job]:not(:disabled)").forEach((input) => {
    input.checked = selectVisibleJobs.checked;
    if (selectVisibleJobs.checked) selectedQueueJobs.add(input.dataset.selectJob);
    else selectedQueueJobs.delete(input.dataset.selectJob);
  });
  updateQueueSelectionControls();
});
deleteSelectedJobs.addEventListener("click", deleteSelectedJobRecords);
restartSelectedJobs.addEventListener("click", restartSelectedFailedJobs);
select("#expand-all-jobs").addEventListener("click", () => {
  jobs.querySelectorAll("[data-queue-date]").forEach((group) => {
    expandedQueueDates.add(group.dataset.queueDate);
  });
  jobs.querySelectorAll("[data-toggle-job]").forEach((button) => {
    expandedQueueJobs.add(button.dataset.toggleJob);
  });
  pollJobs();
});
select("#collapse-all-jobs").addEventListener("click", () => {
  expandedQueueDates.clear();
  jobs.querySelectorAll("[data-toggle-job]").forEach((button) => {
    expandedQueueJobs.delete(button.dataset.toggleJob);
  });
  pollJobs();
});
settingsToggle.addEventListener("click", () => {
  const expanded = settingsToggle.getAttribute("aria-expanded") === "true";
  settingsToggle.setAttribute("aria-expanded", String(!expanded));
  settingsContent.hidden = expanded;
  select(".settings-toggle-label").textContent = expanded ? "Expand" : "Collapse";
  if (!expanded && !isStaticPreview) pollMlxStatus();
  if (expanded) scheduleMlxPolling(null);
});
select("#login").addEventListener("click", async () => {
  try {
    const data = await requestJson("/api/login", { method: "POST" });
    urlStatus.textContent = data.message;
  } catch (error) {
    urlStatus.textContent = error.message;
  }
});
activateAppTab("add");

if (isStaticPreview) {
  select("#preview-warning").hidden = false;
  document.querySelectorAll("form button, #login").forEach((button) => {
    button.disabled = true;
  });
  creatorStatus.textContent = "Start the local app to browse creators and submit jobs.";
  queueSummary.textContent = "Preview only";
  jobs.innerHTML = '<div class="empty">Start the local app to view the processing queue</div>';
  select("#refresh-download-history").disabled = true;
} else {
  loadTrackedRequests();
  renderRequestProgress(latestJobs);
  document.addEventListener("click", noteUserInteraction, { passive: true });
  document.addEventListener("keydown", noteUserInteraction, { passive: true });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopNetworkPolling();
    else refreshNetworkState();
  });
  window.addEventListener("focus", () => refreshNetworkState());
  loadSettings();
  refreshNetworkState(true);
  setInterval(requestProgressWatchdog, 60 * 1000);
}
