(() => {
    "use strict";
    const content = window.EmailHelpContent;
    const panel = document.getElementById("help-dialog");
    if (!content || !panel) return;
    let user = null;
    let lastFocus = null;
    const search = document.getElementById("help-search");
    const articles = document.getElementById("help-articles");
    const tours = document.getElementById("help-tours");

    function visible(item) { return !item.admin || user?.role === "admin"; }
    function render() {
        const query = search.value.trim().toLowerCase();
        articles.replaceChildren();
        for (const article of content.articles.filter(visible)) {
            if (query && ![article.id, article.title, article.tags, ...article.paragraphs].join(" ").toLowerCase().includes(query)) continue;
            const details = document.createElement("details");
            details.id = `help-article-${article.id}`;
            const heading = document.createElement("summary");
            heading.textContent = article.title;
            details.appendChild(heading);
            for (const paragraph of article.paragraphs) {
                const text = document.createElement("p");
                text.textContent = paragraph;
                details.appendChild(text);
            }
            if (article.sample) {
                const link = document.createElement("a");
                link.href = "assets/help/sample-leads.csv";
                link.download = "sample-leads.csv";
                link.textContent = "Download fictional sample CSV";
                details.appendChild(link);
            }
            articles.appendChild(details);
        }
        if (!articles.children.length) articles.textContent = "No matching articles.";
    }

    function show(articleId) {
        document.dispatchEvent(new CustomEvent("help:opening"));
        if (articleId) search.value = "";
        if (document.getElementById("settings-drawer")?.hidden === false) {
            document.getElementById("settings-close-btn")?.click();
        }
        lastFocus = document.activeElement;
        render();
        if (!panel.open) panel.showModal();
        const article = articleId && document.getElementById(`help-article-${articleId}`);
        if (article) { article.open = true; article.querySelector("summary").focus(); }
        else search.focus();
    }
    function close() { panel.close(); if (lastFocus?.isConnected) lastFocus.focus(); }
    document.getElementById("help-close").addEventListener("click", close);
    panel.addEventListener("cancel", event => { event.preventDefault(); close(); });
    panel.addEventListener("keydown", event => {
        if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); }
    });
    document.querySelectorAll("[data-open-help]").forEach(button => button.addEventListener("click", () => show()));
    search.addEventListener("input", render);
    document.addEventListener("app:guide-state", event => {
        const next = event.detail?.user;
        if (!next) return;
        if (user?.oid === next.oid && user?.role === next.role) return;
        user = next;
        tours.replaceChildren();
        for (const tour of content.tours.filter(visible)) {
            const row = document.createElement("div");
            row.className = "help-tour-row";
            const label = document.createElement("strong");
            label.textContent = tour.title;
            const button = document.createElement("button");
            button.type = "button";
            button.className = "btn btn-secondary";
            button.textContent = "Start / resume";
            button.addEventListener("click", () => {
                close();
                document.dispatchEvent(new CustomEvent("help:start-tour", { detail: { tourId: tour.id } }));
            });
            row.append(label, button);
            tours.appendChild(row);
        }
        render();
    });
    document.addEventListener("help:open", event => show(event.detail?.articleId));
    const linked = new URLSearchParams(location.search).get("help");
    if (linked && content.articles.some(article => article.id === linked && !article.admin)) show(linked);
    render();
})();