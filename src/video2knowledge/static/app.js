const select = (selector) => document.querySelector(selector);
const results = select("#results");
const jobs = select("#jobs");
const queueStatus = select("#queue-status");
const urlStatus = select("#url-status");
const creatorStatus = select("#creator-status");
const creatorBrowser = select("#creator-browser");
const creatorContent = select("#creator-content");
const settingsStatus = select("#settings-status");
const isStaticPreview = window.location.protocol === "file:";
let searchResults = [];
const expandedFileJobs = new Set();
let creatorState = null;

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
    button.addEventListener("click", () => submitVideo(filtered[Number(button.dataset.videoIndex)]));
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

function videoChoice(video, disabled = false) {
  const checked = creatorState.selectedVideos.has(video.source_id);
  return `
    <label class="creator-video ${disabled ? "disabled" : ""}">
      <input type="checkbox" data-creator-video="${escapeHtml(video.source_id)}"
        ${checked ? "checked" : ""} ${disabled ? "disabled" : ""}>
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
  const selectedCollections = state.selectedCollections.size;
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
        const wholeSelected = state.selectedCollections.has(key);
        return `
          <article class="collection-card ${wholeSelected ? "selected" : ""}">
            <div class="collection-summary">
              <label class="collection-check">
                <input type="checkbox" data-creator-collection="${escapeHtml(key)}"
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
                  : collection.videos.map((video) => videoChoice(video, wholeSelected)).join("")}
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
      <span><strong>${selectedCollections}</strong> whole collections and <strong>${selectedVideos}</strong> individual videos selected</span>
      <button type="button" data-batch-scope="selected"
        ${state.batching || (!selectedCollections && !selectedVideos) ? "disabled" : ""}>
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
    rememberVideos(data.items);
    collection.videos.push(...data.items.filter(
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
    collections: scope === "selected" ? [...state.selectedCollections.values()] : [],
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
  creatorStatus.textContent = "Expanding the selection across all pages…";
  renderCreatorBrowser();
  try {
    const data = await requestJson("/api/jobs/creator-batch", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    creatorStatus.textContent = `${data.submitted} unique videos added to the serial queue.`;
    state.selectedCollections.clear();
    state.selectedVideos.clear();
    await pollJobs();
  } catch (error) {
    creatorStatus.textContent = error.message;
  } finally {
    state.batching = false;
    renderCreatorBrowser();
  }
}

function bindCreatorControls() {
  creatorContent.querySelectorAll("[data-creator-collection]").forEach((input) => {
    input.addEventListener("change", () => {
      const collection = creatorState.collectionIndex.get(input.dataset.creatorCollection);
      if (input.checked) {
        creatorState.selectedCollections.set(input.dataset.creatorCollection, {
          kind: collection.kind,
          id: collection.id,
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
      if (input.checked) {
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
  urlStatus.textContent = "Resolving video…";
  try {
    const data = await requestJson("/api/jobs/url", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: jobPayload({ url: select("#video-url").value }),
    });
    urlStatus.textContent = `Added to queue: ${data.video.title}`;
    select("#video-url").value = "";
    await pollJobs();
  } catch (error) {
    urlStatus.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

async function submitVideo(video) {
  try {
    await requestJson("/api/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: jobPayload({ video }),
    });
    await pollJobs();
  } catch (error) {
    urlStatus.textContent = error.message;
  }
}

async function pollJobs() {
  try {
    const data = await requestJson("/api/jobs");
    jobs.innerHTML = data.length ? data.map((job) => {
      const outputEntries = Object.entries(job.outputs || {});
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
      const canDelete = job.status === "complete" || job.status === "failed";
      return `
      <div class="job">
        <div class="job-head">
          <span>${escapeHtml(job.source.title)}</span>
          <strong>${escapeHtml(job.status)}</strong>
        </div>
        <div class="bar"><i style="width: ${job.progress * 100}%"></i></div>
        <small>${escapeHtml(job.message)}</small>
        ${outputPaths}
        <div class="job-actions">
          <button type="button" class="secondary" data-delete-job="${escapeHtml(job.id)}"
            ${canDelete ? "" : "disabled"}>Delete Record</button>
          <button type="button" class="danger" data-delete-files="${escapeHtml(job.id)}"
            ${canDelete ? "" : "disabled"}>Delete Record &amp; Files</button>
        </div>
      </div>
    `;
    }).join("") : '<div class="empty">No jobs yet</div>';
    jobs.querySelectorAll("[data-delete-job]").forEach((button) => {
      button.addEventListener("click", () => deleteJob(button.dataset.deleteJob, false));
    });
    jobs.querySelectorAll("[data-delete-files]").forEach((button) => {
      button.addEventListener("click", () => deleteJob(button.dataset.deleteFiles, true));
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
  } catch (error) {
    jobs.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
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
    await pollJobs();
  } catch (error) {
    queueStatus.textContent = error.message;
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
  try {
    renderMlxStatus(await requestJson("/api/mlx/status"));
  } catch (error) {
    select("#mlx-message").textContent = error.message;
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
    renderMlxStatus(await requestJson("/api/mlx/start", { method: "POST" }));
  } catch (error) {
    settingsStatus.textContent = error.message;
  }
});

select("#mlx-stop").addEventListener("click", async () => {
  try {
    renderMlxStatus(await requestJson("/api/mlx/stop", { method: "POST" }));
  } catch (error) {
    settingsStatus.textContent = error.message;
  }
});

select("#charging-only").addEventListener("change", renderResults);
select("#tag-filter").addEventListener("input", renderResults);
select("#login").addEventListener("click", async () => {
  try {
    const data = await requestJson("/api/login", { method: "POST" });
    urlStatus.textContent = data.message;
  } catch (error) {
    urlStatus.textContent = error.message;
  }
});

if (isStaticPreview) {
  select("#preview-warning").hidden = false;
  document.querySelectorAll("form button, #login").forEach((button) => {
    button.disabled = true;
  });
  creatorStatus.textContent = "Start the local app to browse creators and submit jobs.";
  jobs.innerHTML = '<div class="empty">Start the local app to view the processing queue</div>';
} else {
  loadSettings();
  pollJobs();
  pollMlxStatus();
  setInterval(pollJobs, 2500);
  setInterval(pollMlxStatus, 2500);
}
