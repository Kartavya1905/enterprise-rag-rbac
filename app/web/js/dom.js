/*
 * FILE:         app/web/js/dom.js
 * WHAT IT DOES: Tiny helpers for building the page safely.
 * WHERE IT FITS: Phase 10 - used by every other script.
 *
 * SECURITY RULE FOR THE WHOLE UI:
 *   Text from the server (answers, document text, names, audit questions) is ALWAYS
 *   inserted as a text node - never as HTML. A document or an AI answer containing
 *   "<img src=x onerror=...>" is shown as harmless characters instead of running.
 *   That's why this UI never uses innerHTML (a test checks it).
 */

// =============================================================================
// 1. el() - create an element:  el("button", {class: "btn", onclick: fn}, "Save")
// =============================================================================
export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  append(node, children);
  return node;
}

// Strings and numbers become TEXT nodes - this is the XSS protection.
export function append(node, children) {
  for (const child of [children].flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  node.replaceChildren();
  return node;
}

// =============================================================================
// 2. TOASTS - short messages in the corner
// =============================================================================
export function toast(message, kind = "info") {
  const box = el("div", { class: `toast toast-${kind}` }, message);
  document.getElementById("toasts").append(box);
  setTimeout(() => box.remove(), 4500);
}

// =============================================================================
// 3. LABELS - clearance names and colours used across the UI
// =============================================================================
export const CLEARANCE = {
  1: { name: "Public", cls: "lvl-1" },
  2: { name: "Internal", cls: "lvl-2" },
  3: { name: "Confidential", cls: "lvl-3" },
  4: { name: "Restricted", cls: "lvl-4" },
};

export const DEPARTMENTS = ["engineering", "sales", "hr", "finance", "executive"];

export function clearanceChip(level) {
  const info = CLEARANCE[level] || { name: `Level ${level}`, cls: "" };
  return el("span", { class: `chip ${info.cls}`, title: `Clearance ${level}` },
    `${level} · ${info.name}`);
}
