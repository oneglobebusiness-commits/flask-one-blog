/* Dashboard: pedal controls, guided tours, topic wizard, campaign pickers and blog generation. */
(function () {
  "use strict";
  var esc = App.esc;
  var SAVED_SELECTION_KEY = "meris_lvx_topic_products_v1";
  var MAX_PRODUCTS_PER_TOPIC = 2;
  var MIN_TOPIC_LENGTH = 10;

  var KNOBS = [
    { id: "kFeedback", label: "store" },
    { id: "kLeft", label: "competitor" },
    { id: "kPreset", label: "calendar" },
    { id: "kRight", label: "keywords" },
  ];

  var ARROWS = {
    upRight: { box: "0 0 120 70", line: "M6 58 C 28 58, 42 47, 52 47 C 64 47, 64 59, 55 58 C 46 57, 51 40, 70 30 C 84 22, 97 17, 107 13", head: "M96 7 L108 13 L98 24" },
    down: { box: "0 0 70 120", line: "M60 8 C 60 24, 50 30, 44 40 C 36 52, 52 58, 48 66 C 44 74, 32 68, 32 80 C 32 94, 34 100, 35 108", head: "M24 98 L35 111 L47 98" },
    up: { box: "0 0 70 120", line: "M60 112 C 60 96, 50 90, 44 80 C 36 68, 52 62, 48 54 C 44 46, 32 52, 32 40 C 32 26, 34 20, 35 12", head: "M24 22 L35 9 L47 22" },
  };

  var KNOB_TOUR = [
    { msg: "✦ <b>Preview</b> — start here: pick blog topics, attach products to each one and generate your blogs step by step.", variant: "down", layout: "row", style: { left: "4.5cqw", top: "0.4cqw" } },
    { msg: "⚡ <b>Generator</b> — instantly writes blogs from your already-selected topics &amp; products. No wizard, one tap.", variant: "down", layout: "row", style: { left: "19.5cqw", top: "0.4cqw" } },
    { msg: "🚀 <b>Generate</b> — creates a campaign blog from your Store, Competitor, Calendar and Keywords selections below.", variant: "down", layout: "row-reverse", style: { right: "2cqw", top: "0.4cqw" } },
    { msg: "🏬 <b>Store</b> — choose the Collections and Products your campaign blog should feature and link to.", variant: "up", layout: "col", style: { left: "5cqw", top: "37.5cqw" }, arrow: { marginLeft: "6cqw" } },
    { msg: "🎯 <b>Competitor</b> — pick one competitor to position your blog against.", variant: "up", layout: "col", style: { left: "27cqw", top: "37.5cqw" }, arrow: { marginLeft: "8cqw" } },
    { msg: "📅 <b>Calendar</b> — tie the blog to a Seasonal, Cultural, Retail or Experiential moment so it lands at the right time.", variant: "up", layout: "col", style: { left: "51cqw", top: "37.5cqw" }, arrow: { marginLeft: "8cqw" } },
    { msg: "🔑 <b>Keywords</b> — select the short-tail and long-tail keywords the campaign blog should target.", variant: "up", layout: "col", style: { left: "58cqw", top: "37.5cqw" }, arrow: { marginLeft: "24cqw" } },
  ];

  var PORTAL_TOUR = {
    topics: { msg: "<b>Step 1</b> — Tap the <b>Topics</b> star and choose your blog topics.", arrow: { left: "18%", top: "46%", rotate: -65, size: 150 }, bubble: { left: "24%", top: "64%" }, next: "products" },
    products: { msg: "<b>Step 2</b> — Then open <b>Product</b> to assign up to 2 products to each topic.", arrow: { left: "54%", top: "44%", rotate: -30, size: 150 }, bubble: { left: "30%", top: "62%" }, next: "blogs" },
    blogs: { msg: "<b>Step 3</b> — Your generated blogs live under <b>Blogs</b>. Edit, schedule or publish them from there.", arrow: { left: "26%", top: "60%", rotate: 20, size: 140 }, bubble: { left: "5%", top: "44%" }, next: null },
  };

  var state = {
    store: null,
    plan: null,
    selectedKnob: "kFeedback",
    topics: [],
    selected: {},
    topicProducts: {},
    productCache: {},
    activeTopic: null,
    wizardView: null,
    portalTourShown: false,
    portalStep: null,
    topicsHintShown: false,
    topicsHint: false,
    titlePrompt: "",
    generatingTitles: false,
    pickerCollections: [],
    pickerCollection: "",
    productSearch: "",
    productResults: [],
    searching: false,
    knobStep: null,
    knobStop: KNOB_TOUR.length - 1,
    blogs: [],
    generating: false,
    campaign: { collections: [], products: [], competitorUrl: "", calendar: { type: "", name: "", country: "" }, shortTail: [], longTail: [] },
  };
  var uidCounter = 0;
  function uid() { uidCounter += 1; return "t" + Date.now().toString(36) + uidCounter; }
  function $(id) { return document.getElementById(id); }

  function arrowSvg(variant, size, rotate) {
    var a = ARROWS[variant];
    var width = typeof size === "number" ? size + "px" : size;
    return '<div class="guide-arrow" style="width:' + width + ";" + (rotate ? "rotate:" + rotate + "deg" : "") + '"><svg viewBox="' + a.box + '" aria-hidden="true">' +
      '<path class="ga-line" d="' + a.line + '"></path><path class="ga-head" d="' + a.head + '"></path></svg></div>';
  }

  /* ---------- plan helpers ---------- */
  function remaining(feature) { return (state.plan && state.plan.remaining && state.plan.remaining[feature]) || 0; }
  function refreshPlan() {
    return App.plan().then(function (plan) { state.plan = plan; }).catch(function () {});
  }
  function hasArticlesFor(count) {
    if (remaining("articles") >= count) return true;
    showPlanLimit(count);
    return false;
  }
  function handleLimitError(err, needed) {
    var code = err.data && err.data.code;
    if (code === "LIMIT_REACHED" || code === "NO_SUBSCRIPTION") {
      refreshPlan().then(function () { showPlanLimit(needed, err.message); });
      return true;
    }
    return false;
  }

  /* ---------- screen ---------- */
  function keywordStack(list) {
    return (list || []).slice(0, 4).map(function (kw) {
      return '<span class="kw-item" title="' + esc(kw) + '"><span class="kw-text">' + esc(kw) + '</span><span class="kw-full">' + esc(kw) + "</span></span>";
    }).join("");
  }
  function renderScreen() {
    var s = state.store || {};
    var markets = Array.isArray(s.primaryMarket) ? s.primaryMarket : s.primaryMarket ? [s.primaryMarket] : [];
    $("scrMarket").textContent = markets.join(", ").split("(")[0].trim() || "—";
    $("scrLang").textContent = s.language || "EN";
    $("scrShort").innerHTML = keywordStack(s.shortTailKeywords);
    $("scrLong").innerHTML = keywordStack(s.longTailKeywords);
    $("scrVoice").textContent = (s.brandVoice || "—").split(/[,.;]/)[0].trim().slice(0, 18);
    $("scrCount").textContent = String(state.topics.length).padStart(2, "0");
  }

  /* ---------- knob row + foot row ---------- */
  function renderKnobs() {
    var row = $("knobRow");
    KNOBS.forEach(function (knob) {
      var tile = document.createElement("div");
      tile.className = "face tile";
      tile.setAttribute("data-knob", knob.id);
      tile.setAttribute("role", "button");
      tile.tabIndex = 0;
      tile.innerHTML = '<div class="knob-unit"><div class="knob black" id="' + knob.id + '"><div class="pointer"></div></div><span class="label">' + knob.label + "</span></div>";
      App.onActivate(tile, function () { clickKnob(tile, knob.id); });
      row.appendChild(tile);
    });
    positionBeam(row.querySelector('[data-knob="' + state.selectedKnob + '"]'));
    renderFoot();
  }
  function positionBeam(tile) {
    var foot = $("footRow");
    if (!tile) return;
    var f = foot.getBoundingClientRect();
    var t = tile.getBoundingClientRect();
    if (f.width) foot.style.setProperty("--ox", (((t.left + t.width / 2 - f.left) / f.width) * 100).toFixed(1) + "%");
  }
  function clickKnob(tile, id) {
    state.selectedKnob = state.selectedKnob === id ? "" : id;
    if (state.selectedKnob) positionBeam(tile);
    renderFoot();
  }
  function footSwitches() {
    var c = state.campaign;
    switch (state.selectedKnob) {
      case "kFeedback":
        return [
          { label: "collections", on: c.collections.length > 0, click: openCollections },
          { label: "products", on: c.products.length > 0, click: openProducts },
        ];
      case "kLeft":
        return ((state.store && state.store.competitors) || []).map(function (comp) {
          return { label: comp.name, on: !!comp.website && c.competitorUrl === comp.website, click: function () { openCompetitor(comp); } };
        });
      case "kPreset":
        return ["seasonal", "cultural", "retail", "experiential"].map(function (type) {
          return { label: type, on: c.calendar.type === type, click: function () { openCalendar(type); } };
        });
      case "kRight":
        return [
          { label: "short‑tail", on: c.shortTail.length > 0, click: function () { openKeywords("shortTail"); } },
          { label: "long‑tail", on: c.longTail.length > 0, click: function () { openKeywords("longTail"); } },
        ];
      default:
        return [];
    }
  }
  function renderFoot() {
    var foot = $("footRow");
    foot.className = "foot-row" + (state.selectedKnob ? " linked-green" : "");
    foot.innerHTML = "";
    var switches = footSwitches();
    if (!switches.length) {
      foot.innerHTML = '<span class="foot-empty">' + (state.selectedKnob === "kLeft" ? "No competitors found yet." : "Choose a knob above.") + "</span>";
    }
    switches.forEach(function (sw) {
      var tile = document.createElement("div");
      tile.className = "fs-tile";
      tile.setAttribute("role", "button");
      tile.tabIndex = 0;
      tile.innerHTML = '<div class="switch-unit"><div class="led' + (sw.on ? " on" : "") + '"></div><div class="footswitch"></div><div class="sw-label">' + esc(sw.label) + "</div></div>";
      App.onActivate(tile, sw.click);
      foot.appendChild(tile);
    });
    var brand = document.createElement("div");
    brand.className = "brand";
    brand.innerHTML = 'meris <span class="box">lvx</span>';
    foot.appendChild(brand);
  }

  /* ---------- knob tour ---------- */
  function renderKnobTour() {
    var host = $("knobHint");
    if (state.knobStep === null || !KNOB_TOUR[state.knobStep]) { host.innerHTML = ""; return; }
    var step = KNOB_TOUR[state.knobStep];
    var last = state.knobStep >= state.knobStop;
    host.innerHTML = '<div class="knob-hint ' + step.layout + '"><div class="guide-anchor kh-arrow">' + arrowSvg(step.variant, "100%") + "</div>" +
      '<div class="guide-bubble">' + step.msg + '<div class="gb-actions"><button type="button" class="btn btn-gho btn-sm" id="tourSkip">Skip</button>' +
      '<button type="button" class="btn btn-pri btn-sm" id="tourNext">' + (last ? "Got it ✓" : "Next →") + "</button></div></div></div>";
    var hint = host.firstChild;
    Object.keys(step.style).forEach(function (key) { hint.style[key] = step.style[key]; });
    if (step.arrow) hint.querySelector(".kh-arrow").style.marginLeft = step.arrow.marginLeft;
    $("tourSkip").addEventListener("click", function () { state.knobStep = null; renderKnobTour(); });
    $("tourNext").addEventListener("click", function () {
      state.knobStep = last ? null : state.knobStep + 1;
      renderKnobTour();
    });
  }
  function toggleTour(start, stop) {
    if (state.knobStep !== null) state.knobStep = null;
    else { state.knobStep = start; state.knobStop = stop; }
    renderKnobTour();
  }

  /* ---------- topic wizard ---------- */
  function selectedTopics() { return state.topics.filter(function (t) { return state.selected[t.id]; }); }
  function selectedCount() { return selectedTopics().length; }

  function closeWizard() {
    state.wizardView = null;
    state.portalStep = null;
    $("overlayHost").innerHTML = "";
  }
  function openWizard() {
    if (!state.store) { App.toast("Store data not loaded yet"); return; }
    state.knobStep = null;
    renderKnobTour();
    state.wizardView = "home";
    if (!state.portalTourShown) { state.portalStep = "topics"; state.portalTourShown = true; }
    renderWizard();
  }
  function renderWizard() {
    var host = $("overlayHost");
    var inner = "";
    if (state.wizardView === "home") inner = portalHtml();
    else if (state.wizardView === "topics") inner = topicsHtml();
    else if (state.wizardView === "products") inner = productsHtml();
    host.innerHTML = '<div class="ov open"><div class="ov-bd" data-w="close"></div><button type="button" class="wiz-x" data-w="close" aria-label="Close">×</button><div class="portal-wrap">' + inner + "</div></div>";
    if (state.wizardView === "topics") { renderTopicGrid(); renderTopicsHint(); bindTopicInputs(); }
    if (state.wizardView === "products") { renderProductTopics(); renderCollectionChips(); renderProductGrid(); bindProductSearch(); }
  }
  function portalTourHtml() {
    var step = PORTAL_TOUR[state.portalStep];
    if (!step) return "";
    return '<div class="guide-layer"><div class="guide-anchor" style="left:' + step.arrow.left + ";top:" + step.arrow.top + '">' + arrowSvg("upRight", step.arrow.size, step.arrow.rotate) + "</div>" +
      '<div class="guide-bubble" style="left:' + step.bubble.left + ";top:" + step.bubble.top + '">' + step.msg + '<div class="gb-actions">' +
      (step.next ? '<button type="button" class="btn btn-gho btn-sm" data-w="tour-skip">Skip</button>' : "") +
      '<button type="button" class="btn btn-pri btn-sm" data-w="tour-next">' + (step.next ? "Next →" : "Got it ✓") + "</button></div></div></div>";
  }
  function portalHtml() {
    var done = selectedCount() > 0 ? " done" : "";
    return '<div class="portal"><span class="pring r1"></span><span class="pring r2"></span><span class="pring r3"></span><span class="pring r4"></span><div class="portal-core"></div>' +
      '<div class="portal-hint">✦ Tap a star to explore</div><button type="button" class="help-fab" title="Show me around" data-w="tour-start">?</button>' + portalTourHtml() +
      '<button type="button" class="pstar big' + done + '" style="left:28%;top:38%" data-w="topics"><span class="pstar-dot"></span><span class="pstar-label">Topics</span></button>' +
      '<button type="button" class="pstar big' + done + '" style="right:8%;top:38%;transform:translateY(-50%)" data-w="products"><span class="pstar-dot"></span><span class="pstar-label">Product</span></button>' +
      '<button type="button" class="pstar big" style="left:50%;top:70%" data-w="blogs"><span class="pstar-dot"></span><span class="pstar-label">Blogs</span></button>' +
      '<button type="button" class="portal-save" data-w="save-close">Save &amp; close</button></div>';
  }
  function topicsHtml() {
    return '<div class="cardhost open"><div class="card"><div class="cardtop"><button type="button" class="btn btn-gho btn-sm" data-w="home">✦ Stars</button><h3>Blog Topics</h3>' +
      '<button type="button" class="hint-replay in-card" title="Show help" data-w="topics-hint">?</button></div>' +
      '<div class="sub">Step 1 of 3 — Select topics, then continue to product selection.</div>' +
      '<div class="nt-toolbar"><div class="product-search-box nt-promptbox"><span class="search-icon">✦</span><input id="titlePrompt" maxlength="500" placeholder=\'Optional: describe titles you want, e.g. "Diwali gift ideas"\' value="' + esc(state.titlePrompt) + '"></div>' +
      '<button type="button" class="btn btn-pri btn-sm" id="newTitles" data-w="new-titles"></button><div id="topicsHintHost"></div></div>' +
      '<div class="muted" style="margin-bottom:10px">Your existing topics and selections are kept when you generate new titles.</div>' +
      '<div class="topic-grid" id="topicGrid"></div>' +
      '<div class="field" style="margin-top:12px"><input id="customTopic" maxlength="200" placeholder="Add your own topic + Enter"><button type="button" class="btn btn-gho" data-w="add-topic">Add</button></div>' +
      '<div class="wiz-foot"><span class="muted" id="topicCount"></span><button type="button" class="btn btn-pri" id="toProducts" data-w="to-products">Next — Select Products →</button></div></div></div>';
  }
  function renderTopicGrid() {
    var grid = $("topicGrid");
    if (!grid) return;
    grid.innerHTML = state.topics.map(function (t) {
      var on = !!state.selected[t.id];
      return '<div class="topic-card' + (on ? " sel" : "") + '" data-topic="' + esc(t.id) + '" role="checkbox" aria-checked="' + on + '" tabindex="0"><span class="topic-check' + (on ? " on" : "") + '">' + (on ? "✓" : "") + '</span><span class="topic-name">' + esc(t.name) + "</span></div>";
    }).join("") || '<div class="modal-note">No topics yet. Add your own or generate new titles.</div>';
    $("topicCount").textContent = selectedCount() + " selected";
    $("toProducts").disabled = selectedCount() === 0;
    var button = $("newTitles");
    button.disabled = state.generatingTitles;
    button.innerHTML = state.generatingTitles ? '<span class="spin"></span> Generating…' : "↻ New titles";
    renderScreen();
  }
  function renderTopicsHint() {
    var host = $("topicsHintHost");
    if (!host) return;
    host.innerHTML = state.topicsHint
      ? '<div class="nt-hint"><div class="guide-bubble">✦ Don\'t like these titles? Click <b>↻ New titles</b> to add fresh ones — or type a prompt in the box to get titles about exactly what you want. Your existing topics are always kept.<div class="gb-actions"><button type="button" class="btn btn-pri btn-sm" data-w="topics-hint-close">Got it</button></div></div><div class="guide-anchor nt-arrow" style="position:relative">' + arrowSvg("upRight", "100%") + "</div></div>"
      : "";
  }
  function bindTopicInputs() {
    var prompt = $("titlePrompt");
    prompt.addEventListener("input", function () { state.titlePrompt = prompt.value; });
    prompt.addEventListener("keydown", function (event) { if (event.key === "Enter") generateTitles(); });
    $("customTopic").addEventListener("keydown", function (event) { if (event.key === "Enter") addCustomTopic(); });
    var grid = $("topicGrid");
    function toggleFrom(event) {
      var card = event.target.closest("[data-topic]");
      if (card) toggleTopic(card.getAttribute("data-topic"));
    }
    grid.addEventListener("click", toggleFrom);
    grid.addEventListener("keydown", function (event) {
      if (event.key === " " || event.key === "Enter") { event.preventDefault(); toggleFrom(event); }
    });
  }
  function toggleTopic(id) {
    if (state.selected[id]) { delete state.selected[id]; delete state.topicProducts[id]; }
    else state.selected[id] = true;
    renderTopicGrid();
  }
  function addCustomTopic() {
    var input = $("customTopic");
    var name = input.value.trim();
    if (!name) return;
    if (name.length < MIN_TOPIC_LENGTH) { App.toast("A topic needs at least " + MIN_TOPIC_LENGTH + " characters."); return; }
    if (state.topics.some(function (t) { return t.name.toLowerCase() === name.toLowerCase(); })) { App.toast("That topic is already in the list."); return; }
    var topic = { id: uid(), name: name };
    state.topics.push(topic);
    state.selected[topic.id] = true;
    input.value = "";
    renderTopicGrid();
  }
  function generateTitles() {
    if (state.generatingTitles) return;
    state.generatingTitles = true;
    renderTopicGrid();
    App.api("POST", "/store-intelligence/topics/generate", { body: state.titlePrompt.trim() ? { reference: state.titlePrompt.trim() } : {} })
      .then(function (data) {
        var added = 0;
        (data.blogTopics || []).forEach(function (raw) {
          state.topics.push({ id: uid(), name: raw.title });
          added += 1;
        });
        App.toast(added ? added + " new title" + (added > 1 ? "s" : "") + " added" : "No new titles were returned. Try again.");
        return refreshPlan();
      })
      .catch(function (err) { if (!handleLimitError(err, 1)) App.toast(err.message); })
      .finally(function () { state.generatingTitles = false; renderTopicGrid(); });
  }

  /* ---------- product step ---------- */
  function productsHtml() {
    return '<div class="cardhost open"><div class="card"><div class="cardtop"><button type="button" class="btn btn-gho btn-sm" data-w="topics">← Back to Topics</button><h3>Select Products (max 2 per topic)</h3></div>' +
      '<div class="sub">Step 2 of 3 — Optional: attach up to 2 products to each blog.</div>' +
      '<div class="pp-hintbar"><span class="pp-step"><span class="pp-stepnum">1</span> Pick a topic on the left</span><span class="pp-step"><span class="pp-stepnum">2</span> Tap products to attach (max 2)</span><span class="pp-step"><span class="pp-stepnum">3</span> Hit Generate when you\'re done</span></div>' +
      '<div class="pp-why"><span>💡</span><span><b>Why select products?</b> We place the product links inside your blog content — so readers can click straight through from the blog to buy them in your store.</span></div>' +
      '<div class="pp-layout"><div class="pp-topics" id="ppTopics"></div><div class="pp-products"><div class="pp-collections" id="ppCollections" hidden></div>' +
      '<div class="product-search-box"><span class="search-icon">🔍</span><input id="ppSearch" type="text" placeholder="Search products…" value="' + esc(state.productSearch) + '"><span id="ppSpin"></span></div><div id="ppGridHost" style="display:contents"></div></div></div>' +
      '<div class="wiz-foot"><span class="muted">' + selectedCount() + ' topics configured</span><button type="button" class="btn btn-pri" data-w="save-generate">Save &amp; Generate Blogs →</button></div></div></div>';
  }
  function renderProductTopics() {
    var host = $("ppTopics");
    if (!host) return;
    host.innerHTML = selectedTopics().map(function (topic) {
      var chosen = state.topicProducts[topic.id] || [];
      var thumbs = chosen.map(function (id) {
        var product = state.productCache[id];
        if (!product) return "";
        return product.image ? '<img src="' + esc(product.image) + '" alt="' + esc(product.title) + '">' : '<span class="ppt-chip">' + esc(product.title) + "</span>";
      }).join("");
      return '<div class="pp-topic' + (state.activeTopic === topic.id ? " active" : "") + '" data-pick-topic="' + esc(topic.id) + '"><div class="ppt-name">' + esc(topic.name) + '</div><div class="ppt-count">' +
        (chosen.length ? '<span class="' + (chosen.length === MAX_PRODUCTS_PER_TOPIC ? "done" : "") + '">' + chosen.length + "/2 products" + (chosen.length === MAX_PRODUCTS_PER_TOPIC ? " ✓" : "") + "</span>" : "No products yet") +
        "</div>" + (thumbs ? '<div class="ppt-thumbs">' + thumbs + "</div>" : "") + "</div>";
    }).join("");
  }
  function renderCollectionChips() {
    var host = $("ppCollections");
    if (!host) return;
    host.hidden = state.pickerCollections.length === 0;
    host.innerHTML = '<span class="ppc-label">Collection:</span><div class="pp-colrow"><div class="chip' + (!state.pickerCollection ? " sel" : "") + '" data-collection="">All products</div>' +
      state.pickerCollections.map(function (c) {
        return '<div class="chip' + (state.pickerCollection === c.id ? " sel" : "") + '" data-collection="' + esc(c.id) + '">' + esc(c.title) + "</div>";
      }).join("") + "</div>";
  }
  function renderProductGrid() {
    var host = $("ppGridHost");
    if (!host) return;
    $("ppSpin").innerHTML = state.searching ? '<span class="loading-spinner spin"></span>' : "";
    if (!state.productResults.length) {
      host.innerHTML = state.searching ? "" : '<div class="pp-empty">No products found.<br>Try a different search — or just skip this step, products are optional.</div>';
      return;
    }
    var chosen = state.topicProducts[state.activeTopic] || [];
    host.innerHTML = '<div class="pp-grid">' + state.productResults.map(function (p) {
      var on = chosen.indexOf(p.id) !== -1;
      return '<div class="pp-card' + (on ? " sel" : "") + '" data-product="' + esc(p.id) + '">' + (on ? '<span class="ppc-tick">✓</span>' : "") +
        (p.image ? '<img src="' + esc(p.image) + '" alt="' + esc(p.title) + '">' : '<div class="ppc-noimg">No image</div>') +
        '<div class="ppc-body"><div class="ppc-name">' + esc(p.title) + '</div><div class="ppc-price">' + esc(p.price) + " " + esc(p.currency) + "</div></div></div>";
    }).join("") + "</div>";
  }
  var productRequest = 0;
  function loadProducts() {
    var id = ++productRequest;
    state.searching = true;
    renderProductGrid();
    App.api("GET", "/shopify/products", { params: { search: state.productSearch, collection: state.pickerCollection } })
      .then(function (products) {
        if (id !== productRequest) return;
        state.productResults = products || [];
        state.productResults.forEach(function (p) { state.productCache[p.id] = p; });
      })
      .catch(function (err) { if (id === productRequest) App.toast(err.message); })
      .finally(function () {
        if (id !== productRequest) return;
        state.searching = false;
        renderProductGrid();
        renderProductTopics();
      });
  }
  var productTimer;
  function bindProductSearch() {
    var input = $("ppSearch");
    input.addEventListener("input", function () {
      state.productSearch = input.value;
      clearTimeout(productTimer);
      productTimer = setTimeout(loadProducts, 300);
    });
  }
  function goToProducts() {
    if (!selectedCount()) { App.toast("Select at least one topic first."); return; }
    if (!hasArticlesFor(selectedCount())) return;
    var first = selectedTopics()[0];
    if (!state.selected[state.activeTopic]) state.activeTopic = first.id;
    state.wizardView = "products";
    state.productSearch = "";
    renderWizard();
    loadProducts();
    if (!state.pickerCollections.length) {
      App.api("GET", "/shopify/collections").then(function (data) {
        state.pickerCollections = (data.collections || []).map(function (c) { return { id: c.id, title: c.title }; });
        renderCollectionChips();
      }).catch(function () {});
    }
  }
  function toggleProduct(productId) {
    var topicId = state.activeTopic;
    if (!topicId) return;
    var chosen = state.topicProducts[topicId] || [];
    var index = chosen.indexOf(productId);
    if (index !== -1) chosen.splice(index, 1);
    else if (chosen.length >= MAX_PRODUCTS_PER_TOPIC) { App.toast("Maximum 2 products per topic"); return; }
    else chosen.push(productId);
    state.topicProducts[topicId] = chosen;
    renderProductGrid();
    renderProductTopics();
  }
  function saveSelection() {
    try {
      localStorage.setItem(SAVED_SELECTION_KEY, JSON.stringify({
        items: selectedTopics().map(function (t) { return { name: t.name, products: state.topicProducts[t.id] || [] }; }),
        savedAt: Date.now(),
      }));
    } catch (e) { /* the selection still works for this visit */ }
  }
  function restoreSelection() {
    try {
      var saved = JSON.parse(localStorage.getItem(SAVED_SELECTION_KEY) || "{}");
      (saved.items || []).forEach(function (item) {
        var match = state.topics.filter(function (t) { return t.name === item.name; })[0];
        if (match && Array.isArray(item.products)) state.topicProducts[match.id] = item.products.slice(0, MAX_PRODUCTS_PER_TOPIC);
      });
    } catch (e) { /* ignore malformed saved data */ }
  }

  /* ---------- wizard click routing ---------- */
  document.addEventListener("click", function (event) {
    if (!$("overlayHost").contains(event.target)) return;
    var topicCard = event.target.closest("[data-pick-topic]");
    if (topicCard) {
      state.activeTopic = topicCard.getAttribute("data-pick-topic");
      renderProductTopics();
      renderProductGrid();
      return;
    }
    var product = event.target.closest("[data-product]");
    if (product) { toggleProduct(product.getAttribute("data-product")); return; }
    var chip = event.target.closest("[data-collection]");
    if (chip) {
      state.pickerCollection = chip.getAttribute("data-collection");
      renderCollectionChips();
      loadProducts();
      return;
    }
    var target = event.target.closest("[data-w]");
    if (!target) return;
    switch (target.getAttribute("data-w")) {
      case "close": closeWizard(); break;
      case "home": state.wizardView = "home"; renderWizard(); break;
      case "topics":
        state.wizardView = "topics";
        if (!state.topicsHintShown) { state.topicsHint = true; state.topicsHintShown = true; }
        renderWizard();
        break;
      case "products": goToProducts(); break;
      case "blogs": closeWizard(); openBlogModal(); break;
      case "save-close": closeWizard(); App.toast("Ready to generate blogs"); break;
      case "tour-start": state.portalStep = "topics"; renderWizard(); break;
      case "tour-skip": state.portalStep = null; renderWizard(); break;
      case "tour-next": state.portalStep = PORTAL_TOUR[state.portalStep].next; renderWizard(); break;
      case "topics-hint": state.topicsHint = !state.topicsHint; renderTopicsHint(); break;
      case "topics-hint-close": state.topicsHint = false; renderTopicsHint(); break;
      case "new-titles": generateTitles(); break;
      case "add-topic": addCustomTopic(); break;
      case "to-products": goToProducts(); break;
      case "save-generate": saveSelection(); startGeneration(); break;
    }
  });

  /* ---------- blog modal + generation ---------- */
  var blogCards = [];
  function closeBlogModal() { $("blogHost").innerHTML = ""; blogCards = []; }
  function openBlogModal() {
    blogCards = [];
    $("blogHost").innerHTML = '<div class="ov open" style="align-items:flex-start;padding-top:20px"><div class="ov-bd"></div><div class="be-panel" role="dialog" aria-modal="true" aria-label="Blogs">' +
      '<div class="be-head"><h2><span class="be-dot"></span><span id="blogHeading"></span></h2><button type="button" class="abtn" id="blogClose">Close</button></div>' +
      '<div class="be-body" id="blogBody"></div><div class="be-foot" id="blogFoot" hidden><button type="button" class="abtn pub" id="publishAll">Publish all</button></div></div></div>';
    $("blogHost").querySelector(".ov-bd").addEventListener("click", closeBlogModal);
    $("blogClose").addEventListener("click", closeBlogModal);
    $("publishAll").addEventListener("click", publishAll);
    state.blogs.forEach(appendBlogCard);
    renderBlogStatus();
  }
  function appendBlogCard(entry) {
    var body = $("blogBody");
    if (!body) return;
    var card = App.editorCard(entry.blog, { initialState: entry.state || "none", warning: entry.warning, onChange: function (next) { entry.state = next; } });
    blogCards.push(card);
    var wait = $("blogWait");
    if (wait) body.insertBefore(card, wait); else body.appendChild(card);
  }
  function renderBlogStatus() {
    var body = $("blogBody");
    if (!body) return;
    $("blogHeading").textContent = state.generating ? "Generating…" : "Blogs";
    $("blogFoot").hidden = state.blogs.length === 0;
    var wait = $("blogWait");
    if (state.generating && !wait) {
      wait = document.createElement("div");
      wait.id = "blogWait";
      wait.className = "be-wait";
      wait.innerHTML = '<span class="spin"></span> Writing your blog. This can take a minute or two…';
      body.appendChild(wait);
    } else if (!state.generating && wait) wait.remove();
    var empty = $("blogEmpty");
    if (!state.blogs.length && !state.generating && !empty) {
      empty = document.createElement("div");
      empty.id = "blogEmpty";
      empty.className = "be-empty";
      empty.textContent = "No blogs yet in this visit. Generate from the wizard, or open your saved drafts from the sidebar.";
      body.appendChild(empty);
    } else if ((state.blogs.length || state.generating) && empty) empty.remove();
  }
  function addGenerated(result) {
    var entry = { blog: result.blog, warning: result.warning, state: result.alreadyPublished ? "pub" : "none" };
    state.blogs.push(entry);
    appendBlogCard(entry);
    renderBlogStatus();
    if (result.warning) App.toast(result.warning);
  }
  function publishAll() {
    var button = $("publishAll");
    button.disabled = true;
    var cards = blogCards.filter(function (card) { return !card.isPublished(); });
    var published = 0;
    cards.reduce(function (chain, card) {
      return chain.then(function () { return card.publish(); }).then(function (ok) { if (ok) published += 1; });
    }, Promise.resolve()).then(function () {
      button.disabled = false;
      App.toast(published + " of " + cards.length + " blogs published");
    });
  }
  function startGeneration() {
    var topics = selectedTopics();
    if (!topics.length) { App.toast("Select topics first (tap preview)"); return; }
    if (state.generating) { App.toast("Blogs are already being generated."); return; }
    if (!hasArticlesFor(topics.length)) return;
    closeWizard();
    state.blogs = [];
    state.generating = true;
    openBlogModal();
    var done = 0;
    var stopped = false;
    topics.reduce(function (chain, topic) {
      return chain.then(function () {
        if (stopped) return null;
        return App.api("POST", "/blog/generate", { body: { topic: topic.name, products: state.topicProducts[topic.id] || [] } })
          .then(function (result) { done += 1; addGenerated(result); })
          .catch(function (err) {
            if (handleLimitError(err, 1)) { stopped = true; return; }
            App.toast('Error generating "' + topic.name + '": ' + err.message);
          });
      });
    }, Promise.resolve()).then(function () {
      state.generating = false;
      renderBlogStatus();
      App.toast(done + " of " + topics.length + " blogs generated");
      return refreshPlan();
    });
  }
  function generateCampaign() {
    var c = state.campaign;
    if (state.generating) { App.toast("Blogs are already being generated."); return; }
    if (!c.competitorUrl) { App.toast("Please select a competitor first."); return; }
    if (!c.calendar.type || !c.calendar.name) { App.toast("Please choose a calendar event first."); return; }
    if (!hasArticlesFor(1)) return;
    state.blogs = [];
    state.generating = true;
    openBlogModal();
    App.api("POST", "/blog/generate-campaign", {
      body: {
        collections: c.collections, products: c.products, competitorUrl: c.competitorUrl, calendar: c.calendar,
        keywords: { shortTail: c.shortTail, longTail: c.longTail },
      },
    }).then(function (result) {
      addGenerated(result);
      App.toast("Campaign blog generated!");
      return refreshPlan();
    }).catch(function (err) {
      if (!handleLimitError(err, 1)) App.toast(err.message);
    }).finally(function () {
      state.generating = false;
      renderBlogStatus();
    });
  }

  /* ---------- campaign modals ---------- */
  function closeModal() { $("modalHost").innerHTML = ""; }
  function modalShell(title, sub, bodyHtml, footHtml) {
    return '<div class="ov open"><div class="ov-bd" data-m="close"></div><button type="button" class="wiz-x" data-m="close" aria-label="Close">×</button><div class="cardhost open" style="max-width:700px"><div class="card"><div class="cardtop"><h3>' + title + '</h3></div><div class="sub">' + sub + "</div>" + bodyHtml + '<div class="wiz-foot">' + footHtml + "</div></div></div></div>";
  }
  function bindClose(host) {
    host.querySelectorAll('[data-m="close"]').forEach(function (el) { el.addEventListener("click", closeModal); });
  }
  function afterCampaignChange() { closeModal(); renderFoot(); }

  function openCollections() {
    var chosen = state.campaign.collections.slice();
    var host = $("modalHost");
    host.innerHTML = modalShell("Select up to 2 Collections", "Choose collections for your campaign (optional)",
      '<div id="colBody"><div class="modal-note"><span class="spin"></span> Loading collections…</div></div>',
      '<span class="muted" id="colCount"></span><button type="button" class="btn btn-pri" id="colSave">Save</button>');
    bindClose(host);
    var items = [];
    function draw() {
      $("colCount").textContent = chosen.length + " / 2 selected";
      $("colBody").innerHTML = items.length ? '<div class="col-grid">' + items.map(function (c) {
        var on = chosen.indexOf(c.id) !== -1;
        return '<div class="prod-card col-card' + (on ? " sel" : "") + '" data-col="' + esc(c.id) + '">' + (c.image ? '<img src="' + esc(c.image) + '" alt="' + esc(c.title) + '">' : '<div class="col-noimg">No image</div>') +
          '<div class="prod-name">' + esc(c.title) + '</div><div class="prod-price">' + esc(c.productsCount) + " products</div>" + (on ? '<div class="campaign-tag">✓ Selected</div>' : "") + "</div>";
      }).join("") + "</div>" : '<div class="modal-note">No collections found in your store.</div>';
    }
    App.api("GET", "/shopify/collections").then(function (data) { items = data.collections || []; if ($("colBody")) draw(); })
      .catch(function (err) { if ($("colBody")) $("colBody").innerHTML = '<div class="modal-note">' + esc(err.message) + "</div>"; });
    $("colCount").textContent = chosen.length + " / 2 selected";
    $("colBody").addEventListener("click", function (event) {
      var card = event.target.closest("[data-col]");
      if (!card) return;
      var id = card.getAttribute("data-col");
      var index = chosen.indexOf(id);
      if (index !== -1) chosen.splice(index, 1);
      else if (chosen.length < 2) chosen.push(id);
      else { App.toast("You can select up to 2 collections."); return; }
      draw();
    });
    $("colSave").addEventListener("click", function () { state.campaign.collections = chosen; afterCampaignChange(); });
  }

  function openProducts() {
    var MAX = 2;
    var chosen = state.campaign.products.slice();
    var scope = state.campaign.collections;
    var host = $("modalHost");
    var products = [];
    var loading = true;
    var query = "";
    var request = 0;
    host.innerHTML = '<div class="pm-ov"><div class="pm-bd" data-m="close"></div><div class="pm-card" role="dialog" aria-modal="true" aria-label="Select products"><div class="pm-head"><span class="pm-title">Select Products</span><span class="pm-count-pill" id="pmPill"></span><button type="button" class="pm-x" data-m="close" aria-label="Close">✕</button></div>' +
      '<div class="pm-body"><div class="pm-scope">' + (scope.length
        ? 'Showing products from <span class="pm-chip">' + scope.length + " selected collection" + (scope.length > 1 ? "s" : "") + "</span>"
        : 'Showing <span class="pm-chip">All products</span><span>— pick Collections first to narrow this down</span>') + "</div>" +
      '<div class="pm-search"><span class="pm-ic">🔍</span><input id="pmSearch" type="text" placeholder="Search products…"><span id="pmSpin"></span></div><div id="pmList" style="display:contents"></div></div>' +
      '<div class="pm-foot"><span class="pm-selinfo" id="pmInfo"></span><button type="button" class="pm-btn gho" data-m="close">Cancel</button><button type="button" class="pm-btn pri" id="pmSave">Save selection</button></div></div></div>';
    bindClose(host);
    function draw() {
      $("pmPill").textContent = chosen.length + " / " + MAX + " selected";
      $("pmInfo").innerHTML = "<b>" + chosen.length + "</b> of <b>" + MAX + "</b> products selected";
      $("pmSpin").innerHTML = loading ? '<span class="pm-spin"></span>' : "";
      var list = $("pmList");
      if (loading && !products.length) { list.innerHTML = '<div class="pm-empty"><span class="pm-spin"></span>Loading products…</div>'; return; }
      if (!products.length) { list.innerHTML = '<div class="pm-empty"><span class="pm-emoji">🛍️</span><span>No products found. Try a different search.</span></div>'; return; }
      list.innerHTML = '<div class="pm-grid">' + products.map(function (p) {
        var on = chosen.indexOf(p.id) !== -1;
        return '<div class="pm-prod' + (on ? " sel" : "") + '" data-prod="' + esc(p.id) + '">' + (on ? '<span class="pm-tick">✓</span>' : "") +
          (p.image ? '<img src="' + esc(p.image) + '" alt="' + esc(p.title) + '">' : '<div class="pm-noimg">No image</div>') +
          '<div class="pm-pbody"><div class="pm-pname">' + esc(p.title) + '</div><div class="pm-pprice">' + esc(p.price) + " " + esc(p.currency) + "</div></div></div>";
      }).join("") + "</div>";
    }
    function load() {
      var id = ++request;
      loading = true;
      draw();
      var calls = scope.length
        ? scope.map(function (col) { return App.api("GET", "/shopify/products", { params: { collection: col, search: query } }).catch(function () { return []; }); })
        : [App.api("GET", "/shopify/products", { params: { search: query } })];
      Promise.all(calls).then(function (results) {
        if (id !== request || !$("pmList")) return;
        var seen = {};
        products = [];
        results.forEach(function (rows) {
          (rows || []).forEach(function (p) { if (!seen[p.id]) { seen[p.id] = true; products.push(p); } });
        });
      }).catch(function (err) { App.toast(err.message); }).finally(function () {
        if (id !== request || !$("pmList")) return;
        loading = false;
        draw();
      });
    }
    var timer;
    $("pmSearch").addEventListener("input", function (event) {
      query = event.target.value;
      clearTimeout(timer);
      timer = setTimeout(load, 300);
    });
    $("pmList").addEventListener("click", function (event) {
      var card = event.target.closest("[data-prod]");
      if (!card) return;
      var id = card.getAttribute("data-prod");
      var index = chosen.indexOf(id);
      if (index !== -1) chosen.splice(index, 1);
      else if (chosen.length < MAX) chosen.push(id);
      else { App.toast("You can select up to " + MAX + " products."); return; }
      draw();
    });
    $("pmSave").addEventListener("click", function () { state.campaign.products = chosen; afterCampaignChange(); });
    load();
  }

  function openCompetitor(comp) {
    var host = $("modalHost");
    function list(items, mark) {
      return (items || []).map(function (item) { return '<div class="cd-item"><span class="cd-dot">' + mark + "</span><span>" + esc(item) + "</span></div>"; }).join("");
    }
    var site = /^https?:\/\//i.test(comp.website || "") ? comp.website : comp.website ? "https://" + comp.website : "";
    function draw() {
      var on = !!comp.website && state.campaign.competitorUrl === comp.website;
      host.innerHTML = '<div class="cd-ov"><div class="cd-bd" data-m="close"></div><div class="cd-card" role="dialog" aria-modal="true" aria-label="Competitor details"><div class="cd-head"><div class="cd-avatar">' + esc((comp.name || "?").trim().charAt(0).toUpperCase()) + '</div><div class="cd-headtxt"><div class="cd-name">' + esc(comp.name) + "</div>" +
        (site ? '<a class="cd-site" href="' + esc(site) + '" target="_blank" rel="noopener noreferrer">🔗 ' + esc(comp.website) + "</a>" : "") + "</div>" +
        (on ? '<span class="cd-selpill">✓ In campaign</span>' : "") + '<button type="button" class="cd-x" data-m="close" aria-label="Close">✕</button></div>' +
        '<div class="cd-body"><div><div class="cd-sec-label">About</div><div class="cd-desc">' + esc(comp.description) + '</div></div><div class="cd-cols"><div class="cd-col good"><div class="cd-col-title">💪 Strengths</div>' + list(comp.strengths, "✓") + '</div><div class="cd-col bad"><div class="cd-col-title">⚠️ Weaknesses</div>' + list(comp.weaknesses, "!") + "</div></div></div>" +
        '<div class="cd-foot"><div class="cd-use' + (on ? " on" : "") + '" id="cdUse" role="button" tabindex="0"><span class="cd-check">' + (on ? "✓" : "") + "</span>" + (on ? "Selected for the campaign" : "Use this competitor for the campaign") + '</div><button type="button" class="cd-btn" data-m="close">Done</button></div></div></div>';
      bindClose(host);
      host.querySelectorAll('[data-m="close"]').forEach(function (el) { el.addEventListener("click", renderFoot); });
      App.onActivate($("cdUse"), function () {
        state.campaign.competitorUrl = on ? "" : site;
        comp.website = on ? comp.website : site;
        draw();
      });
    }
    draw();
  }

  function openCalendar(type) {
    var TITLES = { seasonal: "Seasonal Event", cultural: "🌍 Cultural Event", retail: "🛍️ Retail Event", experiential: "🎯 Experiential Event" };
    var current = state.campaign.calendar;
    var markets = (state.store && state.store.primaryMarket) || [];
    if (!Array.isArray(markets)) markets = [markets];
    markets = markets.filter(Boolean);
    var country = current.type === type && current.country ? current.country : markets[0] || "";
    var chosen = current.type === type ? current.name : "";
    var events = [];
    var loading = false;
    var request = 0;
    var host = $("modalHost");
    host.innerHTML = modalShell(TITLES[type], "Choose a country from your markets, then select a " + type + " event.",
      '<div style="font-size:12px;color:#8ea0cc;margin-bottom:8px">Your Markets:</div><div id="calCountries"></div><div id="calEvents"></div>',
      '<span class="muted" id="calNote"></span><button type="button" class="btn btn-pri" id="calSave">Save</button>');
    bindClose(host);
    function draw() {
      $("calCountries").innerHTML = markets.length
        ? '<div class="country-buttons">' + markets.map(function (m) { return '<button type="button" class="country-btn' + (m === country ? " active" : "") + '" data-country="' + esc(m) + '">' + esc(m) + "</button>"; }).join("") + "</div>"
        : '<div class="no-markets">No markets configured. Use Edit next to Market in the sidebar to add one.</div>';
      var eventsHost = $("calEvents");
      if (!country) eventsHost.innerHTML = "";
      else if (loading) eventsHost.innerHTML = '<div class="modal-note"><span class="spin"></span> Loading events for ' + esc(country) + "…</div>";
      else eventsHost.innerHTML = '<div class="selected-country-label">📍 Selected: <strong>' + esc(country) + "</strong></div>" + (events.length
        ? '<div class="chips event-chips">' + events.map(function (e, i) { return '<div class="chip' + (e === chosen ? " sel" : "") + '" data-event="' + i + '">' + esc(e) + "</div>"; }).join("") + "</div>"
        : '<div class="modal-note">No ' + type + " events found for " + esc(country) + "</div>");
      $("calNote").textContent = chosen ? "Selected: " + chosen : "No event selected";
      $("calSave").disabled = !chosen || !country;
    }
    function load() {
      if (!country) { draw(); return; }
      var id = ++request;
      loading = true;
      draw();
      App.api("GET", "/country-events/" + encodeURIComponent(country)).then(function (data) {
        if (id !== request) return;
        events = data[type] || [];
      }).catch(function (err) {
        if (id === request) { events = []; App.toast(err.message); }
      }).finally(function () {
        if (id !== request || !$("calEvents")) return;
        loading = false;
        draw();
      });
    }
    $("calCountries").addEventListener("click", function (event) {
      var button = event.target.closest("[data-country]");
      if (!button) return;
      country = button.getAttribute("data-country");
      chosen = "";
      load();
    });
    $("calEvents").addEventListener("click", function (event) {
      var chip = event.target.closest("[data-event]");
      if (!chip) return;
      chosen = events[Number(chip.getAttribute("data-event"))];
      draw();
    });
    $("calSave").addEventListener("click", function () {
      state.campaign.calendar = { type: type, name: chosen, country: country };
      afterCampaignChange();
    });
    load();
  }

  function openKeywords(field) {
    var short = field === "shortTail";
    var MAX = short ? 20 : 50;
    var available = (state.store && (short ? state.store.shortTailKeywords : state.store.longTailKeywords)) || [];
    var chosen = state.campaign[field].slice();
    var host = $("modalHost");
    host.innerHTML = modalShell(short ? "Short‑tail Keywords" : "Long‑tail Keywords", "Select keywords from the list or add your own (max " + MAX + ")",
      '<div class="chips" id="kwAvailable" style="margin-bottom:12px"></div><div class="field" style="margin-top:12px"><input id="kwInput" maxlength="100" placeholder="Add your own keyword + Enter"><button type="button" class="btn btn-gho" id="kwAdd">Add</button></div><div id="kwCustom" style="margin-top:8px"></div>',
      '<span class="muted" id="kwCount"></span><button type="button" class="btn btn-pri" id="kwSave">Save</button>');
    bindClose(host);
    function draw() {
      $("kwAvailable").innerHTML = available.map(function (kw) {
        return '<div class="chip' + (chosen.indexOf(kw) !== -1 ? " sel" : "") + '" data-kw="' + esc(kw) + '">' + esc(kw) + "</div>";
      }).join("");
      var custom = chosen.filter(function (kw) { return available.indexOf(kw) === -1; });
      $("kwCustom").innerHTML = custom.length ? '<div class="muted" style="font-size:12px">Custom added:</div><div class="chips">' + custom.map(function (kw) {
        return '<div class="chip sel" data-kw="' + esc(kw) + '">' + esc(kw) + " ✕</div>";
      }).join("") + "</div>" : "";
      $("kwCount").textContent = chosen.length + " / " + MAX + " selected";
    }
    function toggle(kw) {
      var index = chosen.indexOf(kw);
      if (index !== -1) chosen.splice(index, 1);
      else if (chosen.length < MAX) chosen.push(kw);
      else App.toast("You can select up to " + MAX + " keywords.");
      draw();
    }
    function add() {
      var input = $("kwInput");
      var value = input.value.trim();
      if (!value) return;
      if (chosen.indexOf(value) === -1) toggle(value);
      input.value = "";
    }
    host.querySelector(".card").addEventListener("click", function (event) {
      var chip = event.target.closest("[data-kw]");
      if (chip) toggle(chip.getAttribute("data-kw"));
    });
    $("kwAdd").addEventListener("click", add);
    $("kwInput").addEventListener("keydown", function (event) { if (event.key === "Enter") add(); });
    $("kwSave").addEventListener("click", function () { state.campaign[field] = chosen; afterCampaignChange(); });
    draw();
  }

  function showPlanLimit(needed, message) {
    var host = $("modalHost");
    var left = remaining("articles");
    var planName = state.plan && state.plan.planId ? state.plan.planId.name : "No active plan";
    host.innerHTML = '<div class="ov open" style="z-index:1300"><div class="ov-bd" data-m="close"></div><div class="blogwrap" style="max-width:500px" role="dialog" aria-modal="true" aria-label="Plan limit reached"><div class="blog-head"><h2>Plan Limit Reached</h2><button type="button" class="abtn" data-m="close" aria-label="Close">✕</button></div><div class="blog-body"><div class="limit-card"><div class="limit-icon">📊</div>' +
      "<h3>" + esc(message || (state.plan ? "You've reached your article limit" : "You don't have an active plan")) + "</h3>" +
      "<p>You have <strong>" + left + "</strong> articles remaining and need <strong>" + needed + "</strong> for this generation.</p>" +
      '<div class="limit-box"><div class="limit-row"><span>Remaining articles</span><b>' + left + '</b></div><div class="limit-row"><span>Articles needed</span><b>' + needed + '</b></div><div class="limit-row"><span>Plan</span><b>' + esc(planName) + "</b></div></div>" +
      '<div class="limit-actions"><button type="button" class="btn btn-gho" data-m="close">Cancel</button><a class="btn btn-pri" href="/billings" style="text-decoration:none">View Plans</a></div></div></div></div></div>';
    bindClose(host);
  }

  /* ---------- start ---------- */
  function seedTopics(store) {
    state.topics = ((store && store.blogTopics) || []).filter(function (t) { return t.title; }).map(function (t) {
      return { id: uid(), name: t.title };
    });
    if (state.topics.length) state.selected[state.topics[0].id] = true;
    restoreSelection();
  }

  renderKnobs();
  App.onActivate($("previewKnob"), openWizard);
  App.onActivate($("generatorKnob"), function () {
    if (!state.store) { App.toast("Store data not loaded yet"); return; }
    startGeneration();
  });
  App.onActivate($("campaignKnob"), generateCampaign);
  $("topHelp").addEventListener("click", function (event) { event.stopPropagation(); toggleTour(0, 2); });
  $("bottomHelp").addEventListener("click", function (event) { event.stopPropagation(); toggleTour(3, KNOB_TOUR.length - 1); });
  document.addEventListener("markets-updated", function (event) {
    if (state.store) { state.store.primaryMarket = event.detail; renderScreen(); }
  });

  App.ready.then(function () {
    if (!App.token()) { App.hideLoader(); return; }
    Promise.all([
      App.store().catch(function (err) { App.toast(err.message || "Error loading store data"); return null; }),
      App.plan().catch(function () { return null; }),
    ]).then(function (results) {
      state.store = results[0];
      state.plan = results[1];
      seedTopics(state.store);
      renderScreen();
      renderFoot();
      App.hideLoader();
      positionBeam($("knobRow").querySelector('[data-knob="' + state.selectedKnob + '"]'));
      state.knobStep = 0;
      state.knobStop = KNOB_TOUR.length - 1;
      renderKnobTour();
    });
  });
})();
