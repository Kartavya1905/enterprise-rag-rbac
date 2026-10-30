/*
 * FILE:         app/web/js/admin.js
 * WHAT IT DOES: The admin screens (only shown to role "admin"):
 *                 DOCUMENTS  list every document + its access label; edit or remove
 *                 UPLOAD     add a new document with its access label
 *                 AUDIT      security dashboard + event log (masked) + tamper check
 * WHERE IT FITS: Phase 10. Calls /admin/* (Phase 8) and /admin/audit* (Phase 9).
 *
 * The UI hides these screens from non-admins, but that is only convenience: the SERVER
 * refuses every /admin call from anyone without the admin role (403).
 */

import { api } from "./api.js";
import { clear, clearanceChip, DEPARTMENTS, el, toast } from "./dom.js";

// =============================================================================
// 1. THE ADMIN SCREEN - three sub-tabs
// =============================================================================
export function renderAdmin(root) {
  const body = el("div", { class: "admin-body" });
  const tabs = [
    ["Documents", renderDocuments],
    ["Upload", renderUpload],
    ["Audit log", renderAudit],
  ];
  const buttons = tabs.map(([label, render]) => el("button", {
    class: "subtab", type: "button",
    onclick: (e) => {
      buttons.forEach((b) => b.classList.remove("active"));
      e.currentTarget.classList.add("active");
      render(clear(body));
    },
  }, label));
  root.append(el("div", { class: "admin" }, el("nav", { class: "subtabs" }, buttons), body));
  buttons[0].click();
}

// =============================================================================
// 2. DOCUMENTS - table of every document and who may read it
// =============================================================================
async function renderDocuments(root) {
  root.append(el("p", { class: "muted" }, "Loading documents…"));
  let docs;
  try {
    docs = await api("/admin/documents");
  } catch (err) {
    clear(root).append(el("p", { class: "error" }, err.message));
    return;
  }
  const rows = docs.map((d) => documentRow(d, () => renderDocuments(clear(root))));
  clear(root).append(
    el("p", { class: "muted" },
      "Changing access takes effect in search immediately. You cannot grant yourself access."),
    el("div", { class: "table-wrap" }, el("table", { class: "table" },
      el("thead", {}, el("tr", {}, ["Document", "Clearance", "Departments", "Allowed",
        "Denied", "Chunks", ""].map((h) => el("th", {}, h)))),
      el("tbody", {}, rows))));
}

function documentRow(doc, refresh) {
  const row = el("tr", {},
    el("td", {}, el("div", { class: "doc-title" }, doc.title),
      el("div", { class: "muted mono" }, doc.doc_id)),
    el("td", {}, clearanceChip(doc.clearance_level)),
    el("td", {}, doc.departments.join(", ")),
    el("td", { class: "mono" }, doc.allowed_users.join(", ") || "-"),
    el("td", { class: "mono" }, doc.denied_users.join(", ") || "-"),
    el("td", {}, doc.chunk_count),
    el("td", { class: "actions" },
      el("button", { class: "btn btn-small", type: "button",
        onclick: () => row.after(aclEditor(doc, refresh)) }, "Edit access"),
      el("button", { class: "btn btn-small btn-danger", type: "button",
        onclick: () => removeDocument(doc, refresh) }, "Remove")));
  return row;
}

// Inline form under a row: clearance, departments, allowed / denied users.
function aclEditor(doc, refresh) {
  const clearance = el("select", { "aria-label": "Clearance" },
    [1, 2, 3, 4].map((n) => el("option", { value: n, selected: n === doc.clearance_level }, n)));
  const depts = departmentPicker(doc.departments);
  const allowed = el("input", { value: doc.allowed_users.join(", "), placeholder: "user ids" });
  const denied = el("input", { value: doc.denied_users.join(", "), placeholder: "user ids" });

  const editorRow = el("tr", { class: "editor-row" }, el("td", { colspan: 7 },
    el("form", {
      class: "editor",
      onsubmit: async (e) => {
        e.preventDefault();
        try {
          await api(`/admin/documents/${encodeURIComponent(doc.doc_id)}/acl`, {
            method: "PATCH",
            json: {
              clearance_level: Number(clearance.value),
              departments: depts.values(),
              allowed_users: splitIds(allowed.value),
              denied_users: splitIds(denied.value),
            },
          });
          toast(`Access updated for ${doc.title}`, "ok");
          refresh();
        } catch (err) {
          toast(err.message, "error"); // e.g. "administrators cannot grant themselves access"
        }
      },
    },
    field("Clearance", clearance), field("Departments", depts.node),
    field("Allowed users", allowed), field("Denied users", denied),
    el("div", { class: "editor-actions" },
      el("button", { class: "btn btn-primary btn-small", type: "submit" }, "Save"),
      el("button", { class: "btn btn-small", type: "button",
        onclick: () => editorRow.remove() }, "Cancel")))));
  return editorRow;
}

async function removeDocument(doc, refresh) {
  if (!window.confirm(`Remove "${doc.title}" from search? The file itself is kept.`)) return;
  try {
    await api(`/admin/documents/${encodeURIComponent(doc.doc_id)}`, { method: "DELETE" });
    toast(`Removed ${doc.title}`, "ok");
    refresh();
  } catch (err) {
    toast(err.message, "error");
  }
}

