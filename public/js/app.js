async function apiFetch(path, options = {}) {
    const fetchOptions = {
        ...options,
        credentials: "include",
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {})
        }
    };
    if (fetchOptions.body && typeof fetchOptions.body === "object" && !(fetchOptions.body instanceof FormData)) {
        fetchOptions.body = JSON.stringify(fetchOptions.body);
    }
    const response = await fetch(path, fetchOptions);
    const data = await response.json();
    if (response.status === 401) {
        window.location.href = "/login.html";
        throw new Error("Unauthorized");
    }
    return data;
}

function setTheme(theme) {
    document.documentElement.dataset.theme = theme === "light" ? "light" : "graphite";
    localStorage.setItem("flowforge-theme", document.documentElement.dataset.theme);
}

setTheme(localStorage.getItem("flowforge-theme") || "graphite");

document.addEventListener("DOMContentLoaded", () => {
    const toolbar = document.querySelector(".toolbar");
    if (!toolbar) return;
    const toggle = document.createElement("button");
    toggle.className = "btn btn-ghost btn-sm";
    toggle.type = "button";
    const render = () => {
        const light = document.documentElement.dataset.theme === "light";
        toggle.textContent = light ? "Graphite" : "Light";
        toggle.setAttribute("aria-label", `Switch to ${light ? "graphite" : "light"} theme`);
        toggle.setAttribute("aria-pressed", String(light));
    };
    toggle.addEventListener("click", () => { setTheme(document.documentElement.dataset.theme === "light" ? "graphite" : "light"); render(); });
    render();
    toolbar.append(toggle);
});

async function requireAuth() {
    const session = await apiFetch("/api/session");
    if (!session.authed) {
        window.location.href = "/login.html";
    }
    return session;
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}
