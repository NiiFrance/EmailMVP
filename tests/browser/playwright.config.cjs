const { defineConfig } = require("@playwright/test");
module.exports = defineConfig({
    testDir: ".", testMatch: "*.spec.cjs", timeout: 30000, workers: 2,
    use: { baseURL: "http://127.0.0.1:8796", browserName: "chromium", screenshot: "only-on-failure", trace: "retain-on-failure" },
    webServer: { command: "node serve.cjs", url: "http://127.0.0.1:8796", reuseExistingServer: false },
});