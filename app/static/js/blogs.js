/* Content Hub, Drafts, Scheduled and Published pages. */
(function () {
  "use strict";
  var esc = App.esc;
  var root = document.getElementById("blogsPage");
  var kind = root.getAttribute("data-kind");
  var FIXED_STATUS = { draft: "COMPLETED", schedule: "SCHEDULED", publish: "PUBLISHED" };
  var state = { page: 1, limit: 10, search: "", status: FIXED_STATUS[kind] || "" };
  var requestId = 0;
  var blogs = {};

  function timeLeft(value) {
    var diff = new Date(value).getTime() - Date.now();
    if (diff < 0) return "Overdue";
    var days = Math.floor(diff / 86400000);
    var hours = Math.floor((diff % 86400000) / 3600000);
    var minutes = Math.floor((diff % 3600000) / 60000);
    if (days > 0) return days + "d " + hours + "h";
    return hours > 0 ? hours + "h " + minutes + "m" : minutes + "m";
  }
  function whenClass(value) {
    var diff = new Date(value).getTime() - Date.now();
    if (diff < 0) return "when-late";
    return diff < 86400000 ? "when-soon" : "when-ok";
  }

  function card(blog) {
    blogs[blog._id] = blog;
    var blogState = App.blogState(blog);
    var keywords = blog.keywords || [];
    var dateNote = "";
    if (blogState === "sched" && blog.scheduledFor) {
      dateNote = '<span class="' + whenClass(blog.scheduledFor) + '">⏰ ' + esc(App.formatDate(blog.scheduledFor)) + " · " + esc(timeLeft(blog.scheduledFor)) + "</span>";
    } else if (blogState === "pub" && blog.publishedAt) {
      dateNote = "<span>Published: " + esc(App.formatDate(blog.publishedAt)) + "</span>";
    } else if (blog.updatedAt) {
      dateNote = "<span>Updated: " + esc(App.formatDate(blog.updatedAt)) + "</span>";
    }
    return '<article class="blog-card"><div class="blog-main">' +
      '<div class="blog-tags">' + App.badgeHtml(blogState) + dateNote + "</div>" +
      "<h2>" + esc(blog.title) + "</h2>" +
      '<p class="excerpt">' + esc(blog.excerpt || blog.topic) + "</p>" +
      '<div class="blog-info"><span>Created: ' + esc(App.formatDate(blog.createdAt)) + "</span><span>" + esc(blog.estimatedReadingTime || "N/A") + "</span>" +
      (keywords.length ? "<span>🏷 " + esc(keywords.slice(0, 3).join(", ")) + (keywords.length > 3 ? " +" + (keywords.length - 3) : "") + "</span>" : "") + "</div>" +
      (blog.publishError ? '<div class="blog-error">' + esc(blog.publishError) + "</div>" : "") +
      '</div><div class="blog-actions">' +
      (blogState !== "pub" ? '<button type="button" class="abtn" data-edit="' + esc(blog._id) + '">Edit</button>' : "") +
      '<button type="button" class="abtn" data-copy="' + esc(blog._id) + '">Copy</button>' +
      '<button type="button" class="abtn" data-download="' + esc(blog._id) + '">Download</button>' +
      (blog.shopifyUrl ? '<a class="abtn pub" href="' + esc(blog.shopifyUrl) + '" target="_blank" rel="noopener noreferrer">View Live</a>' : "") +
      "</div></article>";
  }

  function pageNumbers(current, total) {
    var numbers = [];
    for (var i = 1; i <= total; i++) {
      if (i === 1 || i === total || Math.abs(i - current) <= 2) {
        if (numbers.length && i - numbers[numbers.length - 1] > 1) numbers.push(0);
        numbers.push(i);
      }
    }
    return numbers;
  }

  function renderPager(info) {
    var host = document.getElementById("pager");
    if (info.totalPages <= 1) { host.innerHTML = ""; return; }
    var first = (info.page - 1) * info.limit + 1;
    var last = Math.min(info.page * info.limit, info.total);
    var buttons = '<button type="button" data-page="' + (info.page - 1) + '"' + (info.hasPrev ? "" : " disabled") + ' aria-label="Previous page">‹</button>';
    pageNumbers(info.page, info.totalPages).forEach(function (n) {
      buttons += n === 0 ? "<button type=\"button\" disabled>…</button>"
        : '<button type="button" data-page="' + n + '"' + (n === info.page ? ' class="on" aria-current="page"' : "") + ">" + n + "</button>";
    });
    buttons += '<button type="button" data-page="' + (info.page + 1) + '"' + (info.hasNext ? "" : " disabled") + ' aria-label="Next page">›</button>';
    host.innerHTML = '<div class="pager"><span>Showing ' + first + " to " + last + " of " + info.total + '</span><div class="pager-btns">' + buttons + "</div></div>";
  }

  function renderStats(info, rows) {
    if (kind !== "publish") return;
    var host = document.getElementById("stats");
    host.hidden = false;
    host.innerHTML = '<div class="stat"><b>' + info.total + '</b><span>Total Published</span></div>' +
      '<div class="stat"><b>' + rows.length + '</b><span>On This Page</span></div>' +
      '<div class="stat"><b>' + rows.filter(function (b) { return b.shopifyUrl; }).length + "</b><span>Live on Shopify (this page)</span></div>";
  }

  function load() {
    var id = ++requestId;
    var list = document.getElementById("list");
    list.innerHTML = '<div class="state-box"><span class="spin big-spin"></span>Loading…</div>';
    App.api("GET", "/blog/all", { params: state }).then(function (result) {
      if (id !== requestId) return;
      var rows = result.data || [];
      var info = result.pagination;
      /* A delete or status change can leave us past the last page. */
      if (!rows.length && info.total > 0 && state.page > 1) { state.page = info.totalPages || 1; load(); return; }
      blogs = {};
      list.innerHTML = rows.length ? rows.map(card).join("")
        : '<div class="state-box"><h3>' + esc(root.getAttribute("data-empty")) + "</h3><p>" + esc(root.getAttribute("data-empty-hint")) + "</p></div>";
      renderPager(info);
      renderStats(info, rows);
    }).catch(function (err) {
      if (id !== requestId) return;
      list.innerHTML = '<div class="state-box"><h3>Could not load blogs</h3><p>' + esc(err.message) + "</p></div>";
      document.getElementById("pager").innerHTML = "";
    });
  }

  function closeEditor() {
    document.getElementById("editorHost").innerHTML = "";
    document.removeEventListener("keydown", onEscape);
    load();
  }
  function onEscape(event) { if (event.key === "Escape") closeEditor(); }

  function openEditor(blog) {
    var host = document.getElementById("editorHost");
    host.innerHTML = '<div class="ov open" style="align-items:flex-start;padding-top:20px"><div class="ov-bd"></div>' +
      '<div class="be-panel" role="dialog" aria-modal="true" aria-label="Edit blog"><div class="be-head"><h2><span class="be-dot"></span>Edit Blog</h2><button type="button" class="abtn" id="closeEditor">Close</button></div><div class="be-body"></div></div></div>';
    host.querySelector(".be-body").appendChild(App.editorCard(blog));
    host.querySelector(".ov-bd").addEventListener("click", closeEditor);
    host.querySelector("#closeEditor").addEventListener("click", closeEditor);
    document.addEventListener("keydown", onEscape);
  }

  document.getElementById("list").addEventListener("click", function (event) {
    var button = event.target.closest("[data-edit],[data-copy],[data-download]");
    if (!button) return;
    var edit = button.getAttribute("data-edit");
    var copy = button.getAttribute("data-copy");
    var download = button.getAttribute("data-download");
    if (edit) openEditor(blogs[edit]);
    else if (copy) App.copyText(blogs[copy].content || "");
    else if (download) App.downloadBlog(blogs[download].title, blogs[download].content || "", App.heroUrl(blogs[download]));
  });
  document.getElementById("pager").addEventListener("click", function (event) {
    var button = event.target.closest("[data-page]");
    if (button && !button.disabled) { state.page = Number(button.getAttribute("data-page")); load(); window.scrollTo(0, 0); }
  });
  var searchTimer;
  document.getElementById("search").addEventListener("input", function (event) {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () { state.search = event.target.value.trim(); state.page = 1; load(); }, 300);
  });
  document.getElementById("limit").addEventListener("change", function (event) {
    state.limit = Number(event.target.value); state.page = 1; load();
  });
  var filter = document.getElementById("statusFilter");
  if (filter) filter.addEventListener("change", function () { state.status = filter.value; state.page = 1; load(); });

  App.ready.then(function () {
    App.hideLoader();
    if (App.token()) load();
    else document.getElementById("list").innerHTML = '<div class="state-box"><h3>Not signed in</h3><p>Please open this app from your Shopify admin.</p></div>';
  });
})();
