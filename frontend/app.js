/**
 * Reliance Infosystems Email Campaign Generator — SPA
 * Home dashboard + 4-step wizard (Choose → Upload → Review → Sync).
 * All /api and /api/snovio wiring preserved.
 */
(function () {
    "use strict";

    // ── View routing ──
    const views = {
        home: document.getElementById("view-home"),
        step1: document.getElementById("view-step1"),
        step2: document.getElementById("view-step2"),
        step3: document.getElementById("view-step3"),
        step4: document.getElementById("view-step4"),
        error: document.getElementById("view-error"),
        manage: document.getElementById("view-manage"),
    };
    const navHome = document.getElementById("nav-home");
    const navManage = document.getElementById("nav-manage");
    const railWrap = document.getElementById("rail-wrap");
    const sidebarSnovDot = document.getElementById("sidebar-snov-dot");
    const sidebarSnovText = document.getElementById("sidebar-snov-text");

    const STEP_OF = { step1: 1, step2: 2, step3: 3, step4: 4 };

    function showView(name) {
        Object.values(views).forEach((v) => { if (v) v.hidden = true; });
        if (views[name]) views[name].hidden = false;

        const inWizard = name in STEP_OF;
        railWrap.hidden = !inWizard;
        navHome.classList.toggle("active", name === "home");
        if (navManage) navManage.classList.toggle("active", name === "manage");

        const step = STEP_OF[name] || 0;
        document.querySelectorAll("#step-rail .step-row").forEach((row) => {
            const n = parseInt(row.getAttribute("data-step"), 10);
            row.classList.remove("active", "done");
            if (!step) return;
            if (n < step) row.classList.add("done");
            else if (n === step) row.classList.add("active");
        });
        window.scrollTo({ top: 0, behavior: "smooth" });
    }

    // ── State ──
    let selectedFile = null;
    let currentJobId = null;
    let totalLeads = 0;
    let currentUser = null;
    let uploadColumns = [];
    let uploadDetection = null;
    let pollTimer = null;
    let startTime = null;
    let elapsedTimer = null;
    let templateData = [];
    let snovioOptions = null;
    let snovioVerificationResults = [];
    let snovioSessionId = sessionStorage.getItem("snovioSessionId") || null;
    let reviewLeads = [];
    let activeLeadIdx = 0;
    let activeTouchIdx = 0;
    let lastElapsed = "—";

    // ── Element refs ──
    const templateSelect = document.getElementById("template-select");
    const templateGroups = document.getElementById("template-groups");
    const step1Continue = document.getElementById("step1-continue");

    const step2CampaignName = document.getElementById("step2-campaign-name");
    const step2CampaignCount = document.getElementById("step2-campaign-count");
    const dropZone = document.getElementById("drop-zone");
    const dropEmpty = document.getElementById("drop-empty");
    const fileInput = document.getElementById("file-input");
    const fileInfo = document.getElementById("file-info");
    const fileName = document.getElementById("file-name");
    const fileDetail = document.getElementById("file-detail");
    const clearFileBtn = document.getElementById("clear-file");
    const uploadBtn = document.getElementById("upload-btn");
    const uploadError = document.getElementById("upload-error");
    const columnsCard = document.getElementById("columns-card");
    const colsBadge = document.getElementById("cols-badge");
    const colsTable = document.getElementById("cols-table");
    const step2Back = document.getElementById("step2-back");
    const mappingCard = document.getElementById("mapping-card");
    const mapRows = document.getElementById("map-rows");
    const mapHint = document.getElementById("map-hint");
    const generateBtn = document.getElementById("generate-btn");

    const progressFill = document.getElementById("progress-fill");
    const progressStatus = document.getElementById("progress-status");
    const progressPercent = document.getElementById("progress-percent");
    const jobIdDisplay = document.getElementById("job-id-display");
    const totalLeadsDisp = document.getElementById("total-leads-display");
    const startTimeDisp = document.getElementById("start-time-display");
    const elapsedDisp = document.getElementById("elapsed-display");
    const genEmails = document.getElementById("gen-emails");
    const genLeads = document.getElementById("gen-leads");
    const generatingBlock = document.getElementById("generating-block");
    const reviewBlock = document.getElementById("review-block");

    const completedLeads = document.getElementById("completed-leads");
    const reviewEmails = document.getElementById("review-emails");
    const summaryElapsed = document.getElementById("summary-elapsed");
    const summaryLeads = document.getElementById("summary-leads");
    const summaryJobId = document.getElementById("summary-job-id");
    const reviewLeadList = document.getElementById("review-lead-list");
    const reviewTouchTabs = document.getElementById("review-touch-tabs");
    const reviewCurrentName = document.getElementById("review-current-name");
    const reviewCurrentMeta = document.getElementById("review-current-meta");
    const editSubject = document.getElementById("edit-subject");
    const editBody = document.getElementById("edit-body");
    const downloadBtn = document.getElementById("download-btn");
    const step3Back = document.getElementById("step3-back");
    const step3Continue = document.getElementById("step3-continue");

    const newJobBtn = document.getElementById("new-job-btn");
    const step4Back = document.getElementById("step4-back");
    const retryBtn = document.getElementById("retry-btn");
    const errorMessage = document.getElementById("error-message");

    // Home
    const homeNewCampaign = document.getElementById("home-new-campaign");
    const homeSnovPill = document.getElementById("home-snov-pill");
    const homeSnovText = document.getElementById("home-snov-text");
    const statCampaigns = document.getElementById("stat-campaigns");
    const statEmails = document.getElementById("stat-emails");
    const statLeads = document.getElementById("stat-leads");
    const recentList = document.getElementById("recent-list");
    const recentEmpty = document.getElementById("recent-empty");

    // Snov.io
    const snovioPanel = document.getElementById("snovio-panel");
    const snovioStatus = document.getElementById("snovio-status");
    const snovioRefreshBtn = document.getElementById("snovio-refresh-btn");
    const snovioListSelect = document.getElementById("snovio-list-select");
    const snovioCampaignSelect = document.getElementById("snovio-campaign-select");
    const snovioListName = document.getElementById("snovio-list-name");
    const snovioNewListBtn = document.getElementById("snovio-new-list-btn");
    const snovioNewListRow = document.getElementById("snovio-new-list-row");
    const snovioNewListCancel = document.getElementById("snovio-new-list-cancel");
    const snovioDateFrom = document.getElementById("snovio-date-from");
    const snovioDateTo = document.getElementById("snovio-date-to");
    const snovioRequireVerification = document.getElementById("snovio-require-verification");
    const snovioAutoCreateList = document.getElementById("snovio-auto-create-list");
    const snovioConfirmActive = document.getElementById("snovio-confirm-active");
    const snovioVerifyBtn = document.getElementById("snovio-verify-btn");
    const snovioDryRunBtn = document.getElementById("snovio-dry-run-btn");
    const snovioSyncBtn = document.getElementById("snovio-sync-btn");
    const snovioEnrichBtn = document.getElementById("snovio-enrich-btn");
    const snovioAnalyticsBtn = document.getElementById("snovio-analytics-btn");
    const snovioSuppressionListId = document.getElementById("snovio-suppression-list-id");
    const snovioSuppressionItems = document.getElementById("snovio-suppression-items");
    const snovioSuppressBtn = document.getElementById("snovio-suppress-btn");
    const snovioRecipientEmail = document.getElementById("snovio-recipient-email");
    const snovioRecipientStatus = document.getElementById("snovio-recipient-status");
    const snovioRecipientStatusBtn = document.getElementById("snovio-recipient-status-btn");
    const snovioReport = document.getElementById("snovio-report");
    const snovioClientId = document.getElementById("snovio-client-id");
    const snovioClientSecret = document.getElementById("snovio-client-secret");
    const snovioConnectBtn = document.getElementById("snovio-connect-btn");
    const snovioDisconnectBtn = document.getElementById("snovio-disconnect-btn");
    const snovioSenderSelect = document.getElementById("snovio-sender-select");
    const snovioJourneyTitle = document.getElementById("snovio-journey-title");
    const snovioJourneyDelay = document.getElementById("snovio-journey-delay");
    const snovioJourneyOpen = document.getElementById("snovio-journey-open");
    const snovioJourneyClick = document.getElementById("snovio-journey-click");
    const snovioJourneyPreviewBtn = document.getElementById("snovio-journey-preview-btn");
    const snovioJourneyCreateBtn = document.getElementById("snovio-journey-create-btn");

    // ── Helpers ──
    function formatElapsed(ms) {
        const s = Math.floor(ms / 1000), m = Math.floor(s / 60), h = Math.floor(m / 60);
        if (h > 0) return `${h}h ${m % 60}m ${s % 60}s`;
        if (m > 0) return `${m}m ${s % 60}s`;
        return `${s}s`;
    }
    function showUploadError(msg) { uploadError.textContent = msg; uploadError.hidden = false; }
    function hideUploadError() { uploadError.hidden = true; }
    function showError(msg) { errorMessage.textContent = msg; showView("error"); }

    function setSidebarSnov(state, text) {
        sidebarSnovDot.classList.remove("connected", "disconnected");
        if (state) sidebarSnovDot.classList.add(state);
        sidebarSnovText.textContent = text;
        if (homeSnovPill) {
            homeSnovPill.classList.remove("connected", "disconnected");
            if (state) homeSnovPill.classList.add(state);
            homeSnovPill.textContent = state === "connected" ? "Connected" : (state === "disconnected" ? "Not connected" : "—");
        }
    }

    // ── Templates (Step 1) ──
    async function loadTemplates() {
        try {
            const resp = await fetch("/api/templates");
            if (!resp.ok) return;
            const data = await resp.json();
            templateData = data.templates || [];
            renderTemplateCards();
            // keep hidden select in sync for downstream logic
            templateSelect.innerHTML = "";
            templateData.forEach((t) => {
                templateSelect.appendChild(new Option(`${t.name} (${t.num_emails} emails)`, t.id));
            });
            if (templateData.length) selectTemplate(templateData[0].id);
        } catch (err) { /* keep static fallback */ }
    }

    function renderTemplateCards() {
        const groupOrder = [];
        const groups = {};
        templateData.forEach((t) => {
            const g = t.group || "Templates";
            if (!groups[g]) { groups[g] = []; groupOrder.push(g); }
            groups[g].push(t);
        });
        templateGroups.innerHTML = "";
        groupOrder.forEach((groupName) => {
            const wrap = document.createElement("div");
            wrap.className = "tpl-group";
            const h = document.createElement("div");
            h.className = "tpl-group-name";
            h.textContent = groupName;
            const cards = document.createElement("div");
            cards.className = "tpl-cards";
            groups[groupName].forEach((t) => {
                const card = document.createElement("div");
                card.className = "tpl-card";
                card.setAttribute("data-id", t.id);
                card.innerHTML =
                    `<div class="tpl-card-top"><div class="tpl-card-name"></div>` +
                    `<div class="tpl-card-badge"></div></div>` +
                    `<div class="tpl-card-desc"></div>`;
                card.querySelector(".tpl-card-name").textContent = t.name;
                card.querySelector(".tpl-card-badge").textContent =
                    `${t.num_emails} ${t.num_emails === 1 ? "email" : "emails"}`;
                card.querySelector(".tpl-card-desc").textContent = t.description || "";
                card.addEventListener("click", () => selectTemplate(t.id));
                cards.appendChild(card);
            });
            wrap.appendChild(h); wrap.appendChild(cards);
            templateGroups.appendChild(wrap);
        });
    }

    function selectTemplate(id) {
        templateSelect.value = id;
        document.querySelectorAll(".tpl-card").forEach((c) => {
            c.classList.toggle("selected", c.getAttribute("data-id") === id);
        });
        step1Continue.disabled = false;
    }

    function selectedTemplate() {
        return templateData.find((t) => t.id === templateSelect.value) || null;
    }

    function selectedTemplateName() {
        const t = selectedTemplate();
        if (t) return t.name;
        const opt = templateSelect.options[templateSelect.selectedIndex];
        return opt ? opt.textContent.replace(/\s*\([^)]*emails?\)\s*$/i, "").trim() : "Generated Leads";
    }

    // ── File selection + column preview (Step 2) ──
    function selectFile(file) {
        if (!file) return;
        const name = file.name.toLowerCase();
        if (!name.endsWith(".csv") && !name.endsWith(".xlsx")) {
            showUploadError("Please select a .csv or .xlsx file.");
            return;
        }
        selectedFile = file;
        fileName.textContent = file.name;
        fileDetail.textContent = `${(file.size / 1024).toFixed(1)} KB`;
        dropEmpty.hidden = true;
        fileInfo.hidden = false;
        uploadBtn.disabled = false;
        if (typeof resetMappingPanel === "function") resetMappingPanel();
        hideUploadError();
        if (name.endsWith(".csv")) previewColumns(file);
        else columnsCard.hidden = true;
    }

    function clearFile(e) {
        if (e) e.stopPropagation();
        selectedFile = null;
        fileInput.value = "";
        dropEmpty.hidden = false;
        fileInfo.hidden = true;
        columnsCard.hidden = true;
        uploadBtn.disabled = true;
        if (typeof resetMappingPanel === "function") resetMappingPanel();
    }

    // minimal CSV parser (handles quotes, commas, newlines)
    function parseCSV(text) {
        const rows = [];
        let row = [], field = "", inQuotes = false;
        for (let i = 0; i < text.length; i++) {
            const c = text[i];
            if (inQuotes) {
                if (c === '"') {
                    if (text[i + 1] === '"') { field += '"'; i++; }
                    else inQuotes = false;
                } else field += c;
            } else {
                if (c === '"') inQuotes = true;
                else if (c === ",") { row.push(field); field = ""; }
                else if (c === "\n") { row.push(field); rows.push(row); row = []; field = ""; }
                else if (c === "\r") { /* skip */ }
                else field += c;
            }
        }
        if (field.length || row.length) { row.push(field); rows.push(row); }
        return rows.filter((r) => r.length && !(r.length === 1 && r[0] === ""));
    }

    function previewColumns(file) {
        const reader = new FileReader();
        reader.onload = () => {
            try {
                const rows = parseCSV(String(reader.result));
                if (!rows.length) { columnsCard.hidden = true; return; }
                const headers = rows[0];
                const sample = rows.slice(1, 4);
                let html = "<thead><tr>";
                headers.forEach((h) => { html += `<th>${escapeHtml(h)}</th>`; });
                html += "</tr></thead><tbody>";
                sample.forEach((r) => {
                    html += "<tr>";
                    headers.forEach((_, ci) => { html += `<td>${escapeHtml(r[ci] || "")}</td>`; });
                    html += "</tr>";
                });
                html += "</tbody>";
                colsTable.innerHTML = html;
                colsBadge.textContent = `${headers.length} columns detected`;
                fileDetail.textContent = `${(file.size / 1024).toFixed(1)} KB · ${rows.length - 1} rows · ${headers.length} columns`;
                columnsCard.hidden = false;
            } catch (e) { columnsCard.hidden = true; }
        };
        reader.readAsText(file);
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    }

    // ── Upload (phase 1: store + detect columns) ──
    async function doUpload() {
        if (!selectedFile) return;
        uploadBtn.disabled = true;
        hideUploadError();
        const formData = new FormData();
        formData.append("file", selectedFile);
        formData.append("prompt_id", templateSelect.value);
        try {
            const resp = await fetch("/api/upload", { method: "POST", body: formData });
            const data = await resp.json();
            if (!resp.ok) {
                showUploadError(data.error || "Upload failed.");
                uploadBtn.disabled = false;
                return;
            }
            currentJobId = data.jobId;
            totalLeads = data.totalLeads || 0;
            uploadColumns = data.columns || [];
            uploadDetection = data.detection || null;
            if (uploadDetection && uploadDetection.fields && uploadDetection.fields.length) {
                // Show the mapping review step; generation starts on confirm.
                renderMappingPanel();
                mappingCard.hidden = false;
                uploadBtn.hidden = true;
                generateBtn.hidden = false;
                generateBtn.disabled = false;
                mappingCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
            } else {
                // Custom template with no required columns — generate directly.
                doGenerate();
            }
        } catch (err) {
            showUploadError("Network error. Please check your connection.");
            uploadBtn.disabled = false;
        }
    }

    // Build the field → column dropdowns for the mapping review.
    function renderMappingPanel() {
        mapRows.innerHTML = "";
        const cols = uploadColumns;
        const fullIdx = uploadDetection.fullNameIndex;
        const optionLabel = (c) => {
            const header = c.header && c.header.trim() ? c.header : `(column ${c.index + 1})`;
            return c.sample ? `${header} — e.g. ${c.sample}` : header;
        };
        (uploadDetection.fields || []).forEach((f) => {
            const isName = f.field === "first_name" || f.field === "last_name";
            const row = document.createElement("div");
            row.className = "map-row";
            const label = document.createElement("label");
            label.className = "map-label";
            label.textContent = f.label;
            const sel = document.createElement("select");
            sel.className = "map-select";
            sel.dataset.field = f.field;
            // "Not in file" option
            sel.appendChild(new Option("— Not in my file —", ""));
            // Full-name split option for name fields
            if (isName && fullIdx !== null && fullIdx !== undefined) {
                const fnCol = cols[fullIdx];
                const fnLabel = fnCol ? (fnCol.header || `column ${fullIdx + 1}`) : `column ${fullIdx + 1}`;
                sel.appendChild(new Option(`Split from “${fnLabel}”`, `full:${fullIdx}`));
            }
            cols.forEach((c) => sel.appendChild(new Option(optionLabel(c), String(c.index))));
            // Pre-select detection
            if (f.derivedFromFullName && fullIdx !== null && fullIdx !== undefined) {
                sel.value = `full:${fullIdx}`;
            } else if (f.index !== null && f.index !== undefined) {
                sel.value = String(f.index);
            } else {
                sel.value = "";
            }
            if (sel.value === "") row.classList.add("map-row-missing");
            sel.addEventListener("change", () => {
                row.classList.toggle("map-row-missing", sel.value === "");
            });
            row.appendChild(label);
            row.appendChild(sel);
            mapRows.appendChild(row);
        });
        const unresolved = (uploadDetection.unresolved || []).length;
        if (unresolved) {
            mapHint.textContent = "Tip: a column can still be picked even if its header is blank — use the example values to spot the right one (e.g. the email column).";
            mapHint.hidden = false;
        } else {
            mapHint.hidden = true;
        }
    }

    // ── Generate (phase 2: confirm mapping + start generation) ──
    async function doGenerate() {
        if (!currentJobId) return;
        generateBtn.disabled = true;
        uploadBtn.disabled = true;
        hideUploadError();
        const columnMap = {};
        mapRows.querySelectorAll("select.map-select").forEach((sel) => {
            if (sel.value !== "") columnMap[sel.dataset.field] = sel.value.startsWith("full:") ? sel.value : Number(sel.value);
        });
        try {
            const resp = await fetch("/api/generate", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ jobId: currentJobId, promptId: templateSelect.value, columnMap, totalLeads }),
            });
            const data = await resp.json();
            if (!resp.ok) {
                showUploadError(data.error || "Could not start generation.");
                generateBtn.disabled = false;
                return;
            }
            startGenerationView();
        } catch (err) {
            showUploadError("Network error. Please check your connection.");
            generateBtn.disabled = false;
        }
    }

    function startGenerationView() {
        showView("step3");
        saveContext("step3");
        generatingBlock.hidden = false;
        reviewBlock.hidden = true;
        jobIdDisplay.textContent = currentJobId;
        totalLeadsDisp.textContent = totalLeads;
        genLeads.textContent = totalLeads;
        const t = selectedTemplate();
        genEmails.textContent = t ? totalLeads * (t.num_emails || 1) : totalLeads;
        startTime = Date.now();
        startTimeDisp.textContent = new Date(startTime).toLocaleTimeString();
        progressFill.style.width = "0%";
        progressPercent.textContent = "0%";
        progressStatus.textContent = "Starting orchestration…";
        startElapsedTimer();
        startPolling();
    }

    function resetMappingPanel() {
        mappingCard.hidden = true;
        mapRows.innerHTML = "";
        generateBtn.hidden = true;
        uploadBtn.hidden = false;
        uploadDetection = null;
        uploadColumns = [];
    }

    // ── Timers + polling ──
    function startElapsedTimer() {
        elapsedTimer = setInterval(() => {
            if (startTime) elapsedDisp.textContent = formatElapsed(Date.now() - startTime);
        }, 1000);
    }
    function stopElapsedTimer() { if (elapsedTimer) clearInterval(elapsedTimer); elapsedTimer = null; }
    function startPolling() { pollTimer = setInterval(pollStatus, 5000); pollStatus(); }
    function stopPolling() { if (pollTimer) clearInterval(pollTimer); pollTimer = null; }

    async function pollStatus() {
        if (!currentJobId) return;
        try {
            const resp = await fetch(`/api/status/${encodeURIComponent(currentJobId)}`);
            const data = await resp.json();
            if (!resp.ok) { progressStatus.textContent = "Checking status…"; return; }
            const status = data.status;
            if (status === "Running" || status === "Pending") {
                const processed = data.processedLeads || 0;
                const total = data.totalLeads || totalLeads || 1;
                const phase = data.phase || "processing";
                if (phase === "assembling") progressStatus.textContent = "Assembling output CSV…";
                else if (processed > 0) progressStatus.textContent = `Processed ${processed} of ${total} leads…`;
                else progressStatus.textContent = "Preparing leads…";
                const pct = processed > 0 ? Math.min(phase === "assembling" ? 98 : 95, Math.floor((processed / total) * 100)) : 0;
                progressFill.style.width = pct + "%";
                progressPercent.textContent = pct + "%";
            } else if (status === "Completed") {
                stopPolling(); stopElapsedTimer();
                progressFill.style.width = "100%";
                progressPercent.textContent = "100%";
                progressStatus.textContent = "Complete!";
                lastElapsed = startTime ? formatElapsed(Date.now() - startTime) : "—";
                const leadCount = data.totalLeads || totalLeads;
                setTimeout(() => enterReview(leadCount), 600);
            } else if (status === "Failed") {
                stopPolling(); stopElapsedTimer();
                showError(data.error || "The job failed. Please try again.");
            } else {
                progressStatus.textContent = `Status: ${status}`;
            }
        } catch (err) {
            progressStatus.textContent = "Connection issue, retrying…";
        }
    }

    // ── Review (Step 3) ──
    async function enterReview(leadCount) {
        completedLeads.textContent = leadCount;
        summaryLeads.textContent = leadCount;
        summaryElapsed.textContent = lastElapsed;
        summaryJobId.textContent = currentJobId;
        generatingBlock.hidden = true;
        reviewBlock.hidden = false;
        await loadDrafts();
        loadSnovioOptions();
    }

    async function loadDrafts() {
        reviewLeads = [];
        try {
            const resp = await fetch(`/api/download/${encodeURIComponent(currentJobId)}`);
            if (resp.ok) {
                const text = await resp.text();
                reviewLeads = csvToLeads(text);
            }
        } catch (e) { /* ignore */ }
        const totalEmails = reviewLeads.reduce((n, l) => n + l.touches.length, 0);
        reviewEmails.textContent = totalEmails || "—";
        activeLeadIdx = 0; activeTouchIdx = 0;
        renderLeadList();
        renderEditor();
        recordRecent(reviewLeads.length, totalEmails);
    }

    function csvToLeads(text) {
        const rows = parseCSV(text);
        if (rows.length < 2) return [];
        const headers = rows[0];
        const idx = (name) => headers.findIndex((h) => h.trim().toLowerCase() === name);
        const fi = idx("first_name"), li = idx("last_name"), oi = idx("organization"), ei = idx("email");
        const touchCols = [];
        headers.forEach((h, i) => {
            const m = h.match(/^Subject_Touch(\d+)$/i);
            if (m) {
                const bi = headers.findIndex((x) => x.toLowerCase() === `body_touch${m[1]}`.toLowerCase());
                touchCols.push({ n: parseInt(m[1], 10), si: i, bi });
            }
        });
        touchCols.sort((a, b) => a.n - b.n);
        const leads = [];
        for (let r = 1; r < rows.length; r++) {
            const row = rows[r];
            const first = fi >= 0 ? row[fi] : "";
            const last = li >= 0 ? row[li] : "";
            const org = oi >= 0 ? row[oi] : "";
            const email = ei >= 0 ? row[ei] : "";
            const touches = touchCols.map((tc) => ({
                label: `Touch ${tc.n}`,
                subject: row[tc.si] || "",
                body: tc.bi >= 0 ? (row[tc.bi] || "") : "",
            }));
            leads.push({
                first, last, org, email,
                name: [first, last].filter(Boolean).join(" ") || email || `Lead ${r}`,
                touches,
            });
        }
        return leads;
    }

    function renderLeadList() {
        reviewLeadList.innerHTML = "";
        reviewLeads.forEach((lead, i) => {
            const row = document.createElement("div");
            row.className = "review-lead" + (i === activeLeadIdx ? " active" : "");
            const initial = (lead.org || lead.name || "?").trim().charAt(0).toUpperCase();
            row.innerHTML =
                `<div class="avatar">${escapeHtml(initial)}</div>` +
                `<div style="min-width:0;"><div class="rl-company"></div><div class="rl-contact"></div></div>`;
            row.querySelector(".rl-company").textContent = lead.org || lead.name;
            row.querySelector(".rl-contact").textContent = lead.name;
            row.addEventListener("click", () => { activeLeadIdx = i; activeTouchIdx = 0; renderLeadList(); renderEditor(); });
            reviewLeadList.appendChild(row);
        });
    }

    function renderEditor() {
        const lead = reviewLeads[activeLeadIdx];
        if (!lead) {
            reviewCurrentName.textContent = "No drafts";
            reviewCurrentMeta.textContent = "";
            reviewTouchTabs.innerHTML = "";
            editSubject.value = ""; editBody.value = "";
            return;
        }
        reviewCurrentName.textContent = `${lead.name} · ${lead.org || ""}`.replace(/ · $/, "");
        reviewCurrentMeta.textContent = [lead.email].filter(Boolean).join(" · ");
        reviewTouchTabs.innerHTML = "";
        lead.touches.forEach((t, i) => {
            const tab = document.createElement("button");
            tab.type = "button";
            tab.className = "touch-tab" + (i === activeTouchIdx ? " active" : "");
            tab.textContent = t.label;
            tab.addEventListener("click", () => { activeTouchIdx = i; renderEditor(); });
            reviewTouchTabs.appendChild(tab);
        });
        const touch = lead.touches[activeTouchIdx] || { subject: "", body: "" };
        editSubject.value = touch.subject;
        editBody.value = touch.body;
    }

    editSubject.addEventListener("input", () => {
        const lead = reviewLeads[activeLeadIdx];
        if (lead && lead.touches[activeTouchIdx]) lead.touches[activeTouchIdx].subject = editSubject.value;
    });
    editBody.addEventListener("input", () => {
        const lead = reviewLeads[activeLeadIdx];
        if (lead && lead.touches[activeTouchIdx]) lead.touches[activeTouchIdx].body = editBody.value;
    });

    // ── Recent (session history, localStorage) ──
    function recordRecent(leads, emails) {
        try {
            const list = JSON.parse(localStorage.getItem("cw_recent") || "[]");
            list.unshift({
                name: (selectedFile ? selectedFile.name.replace(/\.[^.]+$/, "") : "Campaign"),
                tpl: selectedTemplateName(),
                date: new Date().toLocaleDateString(),
                leads, emails, status: "Drafted",
            });
            localStorage.setItem("cw_recent", JSON.stringify(list.slice(0, 12)));
        } catch (e) { /* ignore */ }
    }

    function renderHome() {
        loadMyJobs();
    }

    async function loadMyJobs() {
        let jobs = null;
        try {
            const resp = await fetch("/api/jobs");
            if (resp.ok) jobs = (await resp.json()).jobs || [];
        } catch (e) { /* fall back below */ }
        if (jobs === null) {
            // Server history unavailable — fall back to local session history.
            let list = [];
            try { list = JSON.parse(localStorage.getItem("cw_recent") || "[]"); } catch (e) { list = []; }
            statCampaigns.textContent = list.length;
            statEmails.textContent = list.reduce((n, r) => n + (r.emails || 0), 0).toLocaleString();
            statLeads.textContent = list.reduce((n, r) => n + (r.leads || 0), 0).toLocaleString();
            recentList.innerHTML = "";
            recentEmpty.hidden = !!list.length;
            return;
        }
        const emailsFor = (j) => {
            const t = (templateData || []).find((x) => x.id === j.templateId);
            return (t ? t.num_emails || 1 : 1) * (j.totalLeads || 0);
        };
        statCampaigns.textContent = jobs.length;
        statLeads.textContent = jobs.reduce((n, j) => n + (j.totalLeads || 0), 0).toLocaleString();
        statEmails.textContent = jobs.filter((j) => j.status === "Completed").reduce((n, j) => n + emailsFor(j), 0).toLocaleString();
        recentList.innerHTML = "";
        if (!jobs.length) { recentEmpty.hidden = false; return; }
        recentEmpty.hidden = true;
        // "Continue where you left off" — saved context pointing at a completed job.
        const ctx = currentUser && currentUser.lastContext;
        if (ctx && ctx.jobId) {
            const match = jobs.find((j) => j.jobId === ctx.jobId && j.status === "Completed");
            if (match) {
                const banner = document.createElement("div");
                banner.className = "resume-banner";
                banner.innerHTML = `<span class="resume-text"></span><button class="btn btn-primary resume-btn" type="button">Continue</button>`;
                banner.querySelector(".resume-text").textContent = `Continue where you left off — ${(match.fileName || "campaign").replace(/\.[^.]+$/, "")} (${match.templateName || "campaign"})`;
                banner.querySelector(".resume-btn").addEventListener("click", () => openJob(match));
                recentList.appendChild(banner);
            }
        }
        jobs.forEach((j) => {
            const row = document.createElement("div");
            row.className = "recent-row";
            const statusColor = j.status === "Completed" ? "#15803D" : (j.status === "Failed" ? "#B91C1C" : "#B45309");
            const statusLabel = j.status === "Completed" ? "Drafted" : (j.status || "—");
            const canOpen = j.status === "Completed";
            row.innerHTML =
                `<div style="min-width:0;"><div class="recent-name"></div><div class="recent-tpl"></div></div>` +
                `<div class="recent-num"><div class="n">${j.totalLeads || 0}</div><div class="u">leads</div></div>` +
                `<div class="recent-num"><div class="n" style="color:${statusColor};"></div></div>` +
                (canOpen ? `<button class="btn btn-secondary recent-open" type="button">Open</button>` : `<div></div>`);
            row.querySelector(".recent-name").textContent = (j.fileName || "Campaign").replace(/\.[^.]+$/, "");
            const when = j.createdAt ? new Date(j.createdAt).toLocaleDateString() : "";
            row.querySelector(".recent-tpl").textContent = [j.templateName, when].filter(Boolean).join(" · ");
            row.querySelectorAll(".recent-num .n")[1].textContent = statusLabel;
            if (canOpen) row.querySelector(".recent-open").addEventListener("click", () => openJob(j));
            recentList.appendChild(row);
        });
    }

    // Resume a completed campaign: load its drafts straight into Review.
    async function openJob(job) {
        currentJobId = job.jobId;
        totalLeads = job.totalLeads || 0;
        if (job.templateId) selectTemplate(job.templateId);
        stopPolling(); stopElapsedTimer();
        railWrap.hidden = false;
        showView("step3");
        generatingBlock.hidden = true;
        reviewBlock.hidden = false;
        completedLeads.textContent = totalLeads;
        summaryLeads.textContent = totalLeads;
        summaryElapsed.textContent = "—";
        summaryJobId.textContent = currentJobId;
        saveContext("step3");
        await loadDrafts();
        loadSnovioOptions();
    }

    // Persist resume context (best-effort, fire-and-forget).
    function saveContext(step) {
        try {
            fetch("/api/me/context", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ step, jobId: currentJobId || "", templateId: templateSelect.value || "" }),
            });
        } catch (e) { /* ignore */ }
    }

    // ── Download ──
    async function doDownload() {
        if (!currentJobId) return;
        downloadBtn.disabled = true;
        const label = downloadBtn.textContent;
        downloadBtn.textContent = "Downloading…";
        try {
            const resp = await fetch(`/api/download/${encodeURIComponent(currentJobId)}`);
            if (!resp.ok) { const d = await resp.json(); showError(d.error || "Download failed."); return; }
            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url; a.download = `emails_${currentJobId.substring(0, 8)}.csv`;
            document.body.appendChild(a); a.click(); document.body.removeChild(a);
            URL.revokeObjectURL(url);
        } catch (err) { showError("Download failed. Please try again."); }
        finally { downloadBtn.disabled = false; downloadBtn.textContent = label; }
    }

    // ── Reset ──
    function resetAll() {
        stopPolling(); stopElapsedTimer();
        currentJobId = null; totalLeads = 0; startTime = null;
        snovioVerificationResults = []; reviewLeads = [];
        snovioReport.hidden = true;
        clearFile();
        showView("step1");
    }

    // ============================================================
    //  Snov.io (logic preserved)
    // ============================================================
    function setSnovioBusy(isBusy) {
        [snovioRefreshBtn, snovioVerifyBtn, snovioDryRunBtn, snovioSyncBtn, snovioEnrichBtn, snovioAnalyticsBtn, snovioSuppressBtn, snovioRecipientStatusBtn, snovioConnectBtn, snovioDisconnectBtn, snovioJourneyPreviewBtn, snovioJourneyCreateBtn].forEach((b) => { if (b) b.disabled = isBusy; });
    }
    function setSnovioConnected(connected) {
        if (snovioDisconnectBtn) snovioDisconnectBtn.hidden = !connected;
        if (snovioConnectBtn) snovioConnectBtn.textContent = connected ? "Reconnect" : "Connect account";
    }
    function renderSnovioReport(title, payload) {
        snovioReport.hidden = false;
        snovioReport.innerHTML = "";
        snovioReport.appendChild(buildFriendlyResult(title, payload || {}));
    }

    // Turn any Snov.io API payload into a plain-English result card (no raw JSON).
    function buildFriendlyResult(title, payload) {
        const wrap = document.createElement("div");

        const heading = (tone, text, sub) => {
            const h = document.createElement("div");
            h.className = "sr-head sr-" + tone;
            const dot = document.createElement("span");
            dot.className = "sr-dot";
            dot.textContent = tone === "ok" ? "\u2713" : tone === "warn" ? "!" : tone === "error" ? "\u00d7" : "\u2139";
            const t = document.createElement("div");
            const strong = document.createElement("div");
            strong.className = "sr-title";
            strong.textContent = text;
            t.appendChild(strong);
            if (sub) {
                const s = document.createElement("div");
                s.className = "sr-sub";
                s.textContent = sub;
                t.appendChild(s);
            }
            h.appendChild(dot);
            h.appendChild(t);
            return h;
        };
        const stat = (label, value) => {
            const row = document.createElement("div");
            row.className = "sr-stat";
            const l = document.createElement("span");
            l.className = "sr-stat-l";
            l.textContent = label;
            const v = document.createElement("span");
            v.className = "sr-stat-v";
            v.textContent = value;
            row.appendChild(l);
            row.appendChild(v);
            return row;
        };
        const note = (text) => {
            const p = document.createElement("p");
            p.className = "sr-note";
            p.textContent = text;
            return p;
        };
        const bullets = (items) => {
            const ul = document.createElement("ul");
            ul.className = "sr-list";
            items.forEach((it) => {
                const li = document.createElement("li");
                li.textContent = it;
                ul.appendChild(li);
            });
            return ul;
        };

        // 1) Plain error
        if (payload.error && !payload.customFieldReadiness && payload.numTouches === undefined) {
            wrap.appendChild(heading("error", "Couldn't complete this", payload.error));
            if (payload.action) wrap.appendChild(note(payload.action));
            return wrap;
        }

        // 2) Journey / campaign result (has numTouches or customFieldReadiness)
        if (payload.numTouches !== undefined || payload.customFieldReadiness) {
            const readiness = payload.customFieldReadiness || {};
            if (readiness.missing && readiness.missing.length) {
                wrap.appendChild(heading("warn", "One-time Snov.io setup needed",
                    "To carry each lead's personalised emails into a drip campaign, Snov.io needs these custom fields created once."));
                wrap.appendChild(note("In Snov.io: open Prospects \u2192 Custom fields, and add a field (type: Text) for each name below. Then come back and click \u201cCreate new campaign\u201d again."));
                wrap.appendChild(bullets(readiness.missing));
                return wrap;
            }
            if (payload.error) {
                wrap.appendChild(heading("error", "Couldn't create the campaign", payload.error));
                if (payload.action) wrap.appendChild(note(payload.action));
                return wrap;
            }
            if (payload.dryRun) {
                wrap.appendChild(heading("info", "Campaign preview",
                    `${payload.numTouches} touches over ${payload.delayDays} day(s) between each.`));
                if (payload.sync && payload.sync.summary) wrap.appendChild(renderSyncSummary(payload.sync, stat, note));
                return wrap;
            }
            wrap.appendChild(heading("ok", "Campaign created as a draft",
                "It's waiting in Snov.io for your review — nothing has been sent."));
            if (payload.campaignTitle) wrap.appendChild(stat("Campaign", payload.campaignTitle));
            wrap.appendChild(stat("Touches", String(payload.numTouches)));
            if (payload.sync && payload.sync.summary) {
                const s = payload.sync.summary;
                wrap.appendChild(stat("Leads added", String((s.added || 0) + (s.updated || 0))));
            }
            const failed = (payload.stepContent || []).filter((c) => c.status === "failed").length;
            if (failed) wrap.appendChild(note(`${failed} email step(s) couldn't be filled in automatically — you can edit them in Snov.io.`));
            wrap.appendChild(note("Open Snov.io \u2192 Campaigns to review and launch when ready."));
            return wrap;
        }

        // 3) Prospect sync / dry-run (has summary)
        if (payload.summary) {
            wrap.appendChild(renderSyncSummary(payload, stat, note, true));
            return wrap;
        }

        // 4) Verification
        if (Array.isArray(payload.results) && title.toLowerCase().includes("verif")) {
            const total = payload.results.length;
            const eligible = payload.results.filter((r) => r.eligible).length;
            wrap.appendChild(heading(eligible ? "ok" : "warn", "Email check complete",
                `${eligible} of ${total} look safe to send to.`));
            wrap.appendChild(note("Safe-to-send emails will be included; risky ones are skipped automatically."));
            return wrap;
        }

        // 5) Enrichment estimate
        if (payload.estimate) {
            const e = payload.estimate;
            wrap.appendChild(heading("info", "Enrichment estimate",
                `About ${e.estimatedCredits || 0} Snov.io credit(s) for ${e.leadCount || 0} lead(s).`));
            return wrap;
        }

        // 6) Analytics
        if (payload.total_contacted !== undefined || payload.emails_sent !== undefined) {
            wrap.appendChild(heading("info", "Campaign analytics", ""));
            if (payload.emails_sent !== undefined) wrap.appendChild(stat("Emails sent", String(payload.emails_sent)));
            if (payload.delivered !== undefined) wrap.appendChild(stat("Delivered", String(payload.delivered)));
            if (payload.email_opens !== undefined) wrap.appendChild(stat("Opened", String(payload.email_opens)));
            if (payload.email_replies !== undefined) wrap.appendChild(stat("Replied", String(payload.email_replies)));
            return wrap;
        }

        // 7) Balance / preflight or anything else — show a soft confirmation
        if (payload.balance && payload.balance.data) {
            wrap.appendChild(heading("ok", "Connected to Snov.io",
                `Credit balance: ${payload.balance.data.balance}.`));
            return wrap;
        }

        wrap.appendChild(heading("ok", title || "Done", "Action completed."));
        return wrap;
    }

    function renderSyncSummary(payload, stat, note, withHeading) {
        const frag = document.createDocumentFragment();
        const s = payload.summary || {};
        const added = s.added || 0;
        const updated = s.updated || 0;
        const skipped = s.skipped || 0;
        const blocked = s.blocked || 0;
        const duplicates = s.duplicates || 0;
        const failed = s.failed || 0;
        const synced = added + updated;
        if (withHeading) {
            const h = document.createElement("div");
            const tone = failed ? "warn" : synced ? "ok" : "warn";
            h.className = "sr-head sr-" + tone;
            const dot = document.createElement("span");
            dot.className = "sr-dot";
            dot.textContent = tone === "ok" ? "\u2713" : "!";
            const t = document.createElement("div");
            const strong = document.createElement("div");
            strong.className = "sr-title";
            strong.textContent = payload.dryRun
                ? "Preview — nothing sent yet"
                : synced ? "Leads synced to Snov.io" : "No new leads were synced";
            const sub = document.createElement("div");
            sub.className = "sr-sub";
            sub.textContent = payload.dryRun
                ? `${s.eligible || 0} of ${s.total || 0} lead(s) are ready to sync.`
                : `${synced} lead(s) are now in your Snov.io list.`;
            t.appendChild(strong);
            t.appendChild(sub);
            h.appendChild(dot);
            h.appendChild(t);
            frag.appendChild(h);
        }
        if (payload.listName) frag.appendChild(stat("List", payload.listName));
        if (added) frag.appendChild(stat("Added", String(added)));
        if (updated) frag.appendChild(stat("Updated (already in list \u2014 drafts refreshed)", String(updated)));
        if (duplicates) frag.appendChild(stat("Skipped (already in list)", String(duplicates)));
        if (blocked) frag.appendChild(stat("Skipped (risky/invalid email)", String(blocked)));
        if (failed) frag.appendChild(stat("Failed", String(failed)));
        if (failed) {
            const reasons = [];
            (payload.rows || []).forEach((r) => {
                if (r && r.status === "failed") {
                    const msg = (r.error || "Snov.io rejected this lead.").replace(/^Snov\.io request failed:\s*/i, "").trim();
                    if (msg && !reasons.includes(msg)) reasons.push(msg);
                }
            });
            if (reasons.length) {
                const wrapEl = document.createElement("div");
                wrapEl.className = "sr-note sr-warn";
                const lead = document.createElement("div");
                lead.textContent = reasons.length === 1 ? "Why it failed:" : "Why they failed:";
                const ul = document.createElement("ul");
                ul.className = "sr-list";
                reasons.slice(0, 5).forEach((m) => { const li = document.createElement("li"); li.textContent = m; ul.appendChild(li); });
                wrapEl.appendChild(lead);
                wrapEl.appendChild(ul);
                frag.appendChild(wrapEl);
            }
        }
        if (!synced && !payload.dryRun && blocked) {
            frag.appendChild(note("Tip: if emails were skipped as risky, turn off \u201cOnly sync verified emails\u201d under Advanced, or run Verify first."));
        }
        return frag;
    }
    function renderSnovioOptions(options) {
        const lists = options.lists || [];
        const campaigns = options.campaigns || [];
        snovioListSelect.innerHTML = "";
        if (!lists.length) snovioListSelect.appendChild(new Option("No lists found", ""));
        else lists.filter((i) => !i.isDeleted).forEach((i) => snovioListSelect.appendChild(new Option(`${i.name || "List"} (${i.contacts || 0})`, i.id)));
        snovioCampaignSelect.innerHTML = "";
        snovioCampaignSelect.appendChild(new Option("No campaign", ""));
        campaigns.forEach((i) => snovioCampaignSelect.appendChild(new Option(`${i.campaign || "Campaign"} - ${i.status || "Unknown"}`, i.id)));
        if (snovioSenderSelect) {
            snovioSenderSelect.innerHTML = "";
            const senders = options.senderAccounts || [];
            if (!senders.length) snovioSenderSelect.appendChild(new Option("No sender accounts", ""));
            else senders.forEach((i) => snovioSenderSelect.appendChild(new Option(`${i.email_from || i.sender_name || "Sender"}${i.valid === false ? " (invalid)" : ""}`, i.id)));
        }
        applyCampaignListSelection();
    }
    const SNOVIO_SESSION_HEADER = "X-Snovio-Session";
    function snovioFetch(url, options) {
        const opts = options ? { ...options } : {};
        opts.headers = { ...(opts.headers || {}) };
        if (snovioSessionId) opts.headers[SNOVIO_SESSION_HEADER] = snovioSessionId;
        return fetch(url, opts);
    }
    async function loadSnovioOptions() {
        if (!snovioPanel) return;
        setSnovioBusy(true);
        snovioStatus.textContent = "Checking account...";
        try {
            const [statusResp, optionsResp, preflightResp] = await Promise.all([
                snovioFetch("/api/snovio/status"),
                snovioFetch("/api/snovio/options"),
                currentJobId ? snovioFetch(`/api/snovio/preflight?jobId=${encodeURIComponent(currentJobId)}&operation=full`) : Promise.resolve(null),
            ]);
            const status = await statusResp.json();
            const options = await optionsResp.json();
            const preflight = preflightResp ? await preflightResp.json() : null;
            snovioOptions = options;
            renderSnovioOptions(options);
            setSnovioConnected(!!status.sessionActive);
            if (!status.configured) {
                const msg = status.sessionActive ? "Session error \u2014 reconnect" : "Not connected \u2014 enter your Snov.io API keys above.";
                snovioStatus.textContent = msg;
                if (homeSnovText) homeSnovText.textContent = "Not connected yet — connect during the final step.";
                setSidebarSnov("disconnected", "Snov.io — not connected");
                return;
            }
            const source = status.credentialSource === "session" ? "your session" : (status.credentialSource === "account" ? "your account" : "server config");
            const balance = preflight && preflight.balance && preflight.balance.data ? preflight.balance.data.balance : "ready";
            snovioStatus.textContent = `Ready \u00b7 ${source} \u00b7 balance ${balance}`;
            if (homeSnovText) homeSnovText.textContent = `Connected via ${source}. Balance ${balance}.`;
            setSidebarSnov("connected", "Snov.io — connected");
            if (preflight) renderSnovioReport("Preflight", preflight);
        } catch (err) {
            snovioStatus.textContent = "Unavailable";
            if (homeSnovText) homeSnovText.textContent = "Snov.io status unavailable.";
            setSidebarSnov("disconnected", "Snov.io — unavailable");
        } finally {
            setSnovioBusy(false);
        }
    }
    async function postJson(url, payload) {
        const response = await snovioFetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Snov.io request failed.");
        return data;
    }
    function selectedCampaign() {
        const campaignId = snovioCampaignSelect.value;
        if (!campaignId || !snovioOptions) return null;
        return (snovioOptions.campaigns || []).find((i) => String(i.id) === String(campaignId)) || null;
    }
    function campaignListId(campaign) {
        if (!campaign) return "";
        return String(campaign.list_id || campaign.listId || "").trim();
    }
    function applyCampaignListSelection() {
        const campaign = selectedCampaign();
        const inferredListId = campaignListId(campaign);
        if (!inferredListId) return;
        const existing = Array.from(snovioListSelect.options).find((o) => String(o.value) === inferredListId);
        if (!existing) snovioListSelect.appendChild(new Option(`Campaign list ${inferredListId}`, inferredListId));
        snovioListSelect.value = inferredListId;
    }
    function defaultSnovioListName() {
        const customName = snovioListName.value.trim();
        if (customName) return customName;
        const date = new Date().toISOString().slice(0, 10);
        const fileBase = selectedFile ? selectedFile.name.replace(/\.[^.]+$/, "") : "";
        return ["Reliance", selectedTemplateName(), fileBase, date].filter(Boolean).join(" - ");
    }

    // ── New-list mode: the "+ New list" button swaps the dropdown for a name box ──
    function isNewListMode() {
        return !!snovioNewListRow && !snovioNewListRow.hidden;
    }
    function enterNewListMode() {
        snovioNewListRow.hidden = false;
        snovioListSelect.disabled = true;
        snovioNewListBtn.hidden = true;
        if (!snovioListName.value.trim()) {
            snovioListName.value = defaultSnovioListName();
        }
        snovioListName.focus();
        snovioListName.select();
    }
    function exitNewListMode() {
        snovioNewListRow.hidden = true;
        snovioListSelect.disabled = false;
        snovioNewListBtn.hidden = false;
        snovioListName.value = "";
    }

    // Resolve the list target shared by sync + campaign create. Returns null after
    // rendering an error when input is incomplete.
    function resolveListTarget(reportTitle) {
        const campaign = selectedCampaign();
        const inferredListId = campaignListId(campaign);
        const newListMode = isNewListMode();
        const newName = snovioListName.value.trim();
        if (newListMode && !newName) {
            renderSnovioReport(reportTitle, { error: "Give your new list a name, or press \u00d7 to use an existing list instead." });
            return null;
        }
        const wantsNewList = newListMode && !!newName;
        const autoCreateList = wantsNewList ? true : snovioAutoCreateList.checked;
        const listId = wantsNewList ? "" : (snovioListSelect.value || inferredListId);
        if (!listId && !autoCreateList) {
            renderSnovioReport(reportTitle, { error: "Pick a list, click + New list, or enable automatic list creation under More options." });
            return null;
        }
        return { campaign, listId, autoCreateList };
    }

    async function runSnovioSync(dryRun) {
        if (!currentJobId) return;
        const target = resolveListTarget("Snov.io");
        if (!target) return;
        const { campaign, listId, autoCreateList } = target;
        setSnovioBusy(true);
        try {
            const payload = { dryRun, listId, campaignId: snovioCampaignSelect.value, campaignStatus: campaign ? campaign.status : "", autoCreateList, createListIfMissing: autoCreateList, listName: defaultSnovioListName(), templateId: templateSelect.value, templateName: selectedTemplateName(), sourceFileName: selectedFile ? selectedFile.name : "", confirmActiveCampaign: snovioConfirmActive.checked, requireVerification: snovioRequireVerification.checked, verificationResults: snovioVerificationResults, includeGeneratedCustomFields: true };
            const report = await postJson(`/api/jobs/${encodeURIComponent(currentJobId)}/snovio/sync`, payload);
            if (!dryRun && report.createdList) { exitNewListMode(); await loadSnovioOptions(); if (report.listId) snovioListSelect.value = report.listId; }
            renderSnovioReport(dryRun ? "Dry Run" : "Sync Report", report);
        } catch (err) {
            renderSnovioReport("Snov.io", { error: err.message });
        } finally { setSnovioBusy(false); }
    }
    function selectedSenderIds() {
        if (!snovioSenderSelect) return [];
        return Array.from(snovioSenderSelect.selectedOptions).map((o) => o.value).filter(Boolean);
    }
    async function connectSnovio() {
        const clientId = snovioClientId.value.trim();
        const clientSecret = snovioClientSecret.value.trim();
        if (!clientId || !clientSecret) { renderSnovioReport("Snov.io", { error: "Client ID and Client Secret are required." }); return; }
        setSnovioBusy(true);
        try {
            const response = await fetch("/api/snovio/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ clientId, clientSecret }) });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || "Unable to connect to Snov.io.");
            snovioSessionId = data.sessionId;
            sessionStorage.setItem("snovioSessionId", snovioSessionId);
            snovioClientSecret.value = ""; snovioClientId.value = "";
            setSnovioConnected(true);
            await loadSnovioOptions();
        } catch (err) { renderSnovioReport("Snov.io", { error: err.message }); }
        finally { setSnovioBusy(false); }
    }
    async function disconnectSnovio() {
        setSnovioBusy(true);
        try { await snovioFetch("/api/snovio/session", { method: "DELETE" }); }
        catch (err) { /* ignore */ }
        finally {
            snovioSessionId = null;
            sessionStorage.removeItem("snovioSessionId");
            setSnovioConnected(false);
            setSnovioBusy(false);
            await loadSnovioOptions();
        }
    }
    async function runSnovioJourney(dryRun) {
        if (!currentJobId) return;
        const senderIds = selectedSenderIds();
        const campaignTitle = snovioJourneyTitle.value.trim();
        if (!dryRun && !senderIds.length) { renderSnovioReport("Campaign", { error: "Select at least one sender account to create a campaign." }); return; }
        if (!dryRun && !campaignTitle) {
            renderSnovioReport("Campaign", { error: "Give your campaign a title \u2014 that's how you'll find it in Snov.io." });
            snovioJourneyTitle.focus();
            return;
        }
        const target = resolveListTarget("Campaign");
        if (!target) return;
        const { listId, autoCreateList } = target;
        setSnovioBusy(true);
        try {
            const payload = { dryRun, listId, autoCreateList, createListIfMissing: autoCreateList, listName: defaultSnovioListName(), campaignTitle, senderAccountIds: senderIds, delayDays: Number(snovioJourneyDelay.value) || 0, trackOpens: snovioJourneyOpen.checked, trackClicks: snovioJourneyClick.checked, templateId: templateSelect.value, templateName: selectedTemplateName(), sourceFileName: selectedFile ? selectedFile.name : "", requireVerification: snovioRequireVerification.checked, verificationResults: snovioVerificationResults, includeGeneratedCustomFields: true };
            const response = await snovioFetch(`/api/jobs/${encodeURIComponent(currentJobId)}/snovio/journey`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
            const report = await response.json();
            if (!dryRun && response.ok) { exitNewListMode(); await loadSnovioOptions(); }
            renderSnovioReport(dryRun ? "Campaign Preview" : (response.ok ? "Campaign Created" : "Campaign"), report);
        } catch (err) { renderSnovioReport("Campaign", { error: err.message }); }
        finally { setSnovioBusy(false); }
    }

    // ── Event bindings ──
    // Navigation
    navHome.addEventListener("click", () => { renderHome(); showView("home"); });
    homeNewCampaign.addEventListener("click", () => showView("step1"));
    step1Continue.addEventListener("click", () => {
        const t = selectedTemplate();
        step2CampaignName.textContent = selectedTemplateName();
        step2CampaignCount.textContent = t ? `${t.num_emails} ${t.num_emails === 1 ? "email" : "emails"}` : "";
        showView("step2");
    });
    step2Back.addEventListener("click", () => { resetMappingPanel(); uploadBtn.disabled = !selectedFile; showView("step1"); });
    step3Back.addEventListener("click", () => showView("step2"));
    step3Continue.addEventListener("click", () => { showView("step4"); loadSnovioOptions(); });
    step4Back.addEventListener("click", () => showView("step3"));
    newJobBtn.addEventListener("click", resetAll);
    retryBtn.addEventListener("click", resetAll);

    // Sidebar step rail clicks (allow going back to completed steps)
    document.querySelectorAll("#step-rail .step-row").forEach((row) => {
        row.addEventListener("click", () => {
            const n = parseInt(row.getAttribute("data-step"), 10);
            if (n === 1) showView("step1");
            else if (n === 2 && selectedTemplate()) showView("step2");
            else if (n === 3 && currentJobId && !reviewBlock.hidden) showView("step3");
            else if (n === 4 && currentJobId && !reviewBlock.hidden) { showView("step4"); }
        });
    });

    // Upload interactions
    dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("dragover"); });
    dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
    dropZone.addEventListener("drop", (e) => { e.preventDefault(); dropZone.classList.remove("dragover"); if (e.dataTransfer.files.length) selectFile(e.dataTransfer.files[0]); });
    dropZone.addEventListener("click", (e) => { if (e.target.closest("label") || e.target === fileInput || e.target.closest(".btn-clear")) return; if (!selectedFile) fileInput.click(); });
    fileInput.addEventListener("change", () => { if (fileInput.files.length) selectFile(fileInput.files[0]); });
    clearFileBtn.addEventListener("click", clearFile);
    uploadBtn.addEventListener("click", doUpload);
    generateBtn.addEventListener("click", doGenerate);
    downloadBtn.addEventListener("click", doDownload);

    // Snov.io bindings
    snovioRefreshBtn.addEventListener("click", loadSnovioOptions);
    snovioCampaignSelect.addEventListener("change", applyCampaignListSelection);
    if (snovioNewListBtn) snovioNewListBtn.addEventListener("click", enterNewListMode);
    if (snovioNewListCancel) snovioNewListCancel.addEventListener("click", exitNewListMode);
    if (snovioConnectBtn) snovioConnectBtn.addEventListener("click", connectSnovio);
    if (snovioDisconnectBtn) snovioDisconnectBtn.addEventListener("click", disconnectSnovio);
    if (snovioJourneyPreviewBtn) snovioJourneyPreviewBtn.addEventListener("click", () => runSnovioJourney(true));
    if (snovioJourneyCreateBtn) snovioJourneyCreateBtn.addEventListener("click", () => runSnovioJourney(false));
    snovioVerifyBtn.addEventListener("click", async () => {
        if (!currentJobId) return;
        setSnovioBusy(true);
        try {
            const report = await postJson(`/api/jobs/${encodeURIComponent(currentJobId)}/snovio/verify`, { dryRun: false, poll: true });
            snovioVerificationResults = report.results || [];
            renderSnovioReport("Verification", report);
        } catch (err) { renderSnovioReport("Verification", { error: err.message }); }
        finally { setSnovioBusy(false); }
    });
    snovioDryRunBtn.addEventListener("click", () => runSnovioSync(true));
    snovioSyncBtn.addEventListener("click", () => runSnovioSync(false));
    snovioEnrichBtn.addEventListener("click", async () => {
        if (!currentJobId) return;
        setSnovioBusy(true);
        try { renderSnovioReport("Enrichment", await postJson(`/api/jobs/${encodeURIComponent(currentJobId)}/snovio/enrich`, { dryRun: true })); }
        catch (err) { renderSnovioReport("Enrichment", { error: err.message }); }
        finally { setSnovioBusy(false); }
    });
    snovioAnalyticsBtn.addEventListener("click", async () => {
        if (!snovioCampaignSelect.value) { renderSnovioReport("Analytics", { error: "Select a campaign first." }); return; }
        setSnovioBusy(true);
        try {
            const params = new URLSearchParams({ campaignId: snovioCampaignSelect.value });
            if (snovioDateFrom.value) params.set("dateFrom", snovioDateFrom.value);
            if (snovioDateTo.value) params.set("dateTo", snovioDateTo.value);
            const response = await snovioFetch(`/api/snovio/analytics?${params.toString()}`);
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || "Analytics unavailable.");
            renderSnovioReport("Analytics", data);
        } catch (err) { renderSnovioReport("Analytics", { error: err.message }); }
        finally { setSnovioBusy(false); }
    });
    snovioSuppressBtn.addEventListener("click", async () => {
        const items = snovioSuppressionItems.value.split(",").map((i) => i.trim()).filter(Boolean);
        if (!snovioSuppressionListId.value || !items.length) { renderSnovioReport("Suppression", { error: "List ID and at least one item are required." }); return; }
        setSnovioBusy(true);
        try { renderSnovioReport("Suppression", await postJson("/api/snovio/suppressions", { listId: snovioSuppressionListId.value, items })); }
        catch (err) { renderSnovioReport("Suppression", { error: err.message }); }
        finally { setSnovioBusy(false); }
    });
    snovioRecipientStatusBtn.addEventListener("click", async () => {
        if (!snovioCampaignSelect.value || !snovioRecipientEmail.value) { renderSnovioReport("Recipient", { error: "Campaign and recipient email are required." }); return; }
        setSnovioBusy(true);
        try { renderSnovioReport("Recipient", await postJson("/api/snovio/recipient-status", { campaignId: snovioCampaignSelect.value, email: snovioRecipientEmail.value, status: snovioRecipientStatus.value })); }
        catch (err) { renderSnovioReport("Recipient", { error: err.message }); }
        finally { setSnovioBusy(false); }
    });

    // ── Identity ──
    async function initAuth() {
        try {
            const resp = await fetch("/api/me");
            if (resp.status === 401) {
                window.location.href = "/login.html";
                return;
            }
            if (!resp.ok) return;
            currentUser = await resp.json();
            renderUserChip(currentUser);
            renderHome();
        } catch (err) {
            // Network hiccup — the SWA route rules enforce login at the page level.
        }
    }

    function renderUserChip(me) {
        const chip = document.getElementById("user-chip");
        if (!chip || !me) return;
        const name = me.name || me.email || "Signed in";
        document.getElementById("user-name").textContent = name;
        document.getElementById("user-avatar").textContent = name.trim().charAt(0).toUpperCase() || "?";
        const roleEl = document.getElementById("user-role");
        roleEl.textContent = me.role || "user";
        roleEl.classList.toggle("user-role-admin", me.role === "admin");
        chip.hidden = false;
        if (navManage) navManage.hidden = me.role !== "admin";
    }

    // ── Manage (admin): campaigns + users ──
    let manageCampaigns = [];
    let editingCampaignId = null;

    function openManage() {
        showView("manage");
        switchManageTab("campaigns");
        loadManageCampaigns();
        loadManageUsers();
    }

    function switchManageTab(tab) {
        document.getElementById("manage-campaigns").hidden = tab !== "campaigns";
        document.getElementById("manage-users").hidden = tab !== "users";
        document.getElementById("manage-tab-campaigns").classList.toggle("active", tab === "campaigns");
        document.getElementById("manage-tab-users").classList.toggle("active", tab === "users");
    }

    async function loadManageCampaigns() {
        const listEl = document.getElementById("campaign-list");
        listEl.innerHTML = "<div class='manage-loading'>Loading…</div>";
        try {
            const resp = await fetch("/api/campaigns?full=true");
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.error || "Could not load campaigns.");
            manageCampaigns = data.campaigns || [];
            renderCampaignList();
        } catch (err) {
            listEl.innerHTML = "";
            const msg = document.createElement("div");
            msg.className = "manage-loading";
            msg.textContent = err.message;
            listEl.appendChild(msg);
        }
    }

    function renderCampaignList() {
        const listEl = document.getElementById("campaign-list");
        listEl.innerHTML = "";
        manageCampaigns.forEach((c) => {
            const row = document.createElement("div");
            row.className = "campaign-row" + (c.archived ? " archived" : "");
            row.innerHTML =
                `<div class="cr-main"><div class="cr-name"></div><div class="cr-meta"></div></div>` +
                `<div class="cr-badges"></div>` +
                `<button class="btn btn-secondary cr-edit" type="button">Edit</button>`;
            row.querySelector(".cr-name").textContent = c.name;
            row.querySelector(".cr-meta").textContent = `${c.group} · ${c.numEmails} email${c.numEmails === 1 ? "" : "s"} per lead`;
            const badges = row.querySelector(".cr-badges");
            if (c.builtin) { const b = document.createElement("span"); b.className = "cr-badge"; b.textContent = "built-in"; badges.appendChild(b); }
            if (c.archived) { const b = document.createElement("span"); b.className = "cr-badge cr-badge-archived"; b.textContent = "archived"; badges.appendChild(b); }
            row.querySelector(".cr-edit").addEventListener("click", () => openCampaignEditor(c.id));
            listEl.appendChild(row);
        });
    }

    function openCampaignEditor(id) {
        const editor = document.getElementById("campaign-editor");
        const c = id ? manageCampaigns.find((x) => x.id === id) : null;
        editingCampaignId = c ? c.id : null;
        document.getElementById("ce-title").textContent = c ? `Edit “${c.name}”` : "New campaign";
        document.getElementById("ce-name").value = c ? c.name : "";
        document.getElementById("ce-group").value = c ? c.group : "";
        document.getElementById("ce-num").value = c ? c.numEmails : 4;
        document.getElementById("ce-desc").value = c ? (c.description || "") : "";
        document.getElementById("ce-prompt").value = c ? (c.systemPrompt || "") : "";
        const archiveBtn = document.getElementById("ce-archive");
        archiveBtn.hidden = !c;
        archiveBtn.textContent = c && c.archived ? "Restore" : "Archive";
        document.getElementById("ce-error").hidden = true;
        editor.hidden = false;
        editor.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    function ceError(message) {
        const el = document.getElementById("ce-error");
        el.textContent = message;
        el.hidden = false;
    }

    async function saveCampaign() {
        const payload = {
            name: document.getElementById("ce-name").value.trim(),
            group: document.getElementById("ce-group").value.trim() || "Custom",
            description: document.getElementById("ce-desc").value.trim(),
            numEmails: Number(document.getElementById("ce-num").value) || 0,
            systemPrompt: document.getElementById("ce-prompt").value.trim(),
        };
        const saveBtn = document.getElementById("ce-save");
        saveBtn.disabled = true;
        try {
            const resp = await fetch(editingCampaignId ? `/api/campaigns/${encodeURIComponent(editingCampaignId)}` : "/api/campaigns", {
                method: editingCampaignId ? "PUT" : "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const data = await resp.json();
            if (!resp.ok) { ceError(data.error || "Save failed."); return; }
            document.getElementById("campaign-editor").hidden = true;
            await loadManageCampaigns();
            loadTemplates(); // refresh the Step 1 picker with the change
        } catch (err) {
            ceError("Network error — please try again.");
        } finally {
            saveBtn.disabled = false;
        }
    }

    async function toggleArchiveCampaign() {
        if (!editingCampaignId) return;
        const c = manageCampaigns.find((x) => x.id === editingCampaignId);
        const btn = document.getElementById("ce-archive");
        btn.disabled = true;
        try {
            const resp = c && c.archived
                ? await fetch(`/api/campaigns/${encodeURIComponent(editingCampaignId)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ archived: false }) })
                : await fetch(`/api/campaigns/${encodeURIComponent(editingCampaignId)}`, { method: "DELETE" });
            const data = await resp.json();
            if (!resp.ok) { ceError(data.error || "Update failed."); return; }
            document.getElementById("campaign-editor").hidden = true;
            await loadManageCampaigns();
            loadTemplates();
        } catch (err) {
            ceError("Network error — please try again.");
        } finally {
            btn.disabled = false;
        }
    }

    async function loadManageUsers() {
        const listEl = document.getElementById("user-list");
        listEl.innerHTML = "<div class='manage-loading'>Loading…</div>";
        try {
            const resp = await fetch("/api/users");
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.error || "Could not load users.");
            listEl.innerHTML = "";
            (data.users || []).forEach((u) => {
                const row = document.createElement("div");
                row.className = "user-row";
                row.innerHTML =
                    `<div class="ur-main"><div class="ur-name"></div><div class="ur-email"></div></div>` +
                    `<span class="ur-role"></span>` +
                    `<button class="btn btn-secondary ur-toggle" type="button"></button>`;
                row.querySelector(".ur-name").textContent = u.name || u.email;
                row.querySelector(".ur-email").textContent = u.email;
                const roleEl = row.querySelector(".ur-role");
                roleEl.textContent = u.role;
                roleEl.classList.toggle("ur-role-admin", u.role === "admin");
                const btn = row.querySelector(".ur-toggle");
                const isSelf = currentUser && currentUser.oid === u.oid;
                if (u.bootstrapAdmin || isSelf) {
                    btn.hidden = true;
                } else {
                    btn.textContent = u.role === "admin" ? "Make user" : "Make admin";
                    btn.addEventListener("click", async () => {
                        btn.disabled = true;
                        try {
                            const r = await fetch(`/api/users/${encodeURIComponent(u.oid)}/role`, {
                                method: "PUT",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ role: u.role === "admin" ? "user" : "admin" }),
                            });
                            if (r.ok) loadManageUsers();
                        } finally { btn.disabled = false; }
                    });
                }
                listEl.appendChild(row);
            });
        } catch (err) {
            listEl.innerHTML = "";
            const msg = document.createElement("div");
            msg.className = "manage-loading";
            msg.textContent = err.message;
            listEl.appendChild(msg);
        }
    }

    // ── Init ──
    if (navManage) navManage.addEventListener("click", openManage);
    document.getElementById("manage-tab-campaigns").addEventListener("click", () => switchManageTab("campaigns"));
    document.getElementById("manage-tab-users").addEventListener("click", () => switchManageTab("users"));
    document.getElementById("campaign-new-btn").addEventListener("click", () => openCampaignEditor(null));
    document.getElementById("ce-close").addEventListener("click", () => { document.getElementById("campaign-editor").hidden = true; });
    document.getElementById("ce-save").addEventListener("click", saveCampaign);
    document.getElementById("ce-archive").addEventListener("click", toggleArchiveCampaign);
    initAuth();
    loadTemplates();
    renderHome();
    showView("home");
})();
