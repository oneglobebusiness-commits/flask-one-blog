/* Shared by every page: login, API calls, toast, small helpers. */
(function () {
  "use strict";
  var TOKEN_KEY = "blog1_token";
  var App = (window.App = {});

  function readStore(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
  function writeStore(key, value) {
    try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch (e) {}
  }

  App.token = function () { return readStore(TOKEN_KEY); };
  App.setVisited = function () { writeStore("visited", "true"); };

  App.esc = function (value) {
    return String(value === null || value === undefined ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };

  var toastTimer;
  App.toast = function (message) {
    var el = document.getElementById("appToast");
    el.textContent = message;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.classList.remove("show"); }, 3200);
  };

  App.hideLoader = function () { document.getElementById("appLoader").classList.add("gone"); };

  App.showSessionProblem = function (message) {
    if (document.getElementById("sessionBanner")) return;
    var el = document.createElement("div");
    el.id = "sessionBanner";
    el.className = "session-banner";
    el.setAttribute("role", "alert");
    el.textContent = message || "Your session has ended. Please reopen the app from your Shopify admin.";
    document.body.appendChild(el);
  };

  App.api = function (method, path, options) {
    options = options || {};
    var url = "/api/v1" + path;
    if (options.params) {
      var query = new URLSearchParams();
      Object.keys(options.params).forEach(function (key) {
        var value = options.params[key];
        if (value !== undefined && value !== null && value !== "") query.set(key, value);
      });
      if (query.toString()) url += "?" + query.toString();
    }
    var headers = { Accept: "application/json" };
    var token = App.token();
    if (token) headers.Authorization = "Bearer " + token;
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, 290000);
    return fetch(url, {
      method: method,
      headers: headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    })
      .then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (data) {
          if (response.ok) return data;
          var err = new Error((data && data.message) || "The request failed.");
          err.status = response.status;
          err.data = data || {};
          if (response.status === 401 && !options.noSessionCheck) {
            writeStore(TOKEN_KEY, null);
            App.showSessionProblem();
          }
          throw err;
        });
      })
      .catch(function (err) {
        if (err.name === "AbortError") throw new Error("The request took too long. Please try again.");
        if (err instanceof TypeError) throw new Error("Could not reach the server.");
        throw err;
      })
      .finally(function () { clearTimeout(timer); });
  };

  /* A new Shopify token in the URL always wins, so opening a different store switches to it. */
  function login() {
    var url = new URL(window.location.href);
    var idToken = url.searchParams.get("id_token");
    if (!idToken) return Promise.resolve();
    return App.api("POST", "/auth/shopify", { body: { idToken: idToken }, noSessionCheck: true })
      .then(function (data) {
        writeStore(TOKEN_KEY, data.accessToken);
        url.searchParams.delete("id_token");
        window.history.replaceState({}, "", url.toString());
      })
      .catch(function (err) {
        writeStore(TOKEN_KEY, null);
        if (err.data && err.data.needsInstall && err.data.installUrl) {
          window.open(err.data.installUrl, "_top");
          return new Promise(function () {});
        }
        App.showSessionProblem("Could not sign in with Shopify. Please reopen the app from your Shopify admin.");
      });
  }

  App.ready = login().then(function () {
    if (!App.token() && document.querySelector(".app-side")) App.showSessionProblem("Please open this app from your Shopify admin to sign in.");
  });

  var storePromise = null;
  App.store = function () {
    if (!storePromise) {
      storePromise = App.ready.then(function () {
        if (!App.token()) throw new Error("Not signed in.");
        return App.api("POST", "/store-intelligence/analyze");
      });
      storePromise.catch(function () { storePromise = null; });
    }
    return storePromise;
  };

  App.plan = function () {
    return App.ready.then(function () {
      if (!App.token()) return null;
      return App.api("GET", "/user-subscription/me").catch(function (err) {
        if (err.status === 404) return null;
        throw err;
      });
    });
  };

  App.formatDate = function (value) {
    if (!value) return "";
    return new Date(value).toLocaleString("en-US", { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  };

  /* Value for <input type="datetime-local"> in the viewer's own time zone. */
  App.localInputValue = function (date) {
    var pad = function (n) { return String(n).padStart(2, "0"); };
    return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate()) + "T" + pad(date.getHours()) + ":" + pad(date.getMinutes());
  };

  App.onActivate = function (el, handler) {
    el.addEventListener("click", handler);
    el.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); handler(event); }
    });
  };

  document.addEventListener("DOMContentLoaded", function () {
    var back = document.getElementById("backBtn");
    if (back) back.addEventListener("click", function () { window.history.back(); });
  });
})();
