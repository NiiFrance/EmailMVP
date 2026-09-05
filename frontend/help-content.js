(() => {
    "use strict";
    window.EmailHelpContent = {
        articles: [
            { id: "first-campaign", title: "Create your first campaign", tags: "start generate upload", paragraphs: [
                "Choose a campaign template, then upload your CSV or Excel file. Review the detected columns before selecting Generate. Generation uses model tokens and may wait in the background.",
                "When drafts are ready, open each lead and touch in Review. Check the recipient, facts, subject and body. Edits must show as saved before you continue. A completed generation job can still contain failed leads; review the row results."
            ] },
            { id: "files", title: "Files and column mapping", tags: "csv xlsx excel upload encoding columns", paragraphs: [
                "Use CSV or XLSX with one contact per row and a header row. Uploads accept up to 50 MB; queued generation, when enabled, supports up to 10,000 leads and a normalized file up to 10 MB per job. Include the recipient email column and template fields. Prefer UTF-8 CSV; Windows-1252 and supported Unicode BOM encodings are also accepted.",
                "Check each detected column using its sample value. Correct missing mappings before generation. A contact's email must be in the recipient column, not in a note or signature. Duplicate recipients and incomplete generated content are blocked during export.",
                "The sample file contains fictional contacts. Downloading it does not upload, generate or export anything. Any generation or export you choose to run uses the normal service limits and confirmations."
            ], sample: true },
            { id: "drafts", title: "Review, save and repair drafts", tags: "edit subject body failed generate", paragraphs: [
                "Select a lead and a touch to edit its subject and body. Wait for the saved indicator. If saving fails, your export is blocked until the edits are saved.",
                "Regenerate failed leads repairs only failed draft rows and retains successful drafts using the original saved template. Older jobs without a template snapshot require a new job. Drafts are locked after an export snapshot is created; changes to a completed batch need a new job.",
                "Always review claims, dates, prices and personalization. The model can make mistakes. Generation success is not a guarantee of marketing accuracy or deliverability."
            ] },
            { id: "connections", title: "Connect Snov.io", tags: "settings api oauth key copilot login", paragraphs: [
                "Open Settings. The API connection is used for lead verification, list export and campaign drafts. Enter credentials directly in the protected Settings fields and select Test and save. Background exports require the saved account connection.",
                "Snov.io Copilot uses a separate OAuth connection for Snov.io tools in chat. Connect it through the consent screen. It does not replace the API connection, and the API connection does not authorize Copilot tools.",
                "Never paste API secrets into a chat, uploaded file or support report. Reconnect an expired connection in Settings. Changing the account while an export is running cannot redirect that export; restore the original account before retrying."
            ] },
            { id: "snovio-draft", title: "Prepare a Snov.io campaign draft", tags: "sender sequence list export sending", paragraphs: [
                "After reviewing saved emails, open Prepare Snov.io draft. A dedicated new prospect list is the default. Choose sender accounts and timing, then Check readiness. Missing Subject_Touch and Body_Touch custom fields must be created in Snov.io before export.",
                "Review the confirmation before preparing the draft. The background operation imports the leads, creates the draft and writes each email step. Export list only imports the list without building a campaign. An existing completed list export can be extended into a draft without importing all leads again.",
                "Lists attached to active campaigns are blocked because adding prospects could begin outreach. This app's draft preparation does not launch a campaign. Review the final campaign inside Snov.io before deliberately launching it there."
            ] },
            { id: "recovery", title: "Resume an export or resolve a failure", tags: "retry partial needs review failed queued status", paragraphs: [
                "Reopen the job from Home to recover saved progress. Queued means accepted and waiting; running means a worker is processing it. Leaving the page does not cancel an accepted background job.",
                "Partial means some work needs attention. Open Rows needing attention. Fix account prerequisites, then use Retry failed work. Successful rows and the original list are retained. Completed is shown only after the required work is confirmed.",
                "Needs review means a previous write has an unknown outcome. Check uncertain result performs reconciliation. If Snov.io reports no prospect, a second explicit confirmation is required for a no-duplicate retry. Missing or multiple list/campaign matches and other-list conflicts require manual review in Snov.io.",
                "Never start another export just because a connection is slow. Check its saved operation first. Generation failures and export failures are separate; use Regenerate failed leads for draft-generation errors."
            ] },
            { id: "limits", title: "Processing times and service limits", tags: "slow waiting quota 100 users rate credits", paragraphs: [
                "Generation and export are background work. The model's capacity is shared across the apps, while Snov.io's limits apply to the connected account. Many users can increase queueing time. More browser refreshes do not make a job faster.",
                "With queued generation enabled, each account can have one generation job outstanding. A full queue rejects new requests without starting work. Existing work stays queued, including when new admissions are paused by an administrator.",
                "Each app currently allocates up to 20 REST requests per minute per Snov.io account. Normal export uses roughly two requests per lead before setup and retries: 1,000 leads can need about 100 minutes of request budget in one app. Other requests and service throttling can extend this.",
                "Use the saved row counts and status to track progress. The maximum workload proven in a test is not a promise of unlimited concurrent throughput. Contact your administrator if progress stops or the account quota is exhausted."
            ] },
            { id: "admin-template", title: "Build and publish a template", tags: "admin brief prompt preview publish archived", admin: true, paragraphs: [
                "In Manage, create a campaign template. Supply its audience, offer, approved facts, call to action, tone, language and emails per lead. Generate a preview, then review the samples. This consumes model tokens; the walkthrough never starts it automatically.",
                "Save unpublished keeps the template out of the sales picker. Publish template makes it available. Advanced prompt is optional. Updating a template affects future jobs; an existing generation job retains its original template snapshot.",
                "Archive removes a template from new selections. It does not delete existing jobs or change Snov.io campaigns. Confirm the template's visibility after publishing or archiving."
            ] }
        ],
        tours: [
            { id: "first-campaign", title: "Create your first campaign", steps: [
                { id: "choose", title: "Choose a template", text: "Open New campaign, choose the template for your task, then continue to Upload.", anchors: ["#template-groups", "#home-new-campaign"], event: "view", matches: state => state.view === "step2" },
                { id: "upload", title: "Upload your lead file", text: "Select your CSV or XLSX and upload it. This step advances only after the server accepts the file.", anchors: ["#drop-zone", "#upload-btn"], event: "uploaded", matches: state => state.uploaded },
                { id: "mapping", title: "Check the columns", text: "Review the sample values and correct every required mapping. Continue the guide when the mappings are complete.", anchors: ["#mapping-card"], manual: true, matches: state => state.mappingReady },
                { id: "generate", title: "Start generation when ready", text: "Select Generate yourself. It uses model tokens. The guide will pause at the queued work; you can resume it from Help.", anchors: ["#generate-btn", "#generating-block"], event: "generation-started", matches: state => state.generating },
                { id: "review", title: "Review your saved drafts", text: "Wait for generation, then inspect each lead and touch. Check facts and recipient details. Finish this guide after drafts load and any edits are saved.", anchors: ["#review-block", "#review-lead-list"], manual: true, matches: state => state.hasDrafts && !state.dirty }
            ] },
            { id: "snovio-draft", title: "Prepare a Snov.io draft", steps: [
                { id: "connection", title: "Check the API connection", text: "Open a reviewed job and continue to Prepare Snov.io draft. Connect and save the Snov.io API account in Settings if needed. OAuth for Copilot is separate.", anchors: ["#snovio-panel", "#settings-api-title", "#step3-continue"], manual: true, matches: state => state.apiConnected && state.view === "step4" },
                { id: "sender", title: "Choose sender and timing", text: "Select sender accounts, a title and delay. A dedicated list is the default. The guide will never choose a sender for you.", anchors: ["#publish-form"], manual: true, matches: state => state.senderReady },
                { id: "readiness", title: "Check readiness", text: "Select Check readiness. Resolve missing fields or blocked rows before proceeding.", anchors: ["#snovio-journey-preview-btn", "#snovio-report"], event: "readiness", matches: state => state.ready },
                { id: "submit", title: "Confirm draft preparation", text: "Select Prepare draft and review the exact confirmation. Nothing is launched. This step advances only when a background operation has been accepted.", anchors: ["#snovio-journey-create-btn"], event: "publication-started", matches: state => state.publicationActive },
                { id: "progress", title: "Follow the saved result", text: "You can pause the guide and leave the page. Reopen the job for progress. Partial or uncertain results need recovery; finish only after the draft is completed.", anchors: ["#publish-progress"], manual: true, matches: state => state.publicationComplete }
            ] },
            { id: "recovery", title: "Resume and recover work", steps: [
                { id: "history", title: "Open the existing job", text: "Use Open in Home history. Do not create another export for a job that is already running.", anchors: [".recent-row", "#nav-home"], event: "job-opened", matches: state => state.hasJob },
                { id: "result", title: "Read the saved status", text: "Continue to Prepare Snov.io draft to inspect its progress and row errors. If the job has no failures, use the recovery article instead; the guide will not manufacture failures.", anchors: ["#publish-progress", "#regenerate-failed-btn", "#step3-continue"], manual: true, matches: state => state.recoveryAvailable },
                { id: "retry", title: "Choose the appropriate recovery", text: "Use Retry failed work or Check uncertain result for export problems, or Regenerate failed leads for generation errors. Existing confirmation and safety rules remain in force.", anchors: ["#publish-retry", "#regenerate-failed-btn"], event: "recovery-started", matches: state => state.recovering },
                { id: "resolved", title: "Verify the outcome", text: "Wait for the saved result. Partial results are not complete. Pause and return later if work is still running.", anchors: ["#publish-progress", "#review-block"], manual: true, matches: state => state.publicationComplete || ((state.recoveryKind === "generation" || (state.publicationKnown && !state.publicationPresent)) && !state.generating && state.hasDrafts && !state.failedDrafts) }
            ] },
            { id: "admin-template", title: "Build a campaign template", admin: true, steps: [
                { id: "brief", title: "Write the brief", text: "Open Manage and New campaign, then supply audience, offer, approved facts and CTA. Open Advanced prompt only if needed.", anchors: ["#ce-brief", "#campaign-new-btn", "#nav-manage"], manual: true, matches: state => state.briefReady },
                { id: "preview", title: "Review generated samples", text: "Select Generate preview yourself, then inspect its wording and facts. The guide advances only after a successful preview.", anchors: ["#ce-preview-btn", "#ce-preview"], event: "template-preview", matches: state => state.templatePreview },
                { id: "save", title: "Save or publish", text: "Save unpublished keeps the template private from the sales picker. Publish template makes it available. Choose the action that matches your intent.", anchors: [".ce-actions"], event: "template-saved", matches: state => state.templateSaved },
                { id: "published", title: "Check the saved state", text: "Confirm the saved template's name and whether it is unpublished or published. Unpublished is not published; future jobs use later edits, existing jobs keep their snapshot.", anchors: ["#campaign-list"], manual: true, matches: state => state.templateSaved }
            ] }
        ]
    };
})();