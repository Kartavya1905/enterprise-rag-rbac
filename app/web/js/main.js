/*
 * FILE:         app/web/js/main.js
 * WHAT IT DOES: Starts the web UI and switches between screens:
 *                 LOGIN   email + password, or one-click demo personas (if enabled)
 *                 ASK     the chat (chat.js)
 *                 ADMIN   documents + audit (admin.js) - only for role "admin"
 * WHERE IT FITS: Phase 10 - the entry point loaded by index.html.
 *
 * Flow:  page load -> have a token? -> GET /auth/me -> app screen
 *                                  no -> login screen
 */

import { renderAdmin } from "./admin.js";
import { api, session } from "./api.js";
import { renderChat } from "./chat.js";
import { clear, clearanceChip, el, toast } from "./dom.js";

const app = document.getElementById("app");
const topbar = document.getElementById("topbar");

// =============================================================================
// 1. START UP
// =============================================================================
async function boot() {
  if (!session.token) return showLogin();
  try {
    const user = await api("/auth/me"); // who am I - as the DATABASE knows me
    showApp(user);
  } catch {
    session.clear();
    showLogin();
  }
}

// Token expired or account disabled while using the app.
window.addEventListener("auth:expired", () => {
  toast("Your session ended - please sign in again.", "error");
  showLogin();
});

// Demo personas, or [] when DEMO_LOGIN is off (the endpoint then answers 404).
async function demoUsers() {
  try {
    return await api("/auth/demo-users");
  } catch {
    return [];
  }
}

async function demoLogin(userId) {
  const { access_token: token } = await api("/auth/demo-login",
    { method: "POST", json: { user_id: userId } });
  session.set(token);
  await boot();
}

// =============================================================================
// 2. LOGIN SCREEN
// =============================================================================
async function showLogin() {
  topbar.hidden = true;
  const email = el("input", { type: "email", required: true, autocomplete: "username",
    placeholder: "name@orbitra.example" });
  const password = el("input", { type: "password", required: true,
    autocomplete: "current-password" });
  const error = el("p", { class: "error", role: "alert" });

  const form = el("form", {
    class: "card login-form",
    onsubmit: async (e) => {
      e.preventDefault();
      error.textContent = "";
      try {
        const { access_token: token } = await api("/auth/login",
          { method: "POST", form: { username: email.value, password: password.value } });
        session.set(token);
        await boot();
      } catch (err) {
        error.textContent = err.message;
        password.value = "";
      }
    },
  },
  el("h2", {}, "Sign in"),
  el("label", { class: "field" }, el("span", {}, "Email"), email),
  el("label", { class: "field" }, el("span", {}, "Password"), password),
  error,
  el("button", { class: "btn btn-primary", type: "submit" }, "Sign in"));

  const page = el("div", { class: "login" },
    el("div", { class: "login-intro" },
      el("div", { class: "brand brand-large" }, el("span", { class: "logo" }), "Orbitra Assist"),
      el("p", {}, "Ask questions about company documents. You only ever get answers from "
        + "documents your clearance and departments allow."),
      form));
  clear(app).append(page);

  // One-click personas - only when the server has DEMO_LOGIN enabled (dev).
  const personas = await demoUsers();
  if (personas.length) {
    page.append(el("section", { class: "personas" },
      el("h3", {}, "Demo: sign in as…"),
      el("p", { class: "muted" }, "Dev mode only. Try the same question as different people."),
      el("div", { class: "persona-grid" }, personas.map((p) => el("button", {
        class: "persona", type: "button",
        onclick: () => demoLogin(p.user_id).catch((err) => toast(err.message, "error")),
      },
      el("span", { class: "persona-name" }, p.name),
      el("span", { class: "persona-title" }, p.title),
      el("span", { class: "persona-meta" }, clearanceChip(p.clearance),
        el("span", { class: "muted" }, p.departments.join(", "))))))));
  }
}

// =============================================================================
// 3. APP SCREEN - top bar + Ask / Admin
// =============================================================================
async function showApp(user) {
  // --- top bar: who you are (as the server says), switcher, logout ---
  const tabs = [["Ask", renderChat]];
  if (user.role === "admin") tabs.push(["Admin", renderAdmin]);

  const tabButtons = tabs.map(([label, render]) => el("button", {
    class: "tab", type: "button",
    onclick: (e) => {
      tabButtons.forEach((b) => b.classList.remove("active"));
      e.currentTarget.classList.add("active");
      render(clear(app), user);
    },
  }, label));

  const personas = await demoUsers();
  const switcher = personas.length ? el("select", {
    class: "switcher", "aria-label": "Switch demo user",
    onchange: (e) => demoLogin(e.target.value).catch((err) => toast(err.message, "error")),
  }, personas.map((p) => el("option", { value: p.user_id, selected: p.user_id === user.user_id },
    `${p.name} - ${p.title}`))) : null;

  clear(topbar).append(
    el("div", { class: "brand" }, el("span", { class: "logo" }), "Orbitra Assist"),
    el("nav", { class: "tabs" }, tabButtons),
    el("div", { class: "who" },
      el("div", { class: "who-text" },
        el("span", { class: "who-name" }, user.name),
        el("span", { class: "muted" }, `${user.role} · ${user.departments.join(", ")}`)),
      clearanceChip(user.clearance),
      switcher,
      el("button", { class: "btn btn-small", type: "button",
        onclick: () => { session.clear(); showLogin(); } }, "Sign out")));
  topbar.hidden = false;
  tabButtons[0].click();
}

boot();
