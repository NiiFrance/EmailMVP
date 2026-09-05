const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;

async function mockApp(page, options = {}) {
    const writes = [];
    const errors = [];
    const user = { oid: "synthetic-owner", role: options.admin ? "admin" : "user", name: "Alex Example", email: "alex@example.com" };
    const campaigns = [];
    let publication = options.recovery ? { operationId: "operation", status: "partial", report: { mode: "draft", total: 1, processed: 1, summary: { failed: 1 }, rows: [{ rowIndex: 0, status: "failed", error: "Synthetic failure" }] } } : null;
    let state = { version: "2026-09-v1", revision: 0, invitations: 0, optOut: false, visitUntil: 0, leaseUntil: 0, activeTour: "", tours: {} };
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/api/**", async route => {
        const url = new URL(route.request().url());
        const method = route.request().method();
        const body = method === "GET" ? null : route.request().headers()["content-type"]?.includes("application/json") ? route.request().postDataJSON() : {};
        if (method !== "GET") writes.push({ path: url.pathname, body });
        let result = {};
        if (url.pathname === "/api/me") result = user;
        else if (url.pathname === "/api/me/onboarding") {
            if (options.unavailable) return route.fulfill({ status: 503, json: { error: "unavailable" } });
            let granted = false;
            if (body) {
                state.revision += 1;
                if (body.action === "invite" && state.invitations < 2 && !state.optOut) { state.invitations += 1; granted = true; }
                if (body.action === "preferences") state.optOut = body.optOut;
                if (body.action === "start") { state.activeTour = body.tourId; state.tours[body.tourId] = { step: body.restart ? 0 : (state.tours[body.tourId]?.step || 0), completed: false }; }
                if (["step", "pause", "complete"].includes(body.action)) state.tours[body.tourId].step = body.step;
                if (body.action === "complete") state.tours[body.tourId].completed = true;
            }
            result = { enabled: true, autoInvites: !!options.auto, state, granted };
        } else if (url.pathname === "/api/templates") result = { templates: [{ id: "cold_email", name: "Cold email", num_emails: 4, group: "Outreach", description: "Approved template" }] };
        else if (url.pathname === "/api/upload" && options.generation) result = { jobId: "synthetic-job", totalLeads: 1, columns: [{ index: 0, header: "Email", sample: "alex@example.com" }], detection: { fields: [{ field: "email", label: "Email", index: 0 }], unresolved: [] } };
        else if (url.pathname === "/api/generate" && options.generation) result = { jobId: "synthetic-job", status: "Pending" };
        else if (url.pathname === "/api/me/context") result = { saved: true };
        else if (url.pathname.startsWith("/api/status/") && options.generation) result = { status: "Running", processedLeads: 0, totalLeads: 1 };
        else if (url.pathname === "/api/jobs") result = { jobs: options.existing ? [{ jobId: "synthetic-job", status: options.running ? "generating" : "Completed", totalLeads: 1, templateId: "cold_email", templateName: "Cold email", fileName: "fictional.csv" }] : [] };
        else if (url.pathname === "/api/download/synthetic-job") return route.fulfill({ contentType: "text/csv", body: "Email,First_Name,Subject_Touch1,Body_Touch1,Generation_Status\nalex@example.com,Alex,Hello,Fictional email,completed\n" });
        else if (url.pathname === "/api/snovio/status") result = { configured: !!options.existing, credentialSource: "account" };
        else if (url.pathname === "/api/snovio/options") result = { lists: [], campaigns: [], senderAccounts: options.existing ? [{ id: "sender", email_from: "sender@example.com" }] : [] };
        else if (url.pathname === "/api/jobs/synthetic-job/snovio/sync/latest") {
            if (!publication) return route.fulfill({ status: 404, json: {} });
            result = publication;
        }
        else if (url.pathname === "/api/jobs/synthetic-job/snovio/journey") {
            if (body.dryRun) result = { numTouches: 1, sync: { summary: { eligible: 1, blocked: 0 } } };
            else { publication = { operationId: "operation", status: "completed", report: { mode: "draft", total: 1, processed: 1, summary: { added: 1 }, campaignId: "synthetic-campaign" } }; result = { operationId: "operation", statusUrl: "/api/jobs/synthetic-job/snovio/sync/operation" }; }
        }
        else if (url.pathname === "/api/jobs/synthetic-job/snovio/retry") {
            publication = { ...publication, status: "completed", report: { mode: "draft", total: 1, processed: 1, summary: { added: 1 }, campaignId: "synthetic-campaign" } };
            result = { operationId: "operation", statusUrl: "/api/jobs/synthetic-job/snovio/sync/operation" };
        }
        else if (url.pathname === "/api/jobs/synthetic-job/snovio/sync/operation") result = publication;
        else if (url.pathname === "/api/snovio/mcp/status") result = { connected: false };
        else if (url.pathname === "/api/users") result = { users: [] };
        else if (url.pathname === "/api/campaign-builder/preview") result = { systemPrompt: "Synthetic prompt", sampleEmails: [{ subject: "Sample", body: "Fictional sample" }] };
        else if (url.pathname === "/api/campaigns") {
            if (method === "POST") { campaigns.push({ ...body, id: "synthetic-template" }); result = campaigns.at(-1); }
            else result = { campaigns };
        }
        else if (method !== "GET") return route.fulfill({ status: 500, json: { error: "Unexpected business write" } });
        await route.fulfill({ json: result });
    });
    return { writes, errors, user, state: () => state };
}

for (const width of [320, 390, 768, 1440]) {
    test(`Help is accessible and fits ${width}px`, async ({ page }) => {
        const fixture = await mockApp(page);
        await page.setViewportSize({ width, height: 900 });
        await page.goto("/");
        await expect(page.locator("#user-name")).toHaveText("Alex Example");
        await page.locator("#help-open").click();
        await expect(page.locator("#help-dialog")).toBeVisible();
        await expect(page.locator("#help-tours button")).toHaveCount(3);
        await page.locator("#help-search").fill("OAuth");
        await expect(page.locator("#help-articles details")).toHaveCount(1);
        await page.locator("#help-articles summary").click();
        const report = await new AxeBuilder({ page }).include("#help-dialog").analyze();
        expect(report.violations.filter(item => ["critical", "serious"].includes(item.impact))).toEqual([]);
        expect(await page.locator("#help-dialog").evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
        await page.screenshot({ path: `test-results/help-${width}.png` });
        await page.locator("#help-search").fill("recovery");
        await expect(page.locator("#help-article-recovery")).toBeVisible();
        await page.keyboard.press("Escape");
        await expect(page.locator("#help-open")).toBeFocused();
        expect(fixture.errors).toEqual([]);
        expect(fixture.writes).toEqual([]);
    });
}

test("tour navigation never invokes business actions", async ({ page }) => {
    const fixture = await mockApp(page);
    await page.goto("/");
    await page.locator("#help-open").click();
    await page.locator("#help-tours button").first().click();
    await expect(page.locator(".driver-popover")).toBeVisible();
    await page.locator(".driver-popover-next-btn").click();
    await expect(page.locator(".driver-popover")).toHaveCount(0);
    await expect(page.locator("#guide-panel")).toBeVisible();
    await expect(page.locator("#guide-next")).toBeDisabled();
    await page.locator("#home-new-campaign").click();
    await page.locator(".tpl-card").first().click();
    await page.locator("#step1-continue").click();
    await expect(page.locator("#guide-title")).toHaveText("Upload your lead file");
    await page.locator("#guide-back").click();
    await expect(page.locator("#guide-title")).toHaveText("Choose a template");
    await page.locator("#guide-next").click();
    await page.keyboard.press("Escape");
    await expect(page.locator("#guide-panel")).toBeHidden();
    expect(fixture.writes.filter(item => item.path !== "/api/me/onboarding")).toEqual([]);
    expect(fixture.errors).toEqual([]);
});

test("Help survives state failure and missing library", async ({ page }) => {
    const fixture = await mockApp(page, { unavailable: true });
    await page.route("**/vendor/driverjs/**", route => route.abort());
    await page.goto("/");
    await page.locator("#help-open").click();
    await expect(page.locator("#help-articles details")).toHaveCount(7);
    await expect(page.locator("#help-opt-out")).toBeDisabled();
    await expect(page.locator("#guide-invitation")).toBeHidden();
    await page.locator("#help-close").click();
    await page.locator("#home-new-campaign").click();
    await expect(page.locator("#view-step1")).toBeVisible();
    expect(fixture.errors).toEqual([]);
});

test("invitation dismiss and opt-out do not mutate campaigns", async ({ page }) => {
    const fixture = await mockApp(page, { auto: true });
    await page.goto("/");
    await page.locator("#guide-never").click();
    await expect.poll(() => fixture.state().optOut).toBe(true);
    await page.locator("#help-open").click();
    await expect(page.locator("#help-opt-out")).toBeChecked();
    await page.locator("#help-tours button").first().click();
    await expect(page.locator(".driver-popover")).toBeVisible();
    expect(fixture.state().invitations).toBe(1);
    expect(fixture.writes.every(item => item.path === "/api/me/onboarding")).toBe(true);
});

test("admin sees fourth tour and article", async ({ page }) => {
    await mockApp(page, { admin: true });
    await page.goto("/");
    await page.locator("#help-open").click();
    await expect(page.locator("#help-tours button")).toHaveCount(4);
    await expect(page.locator("#help-article-admin-template")).toBeVisible();
});

test("guide pauses only after explicit generation is accepted", async ({ page }) => {
    const fixture = await mockApp(page, { generation: true });
    await page.goto("/");
    await page.locator("#help-open").click();
    await page.locator("#help-tours button").first().click();
    await page.locator(".driver-popover-next-btn").click();
    await page.locator("#home-new-campaign").click();
    await page.locator(".tpl-card").focus();
    await page.keyboard.press("Enter");
    await page.locator("#step1-continue").click();
    await page.locator("#file-input").setInputFiles({ name: "fictional.csv", mimeType: "text/csv", buffer: Buffer.from("Email\nalex@example.com") });
    await page.locator("#upload-btn").click();
    await expect(page.locator("#guide-title")).toHaveText("Check the columns");
    await page.locator("#guide-next").click();
    await expect(page.locator("#guide-title")).toHaveText("Start generation when ready");
    expect(fixture.writes.filter(item => item.path === "/api/generate")).toHaveLength(0);
    await page.locator("#generate-btn").click();
    await expect(page.locator("#guide-panel")).toBeHidden();
    await expect.poll(() => fixture.state().tours["first-campaign"].step).toBe(4);
    expect(fixture.state().tours["first-campaign"].completed).toBe(false);
    expect(fixture.writes.filter(item => item.path === "/api/generate")).toHaveLength(1);
    expect(fixture.errors).toEqual([]);
});

test("tour overlay supports keyboard, reduced motion and small screens", async ({ page }) => {
    await mockApp(page);
    await page.setViewportSize({ width: 320, height: 640 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await page.locator("#help-open").click();
    await page.locator("#help-tours button").first().click();
    await expect(page.locator(".driver-popover")).toBeVisible();
    const report = await new AxeBuilder({ page }).include(".driver-popover").analyze();
    expect(report.violations.filter(item => ["serious", "critical"].includes(item.impact))).toEqual([]);
    const box = await page.locator(".driver-popover").boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(320);
    await page.screenshot({ path: "test-results/tour-mobile.png" });
    await page.keyboard.press("Escape");
    await expect(page.locator(".driver-popover")).toHaveCount(0);
});

test("missing anchor pauses with saved progress instead of skipping", async ({ page }) => {
    const fixture = await mockApp(page);
    await page.goto("/");
    await page.locator("#help-open").click();
    await page.locator("#help-tours button").nth(1).click();
    await expect(page.locator("#guide-status")).toContainText("Open the relevant screen");
    await expect(page.locator("#guide-panel")).toBeHidden({ timeout: 8000 });
    expect(fixture.state().tours["snovio-draft"].step).toBe(0);
    expect(fixture.writes.every(item => item.path === "/api/me/onboarding")).toBe(true);
});

async function startGuide(page, index) {
    await page.locator("#help-open").click();
    await page.locator("#help-tours button").nth(index).click();
    await page.locator(".driver-popover-next-btn").click();
}

test("Snov draft guide requires readiness and explicit normal confirmation", async ({ page }) => {
    const fixture = await mockApp(page, { existing: true });
    await page.goto("/");
    await page.locator(".recent-open").click();
    await page.locator("#step3-continue").click();
    await expect(page.locator("#snovio-sender-select option")).toHaveCount(1);
    await startGuide(page, 1);
    await page.locator("#guide-next").click();
    await page.locator("#snovio-sender-select").selectOption("sender");
    await page.locator("#snovio-journey-title").fill("Fictional draft");
    await page.locator("#snovio-journey-title").blur();
    await page.locator("#guide-next").click();
    expect(fixture.writes.filter(item => item.path.endsWith("/journey"))).toHaveLength(0);
    await page.locator("#snovio-journey-preview-btn").click();
    await expect(page.locator("#guide-title")).toHaveText("Confirm draft preparation");
    page.once("dialog", dialog => dialog.dismiss());
    await page.locator("#snovio-journey-create-btn").click();
    await expect(page.locator("#guide-panel")).toBeVisible();
    expect(fixture.writes.filter(item => item.path.endsWith("/journey") && !item.body.dryRun)).toHaveLength(0);
    page.once("dialog", dialog => dialog.accept());
    await page.locator("#snovio-journey-create-btn").click();
    await expect(page.locator("#guide-panel")).toBeHidden();
    await expect(page.locator("#publish-stage")).toContainText("completed");
    await startGuide(page, 1);
    await expect(page.locator("#guide-title")).toHaveText("Follow the saved result");
    await page.locator("#guide-next").click();
    await expect.poll(() => fixture.state().tours["snovio-draft"].completed).toBe(true);
    expect(fixture.writes.filter(item => item.path.endsWith("/journey") && !item.body.dryRun)).toHaveLength(1);
    expect(fixture.errors).toEqual([]);
});

test("recovery guide waits for actual recovered publication", async ({ page }) => {
    const fixture = await mockApp(page, { existing: true, recovery: true });
    await page.goto("/");
    await startGuide(page, 2);
    await page.locator(".recent-open").click();
    await expect(page.locator("#guide-title")).toHaveText("Read the saved status");
    await page.locator("#step3-continue").click();
    await expect(page.locator("#publish-stage")).toContainText("partial");
    await page.locator("#guide-next").click();
    expect(fixture.writes.filter(item => item.path.endsWith("/retry"))).toHaveLength(0);
    await page.locator("#publish-retry").click();
    await expect(page.locator("#guide-panel")).toBeHidden();
    await startGuide(page, 2);
    await expect(page.locator("#guide-title")).toHaveText("Verify the outcome");
    await page.locator("#guide-next").click();
    await expect.poll(() => fixture.state().tours.recovery.completed).toBe(true);
    expect(fixture.writes.filter(item => item.path.endsWith("/retry"))).toHaveLength(1);
    expect(fixture.errors).toEqual([]);
});

test("admin guide keeps saved unpublished distinct from published", async ({ page }) => {
    const fixture = await mockApp(page, { admin: true });
    await page.goto("/");
    await page.locator("#nav-manage").click();
    await page.locator("#campaign-new-btn").click();
    await startGuide(page, 3);
    for (const key of ["name", "audience", "offer", "facts", "cta"]) await page.locator(`#ce-${key}`).fill(`Fictional ${key}`);
    await page.locator("#guide-next").click();
    expect(fixture.writes.filter(item => item.path.includes("campaign-builder"))).toHaveLength(0);
    await page.locator("#ce-preview-btn").click();
    await expect(page.locator("#guide-title")).toHaveText("Save or publish");
    await page.locator("#ce-save-draft").click();
    await expect(page.locator("#guide-text")).toContainText("Saved as unpublished");
    await expect(page.locator("#campaign-list")).toContainText("unpublished");
    await page.locator("#guide-next").click();
    await expect.poll(() => fixture.state().tours["admin-template"].completed).toBe(true);
    expect(fixture.writes.filter(item => item.path === "/api/campaigns")).toHaveLength(1);
    expect(fixture.writes.find(item => item.path === "/api/campaigns").body.publicationStatus).toBe("draft");
    expect(fixture.errors).toEqual([]);
});

test("running jobs reopen progress instead of downloading unfinished drafts", async ({ page }) => {
    await mockApp(page, { existing: true, running: true, generation: true });
    const downloads = [];
    page.on("request", request => { if (request.url().includes("/api/download/")) downloads.push(request.url()); });
    await page.goto("/");
    await page.locator(".recent-open").click();
    await expect(page.locator("#generating-block")).toBeVisible();
    await expect(page.locator("#review-block")).toBeHidden();
    expect(downloads).toEqual([]);
});

test("background-opened tab offers once when it becomes visible", async ({ page }) => {
    const fixture = await mockApp(page, { auto: true });
    await page.addInitScript(() => {
        window.testTabHidden = true;
        Object.defineProperty(document, "hidden", { get: () => window.testTabHidden, configurable: true });
    });
    await page.goto("/");
    await expect(page.locator("#help-opt-out")).toBeEnabled();
    expect(fixture.writes.filter(item => item.body?.action === "invite")).toHaveLength(0);
    await page.evaluate(() => { window.testTabHidden = false; document.dispatchEvent(new Event("visibilitychange")); });
    await expect(page.locator("#guide-invitation")).toBeVisible();
    await page.locator("#guide-later").click();
    await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
    await expect(page.locator("#guide-invitation")).toBeHidden();
    expect(fixture.writes.filter(item => item.body?.action === "invite")).toHaveLength(1);
});