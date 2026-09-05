(() => {
    "use strict";
    const content = window.EmailHelpContent;
    const panel = document.getElementById("guide-panel");
    if (!content || !panel) return;
    const invitation = document.getElementById("guide-invitation");
    const status = document.getElementById("guide-status");
    const helpStatus = document.getElementById("help-status");
    const preference = document.getElementById("help-opt-out");
    let owner = null;
    let account = null;
    let workflow = {};
    let active = null;
    let spotlight = null;
    let work = Promise.resolve();
    let epoch = 0;
    let lastActivity = 0;
    let lastVisit = 0;
    let channel = null;
    let anchorTimer = null;
    let invitationChecked = false;
    const runId = crypto.randomUUID();
    const requestId = crypto.randomUUID();
    const version = "2026-09-v1";
    document.querySelector(".main-inner").prepend(panel);
    preference.disabled = true;
    try { channel = new BroadcastChannel("emailmvp-onboarding"); } catch (_) { channel = null; }

    function announce(message) { status.textContent = message; helpStatus.textContent = message; }
    function unhighlight() {
        const current = spotlight;
        spotlight = null;
        if (current) current.destroy();
    }
    function stopLocal(message) {
        active = null;
        clearTimeout(anchorTimer);
        unhighlight();
        panel.hidden = true;
        if (message) announce(message);
    }
    async function request(payload) {
        const requestEpoch = epoch;
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 10000);
        try {
            const response = await fetch("/api/me/onboarding", {
                method: payload ? "POST" : "GET", signal: controller.signal,
                headers: payload ? { "Content-Type": "application/json" } : {},
                body: payload ? JSON.stringify({ version, ...payload }) : undefined,
            });
            if (!response.ok) throw new Error(response.status === 409
                ? "Progress changed in another tab. Resume the guide from Help."
                : "Walkthrough progress is unavailable. Your campaign work is unaffected.");
            const result = await response.json();
            if (requestEpoch !== epoch) throw new Error("Your account changed. Open Help again.");
            if (result.state) {
                account = result.state;
                preference.checked = account.optOut;
                preference.disabled = false;
            }
            if (payload) channel?.postMessage({ owner: owner?.oid, revision: account?.revision });
            return result;
        } finally { clearTimeout(timer); }
    }
    function enqueue(action) {
        const actionEpoch = epoch;
        work = work.then(() => actionEpoch === epoch ? action() : undefined).catch(error => {
            if (actionEpoch !== epoch) return;
            stopLocal(error.message);
        });
        return work;
    }
    function stepPayload(action, step, extra = {}) {
        return { action, tourId: active.tour.id, runId, revision: account.revision, step, ...extra };
    }
    function canContinue() {
        const step = active?.tour.steps[active.displayStep];
        return !!step && (active.displayStep < active.step || !!step.matches(workflow));
    }
    function render() {
        if (!active) return;
        const step = active.tour.steps[active.displayStep];
        panel.hidden = false;
        document.getElementById("guide-meta").textContent = `${active.tour.title} / ${active.displayStep + 1} of ${active.tour.steps.length}`;
        document.getElementById("guide-title").textContent = step.title;
        document.getElementById("guide-text").textContent = step.text;
        if (active.tour.id === "admin-template" && step.id === "published" && workflow.templateSaved) {
            document.getElementById("guide-text").textContent = `Saved as ${workflow.templateStatus === "published" ? "published" : "unpublished"}. ${step.text}`;
        }
        const next = document.getElementById("guide-next");
        next.textContent = active.displayStep === active.tour.steps.length - 1 ? "Finish guide" : "Continue guide";
        next.disabled = !canContinue();
        document.getElementById("guide-back").disabled = active.displayStep === 0;
    }
    function anchorFor(step) {
        return step.anchors.map(selector => document.querySelector(selector))
            .find(element => element && element.getClientRects().length && !element.closest("[hidden]"));
    }
    function highlight() {
        if (!active) return;
        unhighlight();
        clearTimeout(anchorTimer);
        const step = active.tour.steps[active.displayStep];
        const element = anchorFor(step);
        if (!element) {
            announce("Open the relevant screen to show this step, or pause and read its Help article.");
            const pending = active;
            anchorTimer = setTimeout(() => {
                if (active === pending && !anchorFor(step)) enqueue(() => pause("Step not visible. Progress saved; resume from Help."));
            }, 5000);
            return;
        }
        if (!window.driver?.js?.driver) {
            announce("Step highlighting is unavailable. Follow the guide text or read Help.");
            return;
        }
        if (document.getElementById("settings-drawer")?.hidden === false) {
            announce("Close Settings before highlighting this step.");
            return;
        }
        spotlight = window.driver.js.driver({
            animate: !matchMedia("(prefers-reduced-motion: reduce)").matches,
            smoothScroll: false, allowKeyboardControl: false, overlayOpacity: 0.3,
            popoverClass: "guide-popover", showButtons: ["next", "close"], nextBtnText: "Back to task",
            onNextClick: () => { unhighlight(); element.focus({ preventScroll: true }); },
            onCloseClick: () => enqueue(() => pause()),
            onDestroyed: () => { if (spotlight) { spotlight = null; enqueue(() => pause()); } },
        });
        spotlight.highlight({ element, popover: { title: step.title, description: step.text, showButtons: ["next", "close"] } });
    }
    async function pause(message = "Guide paused. Resume it from Help.") {
        if (!active) return;
        const payload = stepPayload("pause", active.step);
        stopLocal(message);
        await request(payload);
    }
    async function advance() {
        if (!active || !canContinue()) return;
        unhighlight();
        if (active.displayStep < active.step) {
            active.displayStep += 1;
            render();
            return;
        }
        if (active.step === active.tour.steps.length - 1) {
            await request(stepPayload("complete", active.step));
            stopLocal("Walkthrough completed. You can replay it from Help.");
            return;
        }
        const waiting = ["generation-started", "publication-started", "recovery-started"].includes(active.tour.steps[active.step].event);
        const target = active;
        await request(stepPayload("step", active.step + 1));
        if (active !== target) return;
        active.step += 1;
        active.displayStep = active.step;
        announce("");
        render();
        if (waiting) await pause("Background work accepted. Guide paused; resume it from Help when results are ready.");
    }
    async function start(tourId, restart = false) {
        const tour = content.tours.find(item => item.id === tourId && (!item.admin || owner?.role === "admin"));
        if (!tour || !owner) return;
        if (active) await pause();
        const result = await request();
        if (!result.enabled) { announce("Walkthroughs are currently disabled. Help is still available."); return; }
        const completed = account.tours[tourId]?.completed;
        document.getElementById("copilot-close")?.click();
        await request({ action: "start", tourId, runId, revision: account.revision, restart: restart || !!completed });
        active = { tour, step: account.tours[tourId].step, displayStep: account.tours[tourId].step, jobId: workflow.jobId };
        lastActivity = Date.now();
        announce("");
        render();
        panel.scrollIntoView({ block: "start", behavior: "instant" });
        document.getElementById("guide-title").focus({ preventScroll: true });
        highlight();
    }
    async function initialize() {
        if (invitationChecked) return;
        const result = await request();
        if (!result.enabled || !result.autoInvites || document.hidden || !window.driver?.js?.driver) return;
        const claim = await request({ action: "invite", requestId });
        invitationChecked = true;
        invitation.hidden = !claim.granted;
    }
    document.addEventListener("app:guide-state", event => {
        workflow = event.detail || {};
        const nextOwner = workflow.user;
        if (!nextOwner) return;
        if (owner?.oid !== nextOwner.oid || owner?.role !== nextOwner.role) {
            epoch += 1;
            owner = nextOwner;
            account = null;
            invitationChecked = false;
            preference.disabled = true;
            invitation.hidden = true;
            stopLocal();
            enqueue(initialize);
            return;
        }
        if (!active) return;
        if (active.jobId && active.jobId !== workflow.jobId && active.tour.id !== "admin-template") {
            enqueue(() => pause("The job changed. Resume the guide for this job from Help."));
            return;
        }
        if (!active.jobId && workflow.jobId) active.jobId = workflow.jobId;
        render();
        const expected = active.tour.steps[active.step].event;
        if (expected && expected === workflow.event && active.displayStep === active.step && canContinue()) {
            const target = active, targetStep = active.step;
            enqueue(() => active === target && active.step === targetStep ? advance() : undefined);
        }
    });
    document.addEventListener("help:start-tour", event => enqueue(() => start(event.detail.tourId)));
    document.getElementById("guide-next").addEventListener("click", () => enqueue(advance));
    document.getElementById("guide-highlight").addEventListener("click", highlight);
    document.getElementById("guide-pause").addEventListener("click", () => enqueue(() => pause()));
    document.getElementById("guide-restart").addEventListener("click", () => { if (active) { const tourId = active.tour.id; enqueue(() => start(tourId, true)); } });
    document.getElementById("guide-back").addEventListener("click", () => {
        if (active && active.displayStep > 0) { unhighlight(); active.displayStep -= 1; render(); }
    });
    document.getElementById("guide-accept").addEventListener("click", () => { invitation.hidden = true; enqueue(() => start("first-campaign")); });
    document.getElementById("guide-later").addEventListener("click", () => { invitation.hidden = true; });
    async function optOut(value) {
        preference.disabled = true;
        try { await request({ action: "preferences", optOut: value }); }
        finally { preference.disabled = !account; preference.checked = !!account?.optOut; }
    }
    document.getElementById("guide-never").addEventListener("click", () => { invitation.hidden = true; enqueue(() => optOut(true)); });
    preference.addEventListener("change", () => { const value = preference.checked; enqueue(() => optOut(value)); });
    document.addEventListener("keydown", event => {
        if (event.key === "Escape" && active && !document.getElementById("help-dialog").open) enqueue(() => pause());
    });
    document.addEventListener("help:opening", () => { if (active) enqueue(() => pause()); });
    document.addEventListener("app:overlay", () => { if (active) enqueue(() => pause("Guide paused while another panel is open.")); });
    document.addEventListener("visibilitychange", () => {
        if (document.hidden && active) enqueue(() => pause());
        else if (!document.hidden && owner && !invitationChecked) enqueue(initialize);
    });
    document.getElementById("user-logout")?.addEventListener("click", () => { epoch += 1; owner = null; account = null; stopLocal(); invitation.hidden = true; });
    for (const name of ["pointerdown", "keydown"]) document.addEventListener(name, () => { lastActivity = Date.now(); }, { passive: true });
    setInterval(() => {
        if (!account || document.hidden || Date.now() - lastActivity > 60000) return;
        enqueue(async () => {
            if (active) await request(stepPayload("step", active.step));
            if (account.visitUntil * 1000 > Date.now() && Date.now() - lastVisit > 60000) {
                lastVisit = Date.now();
                await request({ action: "visit" });
            }
        });
    }, 30000);
    if (channel) channel.onmessage = event => {
        if (event.data?.owner !== owner?.oid) return;
        enqueue(async () => {
            await request();
            if (account.optOut) invitation.hidden = true;
            if (active && account.activeTour && account.activeTour !== active.tour.id) stopLocal("Another tab resumed a guide. Open Help to continue here later.");
        });
    };
})();