// =============================================================================
// 3. UPLOAD - a new document with its access label
// =============================================================================
function renderUpload(root) {
  const file = el("input", { type: "file", accept: ".pdf,.docx,.xlsx", required: true });
  const docId = el("input", { required: true, pattern: "[a-z0-9][a-z0-9-]*",
    placeholder: "e.g. hr-relocation-policy" });
  const title = el("input", { required: true, placeholder: "Document title" });
  const clearance = el("select", {}, [1, 2, 3, 4].map((n) => el("option", { value: n }, n)));
  const depts = departmentPicker([]);
  const submit = el("button", { class: "btn btn-primary", type: "submit" }, "Upload");

  root.append(el("form", {
    class: "card upload",
    onsubmit: async (e) => {
      e.preventDefault();
      if (!depts.values().length) { toast("Pick at least one department", "error"); return; }
      const data = new FormData();
      data.append("file", file.files[0]);
      data.append("doc_id", docId.value.trim());
      data.append("title", title.value.trim());
      data.append("clearance_level", clearance.value);
      data.append("departments", depts.values().join(","));
      submit.disabled = true;
      try {
        const doc = await api("/admin/documents", { method: "POST", body: data });
        toast(`Uploaded ${doc.title} (${doc.chunk_count} chunks)`, "ok");
        e.target.reset();
      } catch (err) {
        toast(err.message, "error");
      } finally {
        submit.disabled = false;
      }
    },
  },
  el("p", { class: "muted" }, "PDF, Word or Excel, up to 10 MB. The file is checked, "
    + "parsed, chunked and searchable right away - by the people you allow."),
  field("File", file), field("Document id", docId), field("Title", title),
  field("Clearance", clearance), field("Departments", depts.node), submit));
}

// =============================================================================
// 4. AUDIT - security dashboard, tamper check and the event log
// =============================================================================
async function renderAudit(root) {
  const typeFilter = el("select", { "aria-label": "Event type" },
    ["", "query", "search", "login", "admin", "audit_view"].map((t) =>
      el("option", { value: t }, t || "All events")));
  const summary = el("div", { class: "stats" });
  const chain = el("span", { class: "chain" }, "Checking log integrity…");
  const events = el("div", { class: "table-wrap" });

  const load = async () => {
    try {
      const [stats, verify, list] = await Promise.all([
        api("/admin/audit/stats?hours=24"),
        api("/admin/audit/verify"),
        api(`/admin/audit?limit=50${typeFilter.value ? `&event_type=${typeFilter.value}` : ""}`),
      ]);
      clear(summary).append(...statCards(stats));
      chain.className = `chain ${verify.ok ? "chain-ok" : "chain-bad"}`;
      chain.textContent = verify.ok
        ? `✓ Log intact - ${verify.checked} events verified`
        : `✗ Log altered at event #${verify.first_bad_id}`;
      clear(events).append(eventTable(list));
    } catch (err) {
      clear(events).append(el("p", { class: "error" }, err.message));
    }
  };
  typeFilter.addEventListener("change", load);

  root.append(
    el("div", { class: "audit-head" }, el("h3", {}, "Last 24 hours"), chain),
    summary,
    el("div", { class: "audit-head" }, el("h3", {}, "Recent events"),
      el("div", { class: "row" }, typeFilter,
        el("button", { class: "btn btn-small", type: "button", onclick: load }, "Refresh"))),
    el("p", { class: "muted" }, "Questions that touched documents you may not read are shown "
      + "as [hidden] - the audit log never reveals restricted content."),
    events);
  await load();
}

function statCards(stats) {
  const s = stats.security;
  const card = (label, value, alert) =>
    el("div", { class: `stat ${alert && value > 0 ? "stat-alert" : ""}` },
      el("div", { class: "stat-value" }, value ?? "-"), el("div", { class: "stat-label" }, label));
  return [
    card("Questions", stats.by_event_type.query || 0),
    card("Injections refused", s.injections_refused, true),
    card("Failed logins", s.failed_logins, true),
    card("Self-grants blocked", s.self_grants_blocked, true),
    card("Rate limited", s.rate_limited, true),
    card("Answer time p95 (ms)", stats.query_latency_ms.p95),
  ];
}

function eventTable(list) {
  const hidden = (text) => text === "[hidden]" ? el("span", { class: "hidden-tag" }, "hidden") : text;
  return el("table", { class: "table events" },
    el("thead", {}, el("tr", {}, ["#", "Time (UTC)", "Event", "Outcome", "User", "Question",
      "Documents", "ms"].map((h) => el("th", {}, h)))),
    el("tbody", {}, list.map((e) => el("tr", {},
      el("td", {}, e.id),
      el("td", { class: "mono" }, e.timestamp.slice(5, 19).replace("T", " ")),
      el("td", {}, e.event_type),
      el("td", {}, el("span", { class: `outcome outcome-${e.outcome}` }, e.outcome)),
      el("td", { class: "mono" }, e.user_id || e.detail?.attempted_username || "-"),
      el("td", { class: "question" }, hidden(e.question) || "-"),
      el("td", { class: "mono" }, e.retrieved_doc_ids.length
        ? e.retrieved_doc_ids.map((d) => [hidden(d), " "]) : "-"),
      el("td", {}, e.latency_ms ?? "")))));
}

// =============================================================================
// 5. SMALL FORM HELPERS
// =============================================================================
function field(label, control) {
  return el("label", { class: "field" }, el("span", {}, label), control);
}

function splitIds(text) {
  return text.split(",").map((s) => s.trim()).filter(Boolean);
}

// Checkboxes for departments, including "all" (= every department).
function departmentPicker(selected) {
  const boxes = ["all", ...DEPARTMENTS].map((d) => {
    const box = el("input", { type: "checkbox", value: d, checked: selected.includes(d) });
    return { d, box, node: el("label", { class: "check" }, box, d) };
  });
  return {
    node: el("div", { class: "checks" }, boxes.map((b) => b.node)),
    values: () => boxes.filter((b) => b.box.checked).map((b) => b.d),
  };
}
