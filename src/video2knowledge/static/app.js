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
const deleteSelectedJobs = select("#delete-selected-jobs");
const urlStatus = select("#url-status");
const creatorStatus = select("#creator-status");
const creatorBrowser = select("#creator-browser");
const creatorContent = select("#creator-content");
const settingsStatus = select("#settings-status");
const settingsToggle = select("#settings-toggle");
const settingsContent = select("#settings-content");
const isStaticPreview = window.location.protocol === "file:";
let searchResults = [];
const expandedFileJobs = new Set();
const expandedQueueJobs = new Set();
const selectedQueueJobs = new Set();
let creatorState = null;

function updateQueueSelectionControls() {
  const visible = [...jobs.querySelectorAll("[data-select-job]:not(:disabled)")];
  const selectedVisible = visible.filter((input) => selectedQueueJobs.has(input.dataset.selectJob));
  selectVisibleJobs.disabled = visible.length === 0;
  selectVisibleJobs.checked = visible.length > 0 && selectedVisible.length === visible.length;
  selectVisibleJobs.indeterminate = selectedVisible.length > 0 && selectedVisible.length < visible.length;
  selectedJobsCount.textContent = `${selectedQueueJobs.size} selected`;
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

function jobCreatedDateParts(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  return match ? { year: match[1], month: match[2], day: match[3] } : null;
}

function jobMatchesStatusFilter(job, filter) {
  if (!filter) return true;
  if (filter === "running") {
    return !["complete", "failed", "queued"].includes(job.status);
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
    const data = await requestJson("/api/jobs?limit=5000");
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
    const activeJobs = filteredData.filter(
      (job) => !["complete", "failed"].includes(job.status),
    ).length;
    queueSummary.textContent = data.length
      ? `${filteredData.length}${filteredData.length !== data.length ? ` of ${data.length}` : ""} jobs${activeJobs ? ` · ${activeJobs} active` : ""}`
      : "No jobs";
    jobs.innerHTML = filteredData.length ? filteredData.map((job) => {
      const outputEntries = Object.entries(job.outputs || {});
      const expanded = expandedQueueJobs.has(job.id);
      const author = job.source.author || "Unknown creator";
      const collectionTitle = job.source.collection_title || "No collection data";
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
      const canDelete = job.status === "complete" || job.status === "failed";
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
          <button type="button" class="quick-delete" data-quick-delete-job="${escapeHtml(job.id)}"
            title="Delete history record" aria-label="Delete ${escapeHtml(job.source.title)}"
            ${canDelete ? "" : "disabled"}>×</button>
        </div>
        <div class="bar"><i style="width: ${job.progress * 100}%"></i></div>
        <div class="job-body" ${expanded ? "" : "hidden"}>
          <small>${escapeHtml(job.message)}</small>
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
    }).join("") : '<div class="empty">No jobs match the current filters</div>';
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
    jobs.querySelectorAll("[data-select-job]").forEach((input) => {
      input.addEventListener("change", () => {
        if (input.checked) selectedQueueJobs.add(input.dataset.selectJob);
        else selectedQueueJobs.delete(input.dataset.selectJob);
        updateQueueSelectionControls();
      });
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
  } catch (error) {
    queueSummary.textContent = "Queue unavailable";
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
select("#expand-all-jobs").addEventListener("click", () => {
  jobs.querySelectorAll("[data-toggle-job]").forEach((button) => {
    expandedQueueJobs.add(button.dataset.toggleJob);
  });
  pollJobs();
});
select("#collapse-all-jobs").addEventListener("click", () => {
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
});
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
  queueSummary.textContent = "Preview only";
  jobs.innerHTML = '<div class="empty">Start the local app to view the processing queue</div>';
} else {
  loadSettings();
  pollJobs();
  pollMlxStatus();
  setInterval(pollJobs, 2500);
  setInterval(pollMlxStatus, 2500);
}
