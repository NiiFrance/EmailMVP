/**
 * Email Campaign Generator — Frontend Logic
 * Handles: CSV upload, progress polling, CSV download.
 */

(function () {
    "use strict";

    // ── DOM References ──
    const uploadSection   = document.getElementById("upload-section");
    const progressSection = document.getElementById("progress-section");
    const downloadSection = document.getElementById("download-section");
    const errorSection    = document.getElementById("error-section");

    const dropZone      = document.getElementById("drop-zone");
    const fileInput     = document.getElementById("file-input");
    const fileInfo      = document.getElementById("file-info");
    const fileName      = document.getElementById("file-name");
    const clearFileBtn  = document.getElementById("clear-file");
    const uploadBtn     = document.getElementById("upload-btn");
    const uploadError   = document.getElementById("upload-error");

    const templateSelect   = document.getElementById("template-select");
    const templateDesc     = document.getElementById("template-description");

    const progressFill    = document.getElementById("progress-fill");
    const progressStatus  = document.getElementById("progress-status");
    const progressPercent = document.getElementById("progress-percent");
    const jobIdDisplay    = document.getElementById("job-id-display");
    const totalLeadsDisp  = document.getElementById("total-leads-display");
    const startTimeDisp   = document.getElementById("start-time-display");
    const elapsedDisp     = document.getElementById("elapsed-display");

    const completedLeads = document.getElementById("completed-leads");
    const summaryLeads   = document.getElementById("summary-leads");
    const summaryElapsed = document.getElementById("summary-elapsed");
    const summaryJobId   = document.getElementById("summary-job-id");
    const downloadBtn    = document.getElementById("download-btn");
    const newJobBtn      = document.getElementById("new-job-btn");

    const snovioPanel = document.getElementById("snovio-panel");
    const snovioStatus = document.getElementById("snovio-status");
    const snovioRefreshBtn = document.getElementById("snovio-refresh-btn");
    const snovioListSelect = document.getElementById("snovio-list-select");
    const snovioCampaignSelect = document.getElementById("snovio-campaign-select");
    const snovioListName = document.getElementById("snovio-list-name");
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

    const errorMessage = document.getElementById("error-message");
    const retryBtn     = document.getElementById("retry-btn");

    // ── State ──
    let selectedFile = null;
    let currentJobId = null;
    let totalLeads   = 0;
    let pollTimer    = null;
    let startTime    = null;
    let elapsedTimer = null;
    let templateData = [];  // cached template list from API
    let snovioOptions = null;
    let snovioVerificationResults = [];

    // ── Load Templates ──
    async function loadTemplates() {
        try {
            const resp = await fetch("/api/templates");
            if (!resp.ok) return;
            const data = await resp.json();
            templateData = data.templates || [];

            // Group templates by their group field, preserving order
            const groupOrder = [];
            const groups = {};
            templateData.forEach((t) => {
                if (!groups[t.group]) {
                    groups[t.group] = [];
                    groupOrder.push(t.group);
                }
                groups[t.group].push(t);
            });

            // Build <optgroup> structure
            templateSelect.innerHTML = "";
            groupOrder.forEach((groupName) => {
                const optgroup = document.createElement("optgroup");
                optgroup.label = groupName;
                groups[groupName].forEach((t) => {
                    const opt = document.createElement("option");
                    opt.value = t.id;
                    opt.textContent = `${t.name} (${t.num_emails} emails)`;
                    optgroup.appendChild(opt);
                });
                templateSelect.appendChild(optgroup);
            });

            // Set initial description
            updateTemplateDescription();
        } catch (err) {
            // Fallback: keep the static cold_email option
        }
    }

    function updateTemplateDescription() {
        const selected = templateSelect.value;
        const tmpl = templateData.find((t) => t.id === selected);
        templateDesc.textContent = tmpl ? tmpl.description : "";

        // Update button text with email count
        if (tmpl) {
            uploadBtn.textContent = `Generate ${tmpl.num_emails} Emails per Lead`;
        }
    }

    templateSelect.addEventListener("change", updateTemplateDescription);

    // Load templates on page load
    loadTemplates();

    // ── Helpers ──
    function showSection(section) {
        [uploadSection, progressSection, downloadSection, errorSection].forEach(
            (s) => { s.hidden = true; }
        );
        section.hidden = false;
    }

    function formatElapsed(ms) {
        const s = Math.floor(ms / 1000);
        const m = Math.floor(s / 60);
        const h = Math.floor(m / 60);
        if (h > 0) return `${h}h ${m % 60}m ${s % 60}s`;
        if (m > 0) return `${m}m ${s % 60}s`;
        return `${s}s`;
    }

    function setSnovioBusy(isBusy) {
        [snovioRefreshBtn, snovioVerifyBtn, snovioDryRunBtn, snovioSyncBtn, snovioEnrichBtn, snovioAnalyticsBtn, snovioSuppressBtn, snovioRecipientStatusBtn].forEach((button) => {
            button.disabled = isBusy;
        });
    }

    function renderSnovioReport(title, payload) {
        snovioReport.hidden = false;
        let summary = payload.summary || payload.estimate || payload.analytics || payload.balance || payload;
        if (payload.summary) {
            summary = {
                ...payload.summary,
                listId: payload.listId || "",
                listSource: payload.listSource || "",
                listName: payload.listName || "",
                plannedListCreation: !!payload.plannedListCreation,
            };
        }
        snovioReport.innerHTML = "";
        const heading = document.createElement("h4");
        heading.textContent = title;
        const pre = document.createElement("pre");
        pre.textContent = JSON.stringify(summary, null, 2);
        snovioReport.appendChild(heading);
        snovioReport.appendChild(pre);
    }

    function renderSnovioOptions(options) {
        const lists = options.lists || [];
        const campaigns = options.campaigns || [];

        snovioListSelect.innerHTML = "";
        if (!lists.length) {
            snovioListSelect.appendChild(new Option("No lists found", ""));
        } else {
            lists.filter((item) => !item.isDeleted).forEach((item) => {
                snovioListSelect.appendChild(new Option(`${item.name || "List"} (${item.contacts || 0})`, item.id));
            });
        }

        snovioCampaignSelect.innerHTML = "";
        snovioCampaignSelect.appendChild(new Option("No campaign", ""));
        campaigns.forEach((item) => {
            snovioCampaignSelect.appendChild(new Option(`${item.campaign || "Campaign"} - ${item.status || "Unknown"}`, item.id));
        });
        applyCampaignListSelection();
    }

    async function loadSnovioOptions() {
        if (!snovioPanel) return;
        setSnovioBusy(true);
        snovioStatus.textContent = "Checking account...";
        try {
            const [statusResp, optionsResp, preflightResp] = await Promise.all([
                fetch("/api/snovio/status"),
                fetch("/api/snovio/options"),
                currentJobId ? fetch(`/api/snovio/preflight?jobId=${encodeURIComponent(currentJobId)}&operation=full`) : Promise.resolve(null),
            ]);
            const status = await statusResp.json();
            const options = await optionsResp.json();
            const preflight = preflightResp ? await preflightResp.json() : null;
            snovioOptions = options;
            renderSnovioOptions(options);
            if (!status.configured) {
                snovioStatus.textContent = "Not configured";
                return;
            }
            const balance = preflight && preflight.balance && preflight.balance.data ? preflight.balance.data.balance : "ready";
            snovioStatus.textContent = `Ready · balance ${balance}`;
            if (preflight) renderSnovioReport("Preflight", preflight);
        } catch (err) {
            snovioStatus.textContent = "Unavailable";
        } finally {
            setSnovioBusy(false);
        }
    }

    async function postJson(url, payload) {
        const response = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Snov.io request failed.");
        return data;
    }

    function selectedCampaign() {
        const campaignId = snovioCampaignSelect.value;
        if (!campaignId || !snovioOptions) return null;
        return (snovioOptions.campaigns || []).find((item) => String(item.id) === String(campaignId)) || null;
    }

    function campaignListId(campaign) {
        if (!campaign) return "";
        return String(campaign.list_id || campaign.listId || "").trim();
    }

    function applyCampaignListSelection() {
        const campaign = selectedCampaign();
        const inferredListId = campaignListId(campaign);
        if (!inferredListId) return;
        const existingOption = Array.from(snovioListSelect.options).find((option) => String(option.value) === inferredListId);
        if (!existingOption) {
            snovioListSelect.appendChild(new Option(`Campaign list ${inferredListId}`, inferredListId));
        }
        snovioListSelect.value = inferredListId;
    }

    function selectedTemplateName() {
        const selected = templateSelect.options[templateSelect.selectedIndex];
        return selected ? selected.textContent.replace(/\s*\([^)]*emails?\)\s*$/i, "").trim() : "Generated Leads";
    }

    function defaultSnovioListName() {
        const customName = snovioListName.value.trim();
        if (customName) return customName;
        const date = new Date().toISOString().slice(0, 10);
        const fileBase = selectedFile ? selectedFile.name.replace(/\.[^.]+$/, "") : "";
        return ["Cloudware", selectedTemplateName(), fileBase, date].filter(Boolean).join(" - ");
    }

    async function runSnovioSync(dryRun) {
        if (!currentJobId) return;
        const campaign = selectedCampaign();
        const inferredListId = campaignListId(campaign);
        const autoCreateList = snovioAutoCreateList.checked;
        if (!snovioListSelect.value && !inferredListId && !autoCreateList) {
            renderSnovioReport("Snov.io", { error: "Select a list, select a campaign with a list, or enable automatic list creation." });
            return;
        }
        setSnovioBusy(true);
        try {
            const payload = {
                dryRun,
                listId: snovioListSelect.value || inferredListId,
                campaignId: snovioCampaignSelect.value,
                campaignStatus: campaign ? campaign.status : "",
                autoCreateList,
                createListIfMissing: autoCreateList,
                listName: defaultSnovioListName(),
                templateId: templateSelect.value,
                templateName: selectedTemplateName(),
                sourceFileName: selectedFile ? selectedFile.name : "",
                confirmActiveCampaign: snovioConfirmActive.checked,
                requireVerification: snovioRequireVerification.checked,
                verificationResults: snovioVerificationResults,
                includeGeneratedCustomFields: true,
            };
            const report = await postJson(`/api/jobs/${encodeURIComponent(currentJobId)}/snovio/sync`, payload);
            if (!dryRun && report.createdList) {
                await loadSnovioOptions();
                if (report.listId) snovioListSelect.value = report.listId;
            }
            renderSnovioReport(dryRun ? "Dry Run" : "Sync Report", report);
        } catch (err) {
            renderSnovioReport("Snov.io", { error: err.message });
        } finally {
            setSnovioBusy(false);
        }
    }

    snovioRefreshBtn.addEventListener("click", loadSnovioOptions);
    snovioCampaignSelect.addEventListener("change", applyCampaignListSelection);
    snovioVerifyBtn.addEventListener("click", async () => {
        if (!currentJobId) return;
        setSnovioBusy(true);
        try {
            const report = await postJson(`/api/jobs/${encodeURIComponent(currentJobId)}/snovio/verify`, {
                dryRun: false,
                poll: true,
            });
            snovioVerificationResults = report.results || [];
            renderSnovioReport("Verification", report);
        } catch (err) {
            renderSnovioReport("Verification", { error: err.message });
        } finally {
            setSnovioBusy(false);
        }
    });
    snovioDryRunBtn.addEventListener("click", () => runSnovioSync(true));
    snovioSyncBtn.addEventListener("click", () => runSnovioSync(false));
    snovioEnrichBtn.addEventListener("click", async () => {
        if (!currentJobId) return;
        setSnovioBusy(true);
        try {
            const report = await postJson(`/api/jobs/${encodeURIComponent(currentJobId)}/snovio/enrich`, { dryRun: true });
            renderSnovioReport("Enrichment", report);
        } catch (err) {
            renderSnovioReport("Enrichment", { error: err.message });
        } finally {
            setSnovioBusy(false);
        }
    });
    snovioAnalyticsBtn.addEventListener("click", async () => {
        if (!snovioCampaignSelect.value) {
            renderSnovioReport("Analytics", { error: "Select a campaign first." });
            return;
        }
        setSnovioBusy(true);
        try {
            const params = new URLSearchParams({ campaignId: snovioCampaignSelect.value });
            if (snovioDateFrom.value) params.set("dateFrom", snovioDateFrom.value);
            if (snovioDateTo.value) params.set("dateTo", snovioDateTo.value);
            const response = await fetch(`/api/snovio/analytics?${params.toString()}`);
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || "Analytics unavailable.");
            renderSnovioReport("Analytics", data);
        } catch (err) {
            renderSnovioReport("Analytics", { error: err.message });
        } finally {
            setSnovioBusy(false);
        }
    });
    snovioSuppressBtn.addEventListener("click", async () => {
        const items = snovioSuppressionItems.value.split(",").map((item) => item.trim()).filter(Boolean);
        if (!snovioSuppressionListId.value || !items.length) {
            renderSnovioReport("Suppression", { error: "List ID and at least one item are required." });
            return;
        }
        setSnovioBusy(true);
        try {
            const report = await postJson("/api/snovio/suppressions", {
                listId: snovioSuppressionListId.value,
                items,
            });
            renderSnovioReport("Suppression", report);
        } catch (err) {
            renderSnovioReport("Suppression", { error: err.message });
        } finally {
            setSnovioBusy(false);
        }
    });
    snovioRecipientStatusBtn.addEventListener("click", async () => {
        if (!snovioCampaignSelect.value || !snovioRecipientEmail.value) {
            renderSnovioReport("Recipient", { error: "Campaign and recipient email are required." });
            return;
        }
        setSnovioBusy(true);
        try {
            const report = await postJson("/api/snovio/recipient-status", {
                campaignId: snovioCampaignSelect.value,
                email: snovioRecipientEmail.value,
                status: snovioRecipientStatus.value,
            });
            renderSnovioReport("Recipient", report);
        } catch (err) {
            renderSnovioReport("Recipient", { error: err.message });
        } finally {
            setSnovioBusy(false);
        }
    });

    // ── File Selection ──
    function selectFile(file) {
        if (!file) return;
        const name = file.name.toLowerCase();
        if (!name.endsWith(".csv") && !name.endsWith(".xlsx")) {
            showUploadError("Please select a .csv or .xlsx file.");
            return;
        }
        selectedFile = file;
        fileName.textContent = `${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
        fileInfo.hidden = false;
        uploadBtn.disabled = false;
        hideUploadError();
    }

    function clearFile() {
        selectedFile = null;
        fileInput.value = "";
        fileInfo.hidden = true;
        uploadBtn.disabled = true;
    }

    function showUploadError(msg) {
        uploadError.textContent = msg;
        uploadError.hidden = false;
    }

    function hideUploadError() {
        uploadError.hidden = true;
    }

    // ── Drag & Drop ──
    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.classList.add("dragover");
    });
    dropZone.addEventListener("dragleave", () => {
        dropZone.classList.remove("dragover");
    });
    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("dragover");
        if (e.dataTransfer.files.length) selectFile(e.dataTransfer.files[0]);
    });
    dropZone.addEventListener("click", (e) => {
        // Don't trigger if click came from the label or file input (they handle it natively)
        if (e.target.closest("label") || e.target === fileInput) return;
        fileInput.click();
    });

    fileInput.addEventListener("change", () => {
        if (fileInput.files.length) selectFile(fileInput.files[0]);
    });

    clearFileBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        clearFile();
    });

    // ── Upload ──
    uploadBtn.addEventListener("click", async () => {
        if (!selectedFile) return;

        uploadBtn.disabled = true;
        uploadBtn.classList.add("loading");
        hideUploadError();

        const formData = new FormData();
        formData.append("file", selectedFile);
        formData.append("prompt_id", templateSelect.value);

        try {
            const resp = await fetch("/api/upload", {
                method: "POST",
                body: formData,
            });

            const data = await resp.json();

            if (!resp.ok) {
                showUploadError(data.error || "Upload failed.");
                uploadBtn.disabled = false;
                uploadBtn.classList.remove("loading");
                return;
            }

            currentJobId = data.jobId;
            totalLeads = data.totalLeads || 0;

            // Switch to progress view
            showSection(progressSection);
            jobIdDisplay.textContent = currentJobId;
            totalLeadsDisp.textContent = totalLeads;
            const templateName = data.templateName || "Cold Email Sequences";
            progressStatus.textContent = `Starting ${templateName}...`;
            startTime = Date.now();
            startTimeDisp.textContent = new Date(startTime).toLocaleTimeString();
            progressFill.style.width = "0%";
            progressPercent.textContent = "0%";
            progressStatus.textContent = "Starting orchestration...";

            startElapsedTimer();
            startPolling();

        } catch (err) {
            showUploadError("Network error. Please check your connection.");
            uploadBtn.disabled = false;
            uploadBtn.classList.remove("loading");
        }
    });

    // ── Elapsed Timer ──
    function startElapsedTimer() {
        elapsedTimer = setInterval(() => {
            if (startTime) {
                elapsedDisp.textContent = formatElapsed(Date.now() - startTime);
            }
        }, 1000);
    }

    function stopElapsedTimer() {
        if (elapsedTimer) clearInterval(elapsedTimer);
        elapsedTimer = null;
    }

    // ── Polling ──
    function startPolling() {
        pollTimer = setInterval(pollStatus, 5000);
        // Also poll immediately
        pollStatus();
    }

    function stopPolling() {
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = null;
    }

    async function pollStatus() {
        if (!currentJobId) return;

        try {
            const resp = await fetch(`/api/status/${encodeURIComponent(currentJobId)}`);
            const data = await resp.json();

            if (!resp.ok) {
                progressStatus.textContent = "Checking status...";
                return;
            }

            const status = data.status;

            if (status === "Running" || status === "Pending") {
                const processed = data.processedLeads || 0;
                const total = data.totalLeads || totalLeads || 1;
                const phase = data.phase || "processing";

                if (phase === "assembling") {
                    progressFill.classList.remove("pulse");
                    progressStatus.textContent = "Assembling output CSV...";
                } else if (processed > 0) {
                    progressFill.classList.remove("pulse");
                    progressStatus.textContent = `Processed ${processed} of ${total} leads...`;
                } else {
                    // No progress yet — show pulse animation
                    progressFill.classList.add("pulse");
                    progressStatus.textContent = "Preparing leads...";
                }

                // Use real progress from orchestrator; cap at 98% during assembly
                const pct = processed > 0
                    ? Math.min(phase === "assembling" ? 98 : 95, Math.floor((processed / total) * 100))
                    : 0;
                progressFill.style.width = pct + "%";
                progressPercent.textContent = pct + "%";
            } else if (status === "Completed") {
                stopPolling();
                stopElapsedTimer();

                progressFill.classList.remove("pulse");
                progressFill.style.width = "100%";
                progressPercent.textContent = "100%";
                progressStatus.textContent = "Complete!";

                // Capture final elapsed time before switching sections
                const finalElapsed = startTime ? formatElapsed(Date.now() - startTime) : "—";

                // Move to download view after a brief pause
                setTimeout(() => {
                    const leadCount = data.totalLeads || totalLeads;
                    completedLeads.textContent = leadCount;
                    summaryLeads.textContent = leadCount;
                    summaryElapsed.textContent = finalElapsed;
                    summaryJobId.textContent = currentJobId;
                    showSection(downloadSection);
                    loadSnovioOptions();
                }, 800);
            } else if (status === "Failed") {
                stopPolling();
                stopElapsedTimer();
                showError(data.error || "The job failed. Please try again.");
            } else {
                progressStatus.textContent = `Status: ${status}`;
            }

        } catch (err) {
            // Network hiccup — keep polling
            progressStatus.textContent = "Connection issue, retrying...";
        }
    }

    // ── Download ──
    downloadBtn.addEventListener("click", async () => {
        if (!currentJobId) return;
        downloadBtn.disabled = true;
        downloadBtn.textContent = "Downloading...";

        try {
            const resp = await fetch(`/api/download/${encodeURIComponent(currentJobId)}`);

            if (!resp.ok) {
                const data = await resp.json();
                showError(data.error || "Download failed.");
                return;
            }

            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `emails_${currentJobId.substring(0, 8)}.csv`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);

        } catch (err) {
            showError("Download failed. Please try again.");
        } finally {
            downloadBtn.disabled = false;
            downloadBtn.textContent = "Download Enriched CSV";
        }
    });

    // ── New Job / Retry ──
    function resetUI() {
        stopPolling();
        stopElapsedTimer();
        currentJobId = null;
        totalLeads = 0;
        startTime = null;
        snovioVerificationResults = [];
        snovioReport.hidden = true;
        clearFile();
        uploadBtn.classList.remove("loading");
        showSection(uploadSection);
    }

    newJobBtn.addEventListener("click", resetUI);
    retryBtn.addEventListener("click", resetUI);

    // ── Error Display ──
    function showError(msg) {
        errorMessage.textContent = msg;
        showSection(errorSection);
    }
})();
