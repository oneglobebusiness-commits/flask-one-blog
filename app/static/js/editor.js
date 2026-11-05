/* Blog editor card, used by the dashboard and the blog list pages. */
(function () {
  "use strict";
  var esc = App.esc;
  var BADGES = {
    none: ["b-none", "Unsaved"], draft: ["b-draft", "Draft"], sched: ["b-sched", "Scheduled"],
    pub: ["b-pub", "Published ✓"], fail: ["b-fail", "Failed"],
  };

  App.blogState = function (blog) {
    if (blog.publishStatus === "PUBLISHED" || blog.status === "PUBLISHED") return "pub";
    if (blog.publishStatus === "SCHEDULED" || blog.status === "SCHEDULED") return "sched";
    if (blog.publishStatus === "FAILED") return "fail";
    return "draft";
  };
  App.badgeHtml = function (state) {
    var badge = BADGES[state] || BADGES.draft;
    return '<span class="badge ' + badge[0] + '">' + badge[1] + "</span>";
  };
  App.heroUrl = function (blog) {
    var hero = blog.heroImage || {};
    return hero.url || hero.shopifyUrl || "";
  };

  function absolute(url) { return url && url.charAt(0) === "/" ? window.location.origin + url : url; }

  App.downloadBlog = function (title, html, heroUrl) {
    var image = heroUrl ? '<img src="' + esc(absolute(heroUrl)) + '" alt="' + esc(title) + '" style="max-width:100%;border-radius:8px;">' : "";
    var page = '<!doctype html><html><head><meta charset="utf-8"><title>' + esc(title) +
      '</title><style>body{max-width:800px;margin:40px auto;padding:20px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;line-height:1.6;color:#333}img{max-width:100%;height:auto}</style></head><body><h1>' +
      esc(title) + "</h1>" + image + html + "</body></html>";
    var url = URL.createObjectURL(new Blob([page], { type: "text/html;charset=utf-8" }));
    var link = document.createElement("a");
    link.href = url;
    link.download = (title || "blog").replace(/[^a-z0-9]+/gi, "-").toLowerCase() + ".html";
    link.click();
    URL.revokeObjectURL(url);
    App.toast("Blog downloaded!");
  };

  App.copyText = function (html) {
    var text = new DOMParser().parseFromString(html, "text/html").body.textContent || "";
    return navigator.clipboard.writeText(text).then(
      function () { App.toast("Content copied to clipboard!"); },
      function () { App.toast("Your browser blocked copying."); }
    );
  };

  /* blog: API blog. opts.onChange(updatedState) runs after a save, schedule or publish. */
  App.editorCard = function (blog, opts) {
    opts = opts || {};
    var state = opts.initialState || App.blogState(blog);
    var card = document.createElement("div");
    card.className = "be-card";
    var hero = App.heroUrl(blog);
    var draftLabel = state === "sched" ? "Move to Drafts" : "Save Draft";
    var defaultWhen = blog.scheduledFor ? new Date(blog.scheduledFor) : new Date(Date.now() + 3600000);
    if (defaultWhen <= new Date()) defaultWhen = new Date(Date.now() + 3600000);

    card.innerHTML =
      (hero ? '<img class="be-hero" src="' + esc(hero) + '" alt="' + esc(blog.title) + '">' : "") +
      '<div class="be-top"><input class="be-title" value="' + esc(blog.title) + '" aria-label="Blog title"><span class="be-badge">' + App.badgeHtml(state) + "</span></div>" +
      '<div class="be-tools" role="toolbar" aria-label="Formatting">' +
      [["bold", "<b>B</b>"], ["italic", "<i>I</i>"], ["underline", "<u>U</u>"], ["h1", "H1"], ["h2", "H2"], ["h3", "H3"], ["p", "¶"], ["ul", "• List"], ["ol", "1. List"], ["link", "Link"]]
        .map(function (t) { return '<button type="button" class="abtn" data-format="' + t[0] + '">' + t[1] + "</button>"; }).join("") +
      "</div>" +
      '<div class="be-editor" contenteditable="true" role="textbox" aria-multiline="true" aria-label="Blog content"></div>' +
      (blog.topic ? '<div class="be-meta">Topic: ' + esc(blog.topic) + "</div>" : "") +
      (blog.scheduledFor && state === "sched" ? '<div class="be-alert info be-when">Currently scheduled for: ' + esc(App.formatDate(blog.scheduledFor)) + "</div>" : "") +
      (blog.publishError ? '<div class="be-alert err">' + esc(blog.publishError) + "</div>" : "") +
      (opts.warning ? '<div class="be-alert err">' + esc(opts.warning) + "</div>" : "") +
      '<div class="be-actions">' +
      '<button type="button" class="abtn" data-act="copy">Copy</button>' +
      '<button type="button" class="abtn" data-act="download">Download HTML</button>' +
      '<button type="button" class="abtn" data-act="draft">' + draftLabel + "</button>" +
      '<button type="button" class="abtn sch" data-act="schedule">' + (state === "sched" ? "Reschedule" : "Schedule") + "</button>" +
      '<button type="button" class="abtn pub" data-act="publish">Publish</button>' +
      '<div class="schbox" hidden><label for="when-' + esc(blog._id) + '">Publish at</label>' +
      '<input id="when-' + esc(blog._id) + '" type="datetime-local" min="' + App.localInputValue(new Date()) + '" value="' + App.localInputValue(defaultWhen) + '">' +
      '<button type="button" class="abtn sch" data-act="confirm">Set</button><button type="button" class="abtn" data-act="cancel">Cancel</button></div>' +
      "</div>";

    var editor = card.querySelector(".be-editor");
    editor.innerHTML = blog.content || ""; /* the server sanitises blog HTML */
    var titleInput = card.querySelector(".be-title");
    var schedule = card.querySelector(".schbox");
    var busy = false;

    function setBusy(value) {
      busy = value;
      card.querySelectorAll(".be-actions .abtn").forEach(function (b) {
        if (b.getAttribute("data-act") !== "copy" && b.getAttribute("data-act") !== "download") b.disabled = value || state === "pub";
      });
    }
    function setState(next) {
      state = next;
      card.querySelector(".be-badge").innerHTML = App.badgeHtml(next);
      var draft = card.querySelector('[data-act="draft"]');
      draft.textContent = next === "sched" ? "Move to Drafts" : "Save Draft";
      card.querySelector('[data-act="schedule"]').textContent = next === "sched" ? "Reschedule" : "Schedule";
      if (next === "pub") {
        titleInput.readOnly = true;
        editor.setAttribute("contenteditable", "false");
      }
      setBusy(false);
      if (opts.onChange) opts.onChange(next);
    }
    function edits() {
      var title = titleInput.value.trim();
      var content = editor.innerHTML;
      if (!title) { App.toast("Blog title is missing."); return null; }
      if (!editor.textContent.trim()) { App.toast("Content cannot be empty"); return null; }
      return { title: title, content: content };
    }

    function save() {
      var body = edits();
      if (!body || busy) return Promise.resolve(false);
      setBusy(true);
      return App.api("POST", "/blog/" + blog._id + "/draft", { body: body }).then(function () {
        setState("draft");
        App.toast("Saved to drafts");
        return true;
      }).catch(function (err) { setBusy(false); App.toast(err.message); return false; });
    }

    function publish() {
      var body = edits();
      if (!body || busy || state === "pub") return Promise.resolve(false);
      setBusy(true);
      return App.api("POST", "/publish/" + blog._id, { body: body }).then(function (data) {
        setState("pub");
        var url = data.data && data.data.shopify && data.data.shopify.url;
        if (url) {
          var link = document.createElement("a");
          link.className = "abtn";
          link.href = url;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.textContent = "View Live";
          card.querySelector(".be-actions").appendChild(link);
        }
        App.toast("Blog published successfully!");
        return true;
      }).catch(function (err) { setState("fail"); App.toast(err.message); return false; });
    }

    function confirmSchedule() {
      var body = edits();
      var value = schedule.querySelector("input").value;
      if (!body || busy) return;
      if (!value) { App.toast("Please select a date and time"); return; }
      var when = new Date(value);
      if (when <= new Date()) { App.toast("Please choose a future date and time."); return; }
      body.scheduledFor = when.toISOString();
      setBusy(true);
      App.api("POST", "/publish/" + blog._id + "/schedule", { body: body }).then(function () {
        schedule.hidden = true;
        var note = card.querySelector(".be-when");
        if (note) note.textContent = "Currently scheduled for: " + App.formatDate(when);
        setState("sched");
        App.toast("Scheduled for " + when.toLocaleString());
      }).catch(function (err) { setBusy(false); App.toast(err.message); });
    }

    card.querySelector(".be-tools").addEventListener("mousedown", function (event) { event.preventDefault(); });
    card.querySelector(".be-tools").addEventListener("click", function (event) {
      var button = event.target.closest("[data-format]");
      if (!button) return;
      var format = button.getAttribute("data-format");
      editor.focus();
      if (format === "bold" || format === "italic" || format === "underline") document.execCommand(format);
      else if (format === "ul") document.execCommand("insertUnorderedList");
      else if (format === "ol") document.execCommand("insertOrderedList");
      else if (format === "link") {
        var url = window.prompt("Link address (https://…)");
        if (url && /^(https?:|mailto:)/i.test(url)) document.execCommand("createLink", false, url);
        else if (url) App.toast("Links must start with https:// or mailto:");
      } else document.execCommand("formatBlock", false, "<" + format + ">");
    });
    card.querySelector(".be-actions").addEventListener("click", function (event) {
      var button = event.target.closest("[data-act]");
      if (!button || button.disabled) return;
      var action = button.getAttribute("data-act");
      if (action === "copy") App.copyText(editor.innerHTML);
      else if (action === "download") App.downloadBlog(titleInput.value, editor.innerHTML, hero);
      else if (action === "draft") save();
      else if (action === "publish") publish();
      else if (action === "schedule") schedule.hidden = false;
      else if (action === "cancel") schedule.hidden = true;
      else if (action === "confirm") confirmSchedule();
    });
    if (state === "pub") setState("pub");
    card.publish = publish;
    card.isPublished = function () { return state === "pub"; };
    return card;
  };
})();
