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
    const customPromptSec  = document.getElementById("custom-prompt-section");
    const customPromptArea = document.getElementById("custom-prompt");
    const charCount        = document.getElementById("char-count");

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

    // ── Load Templates ──
    async function loadTemplates() {
        try {
            const resp = await fetch("/api/templates");
            if (!resp.ok) return;
            const data = await resp.json();
            templateData = data.templates || [];

            // Clear existing options and rebuild
            templateSelect.innerHTML = "";
            templateData.forEach((t) => {
                const opt = document.createElement("option");
                opt.value = t.id;
                opt.textContent = t.name;
                templateSelect.appendChild(opt);
            });

            // Add the "Custom Prompt" option
            const customOpt = document.createElement("option");
            customOpt.value = "custom";
            customOpt.textContent = "Custom Prompt";
            templateSelect.appendChild(customOpt);

            // Set initial description
            updateTemplateDescription();
        } catch (err) {
            // Fallback: keep the static cold_email option
        }
    }

    function updateTemplateDescription() {
        const selected = templateSelect.value;
        if (selected === "custom") {
            templateDesc.textContent = "Provide your own system prompt. The model receives all lead data as context.";
            customPromptSec.hidden = false;
        } else {
            const tmpl = templateData.find((t) => t.id === selected);
            templateDesc.textContent = tmpl ? tmpl.description : "";
            customPromptSec.hidden = true;
        }
    }

    templateSelect.addEventListener("change", updateTemplateDescription);

    customPromptArea.addEventListener("input", () => {
        charCount.textContent = customPromptArea.value.length;
    });

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
        if (templateSelect.value === "custom") {
            formData.append("custom_prompt", customPromptArea.value);
        }

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
        clearFile();
        uploadBtn.classList.remove("loading");
        customPromptArea.value = "";
        charCount.textContent = "0";
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
