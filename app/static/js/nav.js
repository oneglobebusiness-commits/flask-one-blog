/* Sidebar: primary market display and editor. */
(function () {
  "use strict";
  var esc = App.esc;
  var markets = [];
  var countries = [];
  var selected = [];
  var query = "";
  var saving = false;

  function asList(value) {
    if (Array.isArray(value)) return value.filter(Boolean);
    return value ? [value] : [];
  }

  function renderCard() {
    var label = markets.length ? markets.join(", ") : "—";
    document.getElementById("navStore").innerHTML =
      '<div class="ss-meta ss-market"><span title="' + esc(label) + '">Market: ' + esc(label) + "</span>" +
      '<button type="button" class="nv-edit" id="editMarket">✎ Edit</button></div>';
    document.getElementById("editMarket").addEventListener("click", openModal);
  }

  function filtered() {
    var q = query.trim().toLowerCase();
    return countries.filter(function (c) { return !q || c.toLowerCase().indexOf(q) !== -1; });
  }

  function canAddCustom() {
    var typed = query.trim().toLowerCase();
    return typed && !filtered().some(function (c) { return c.toLowerCase() === typed; }) &&
      !selected.some(function (m) { return m.toLowerCase() === typed; });
  }

  function renderDynamic() {
    var host = document.getElementById("marketModal");
    host.querySelector(".mm-selected").innerHTML = selected.length
      ? '<div class="mm-chips">' + selected.map(function (m, i) {
          return '<span class="mm-chip">' + esc(m) + '<button type="button" data-remove="' + i + '" aria-label="Remove ' + esc(m) + '">×</button></span>';
        }).join("") + "</div>"
      : '<div class="mm-none">No markets selected yet.</div>';
    var rows = filtered().map(function (c) {
      var on = selected.indexOf(c) !== -1;
      return '<button type="button" class="mm-opt' + (on ? " on" : "") + '" data-country="' + esc(c) + '"><span class="mm-box">' + (on ? "✓" : "") + "</span>" + esc(c) + "</button>";
    });
    if (canAddCustom()) rows.push('<button type="button" class="mm-opt mm-add" id="mmAdd">+ Add "' + esc(query.trim()) + '"</button>');
    host.querySelector(".mm-list").innerHTML = rows.join("") || '<div class="mm-empty">Type a country name to add it.</div>';
    host.querySelector(".mm-count").textContent = selected.length + " market(s) selected";
    var save = host.querySelector("#mmSave");
    save.disabled = saving || selected.length === 0;
    save.innerHTML = saving ? '<span class="mm-spin"></span>Saving…' : "Save Markets";
  }

  function closeModal() {
    if (saving) return;
    document.getElementById("marketModal").innerHTML = "";
    document.removeEventListener("keydown", onEscape);
  }

  function onEscape(event) { if (event.key === "Escape") closeModal(); }

  function addCustom() {
    if (!canAddCustom()) return;
    selected.push(query.trim());
    query = "";
    var input = document.getElementById("mmSearch");
    input.value = "";
    input.focus();
    renderDynamic();
  }

  function save() {
    if (!selected.length) return;
    saving = true;
    renderDynamic();
    App.api("POST", "/store-intelligence/primary-market", { body: { markets: selected } })
      .then(function (data) {
        markets = asList(data.primaryMarket);
        saving = false;
        renderCard();
        closeModal();
        document.dispatchEvent(new CustomEvent("markets-updated", { detail: markets }));
        App.toast("Markets updated successfully!");
      })
      .catch(function (err) {
        saving = false;
        renderDynamic();
        App.toast(err.message || "Failed to save markets");
      });
  }

  function openModal() {
    selected = markets.slice();
    query = "";
    App.api("GET", "/country-events").then(function (list) {
      countries = Array.isArray(list) ? list : [];
      if (document.querySelector("#marketModal .mm-list")) renderDynamic();
    }).catch(function () { App.toast("Failed to load country suggestions"); });

    var host = document.getElementById("marketModal");
    host.innerHTML =
      '<div class="mm-ov"><div class="mm-bd"></div><div class="mm-panel" role="dialog" aria-modal="true" aria-label="Manage markets">' +
      '<div class="mm-head"><h3>Manage Markets</h3><p>Choose the countries your store sells to. Their seasonal, cultural and retail events power your campaigns.</p></div>' +
      '<button type="button" class="mm-x" aria-label="Close">✕</button>' +
      '<div class="mm-body"><div class="mm-label">Selected</div><div class="mm-selected"></div>' +
      '<div class="mm-label">Add a market</div><div class="mm-search"><input id="mmSearch" placeholder="Search or type a country…" aria-label="Search countries"></div><div class="mm-list"></div></div>' +
      '<div class="mm-foot"><span class="mm-count"></span><div class="mm-actions"><button type="button" class="mm-btn mm-gho" id="mmCancel">Cancel</button><button type="button" class="mm-btn mm-pri" id="mmSave">Save Markets</button></div></div>' +
      "</div></div>";
    host.querySelector(".mm-bd").addEventListener("click", closeModal);
    host.querySelector(".mm-x").addEventListener("click", closeModal);
    host.querySelector("#mmCancel").addEventListener("click", closeModal);
    host.querySelector("#mmSave").addEventListener("click", save);
    var input = host.querySelector("#mmSearch");
    input.addEventListener("input", function () { query = input.value; renderDynamic(); });
    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter") { event.preventDefault(); addCustom(); }
    });
    host.querySelector(".mm-body").addEventListener("click", function (event) {
      var remove = event.target.closest("[data-remove]");
      if (remove) { selected.splice(Number(remove.getAttribute("data-remove")), 1); renderDynamic(); return; }
      if (event.target.closest("#mmAdd")) { addCustom(); return; }
      var option = event.target.closest("[data-country]");
      if (option) {
        var country = option.getAttribute("data-country");
        var index = selected.indexOf(country);
        if (index === -1) selected.push(country); else selected.splice(index, 1);
        renderDynamic();
      }
    });
    document.addEventListener("keydown", onEscape);
    renderDynamic();
    input.focus();
  }

  App.store().then(function (store) {
    markets = asList(store && store.primaryMarket);
    renderCard();
  }).catch(function () {
    document.getElementById("navStore").innerHTML = '<div class="ss-meta">Store details unavailable.</div>';
  });
})();
