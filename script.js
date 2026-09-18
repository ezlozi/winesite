document.querySelectorAll("[data-scroll]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelector(button.dataset.scroll)?.scrollIntoView({ behavior: "smooth" });
  });
});

const form = document.querySelector("form");
const message = document.querySelector(".form-message");
form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!form.querySelector("input").value.trim()) return;
  message.textContent = "Готово — IP сервера уже в пути.";
  form.reset();
});

document.querySelector(".menu-button").addEventListener("click", () => {
  document.querySelector(".nav-links").classList.toggle("is-open");
});

document.querySelector(".copy-ip").addEventListener("click", async (event) => {
  const ip = document.querySelector("#server-ip").textContent;
  try {
    await navigator.clipboard.writeText(ip);
    event.currentTarget.textContent = "✓ Скопировано";
    setTimeout(() => { event.currentTarget.textContent = "▣   Скопировать IP"; }, 1800);
  } catch {
    event.currentTarget.textContent = ip;
  }
});

async function loadServerStatus() {
  const onlineBox = document.querySelector(".online-box");
  const meta = document.querySelector(".server-meta");
  try {
    const response = await fetch("/api/server-status", { cache: "no-store" });
    const status = await response.json();
    if (!response.ok || status.error) throw new Error(status.error || "Статус недоступен");
    onlineBox.querySelector("i").style.background = status.online ? "#11d783" : "#e05c68";
    onlineBox.querySelector("i").style.boxShadow = status.online ? "0 0 7px #11d783" : "0 0 7px #e05c68";
    onlineBox.querySelector("span").innerHTML = `<i></i> ${status.online ? "Сейчас онлайн" : "Сервер офлайн"}`;
    onlineBox.querySelector("strong").innerHTML = `${status.players} <small>/ ${status.max_players || "—"}</small>`;
    meta.querySelector("span:first-child").textContent = `⌁  ${status.version} · пинг ${status.ping ?? "—"}`;
    if (status.motd) meta.title = status.motd;
  } catch {
    onlineBox.querySelector("span").textContent = "Статус недоступен";
  }
}

loadServerStatus();
setInterval(loadServerStatus, 60000);

const authOverlay = document.querySelector(".auth-overlay");
const profileDrawer = document.querySelector(".profile-drawer");
const consent = document.querySelector("#consent");
const discordButton = document.querySelector(".discord-button");
const authTrigger = document.querySelector(".auth-trigger");

function showLayer(layer, visible) {
  layer.classList.toggle("is-visible", visible);
  layer.setAttribute("aria-hidden", String(!visible));
}

function renderProfile(user) {
  const name = user.global_name || user.username;
  document.querySelector("#profile-title").textContent = name;
  document.querySelector(".profile-avatar").innerHTML = user.avatar
    ? `<img src="${user.avatar}" alt="" />`
    : name.charAt(0).toUpperCase();
  document.querySelector(".profile-avatar").classList.toggle("has-image", Boolean(user.avatar));
  document.querySelector(".discord-badge").textContent = "Discord ✓";
  const stats = document.querySelectorAll(".profile-stats strong");
  stats[0].textContent = user.hours_played ?? 0;
  stats[1].textContent = user.builds_count ?? 0;
  stats[2].textContent = user.server_rank || "#—";
  authTrigger.textContent = "Профиль";
}

async function loadSession() {
  try {
    const response = await fetch("/api/session", { credentials: "same-origin" });
    const data = await response.json();
    if (data.authenticated) renderProfile(data.user);
  } catch {
    // The static file preview has no API; the real server handles the session.
  }
}

authTrigger.addEventListener("click", async () => {
  try {
    const response = await fetch("/api/session", { credentials: "same-origin" });
    const data = await response.json();
    if (data.authenticated) {
      renderProfile(data.user);
      showLayer(profileDrawer, true);
      return;
    }
  } catch {
    // Fall through and show the login dialog in the static preview.
  }
  showLayer(authOverlay, true);
});

consent.addEventListener("change", () => { discordButton.disabled = !consent.checked; });
discordButton.addEventListener("click", () => {
  if (!discordButton.disabled) {
    const authUrl = window.location.protocol === "file:"
      ? "http://localhost:8000/auth/discord"
      : "/auth/discord";
    window.location.href = authUrl;
  }
});
document.querySelector(".modal-close").addEventListener("click", () => showLayer(authOverlay, false));
document.querySelector(".profile-close").addEventListener("click", () => showLayer(profileDrawer, false));
document.querySelector(".logout-button").addEventListener("click", async () => {
  await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
  showLayer(profileDrawer, false);
  authTrigger.textContent = "Войти";
});
document.querySelectorAll(".auth-overlay,.profile-drawer").forEach((layer) => {
  layer.addEventListener("click", (event) => {
    if (event.target === layer) showLayer(layer, false);
  });
});

loadSession();
