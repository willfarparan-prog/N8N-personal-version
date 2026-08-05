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
