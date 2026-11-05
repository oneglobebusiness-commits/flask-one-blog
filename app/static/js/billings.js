(function () {
  "use strict";
  var esc = App.esc;

  function cycle(days) {
    if (days === 30) return "month";
    if (days === 90) return "quarter";
    if (days === 365) return "year";
    return days === 1 ? "day" : days + " days";
  }
  function plural(count, word) { return count + " " + word + (count === 1 ? "" : "s"); }
  function feature(on, text) {
    return "<li><span class=\"" + (on ? "y" : "n") + "\">" + (on ? "✓" : "✗") + "</span>" + esc(text) + "</li>";
  }

  function renderCurrent(sub) {
    var host = document.getElementById("current");
    if (!sub) {
      host.innerHTML = '<div class="current-plan"><div><h3>No active plan</h3><p>Your plan has ended. Choose a plan below to keep generating blogs.</p></div></div>';
      return;
    }
    var days = sub.remainingDays === 1 ? "1 day remaining" : sub.remainingDays + " days remaining";
    host.innerHTML = '<div class="current-plan"><div><h3>' + esc((sub.planId && sub.planId.name) || "Current Plan") + "</h3>" +
      "<p>Active since " + esc(new Date(sub.startedAt).toLocaleDateString()) + " · Expires " + esc(new Date(sub.expiresAt).toLocaleDateString()) + "</p>" +
      '<p class="ok">' + esc(days) + "</p>" +
      "<p>Articles: <b>" + sub.usage.articles + "/" + sub.limits.articles + "</b> &nbsp; Topics: <b>" + sub.usage.topics + "/" + sub.limits.topics + "</b></p>" +
      '</div><span class="badge b-pub">Active</span></div>';
  }

  function renderPlans(plans, sub) {
    var host = document.getElementById("plans");
    if (!plans.length) { host.innerHTML = '<div class="state-box"><h3>No plans available</h3><p>Please check back later.</p></div>'; return; }
    var currentId = sub && sub.planId && sub.planId._id;
    host.innerHTML = '<div class="plan-grid">' + plans.map(function (plan) {
      var isCurrent = plan._id === currentId;
      return '<div class="plan-card"><div class="plan-top"><span>' + esc(plan.name) + "</span>" + (isCurrent ? '<span class="badge b-pub">Current Plan</span>' : "") + "</div>" +
        '<div class="plan-price">$' + esc(plan.price || 0) + "<small>/ " + esc(cycle(plan.ForDays)) + "</small></div>" +
        "<ul>" + feature(true, plural(plan.articalsNumber, "article") + " per " + cycle(plan.ForDays)) +
        feature(true, plural(plan.maxTopics, "new topic title")) +
        feature(!!plan.analyticsEnabled, "Advanced analytics") + feature(!!plan.scheduleEnabled, "Scheduled publishing") +
        (plan.maxStores > 1 ? feature(true, plan.maxStores + " stores included") : "") + "</ul>" +
        (isCurrent ? '<button type="button" class="plan-btn current" disabled>✓ Current Plan</button>'
          : '<button type="button" class="plan-btn" data-plan="' + esc(plan._id) + '">Choose Plan</button>') + "</div>";
    }).join("") + "</div>";
    host.addEventListener("click", function (event) {
      var button = event.target.closest("[data-plan]");
      if (!button) return;
      App.api("PATCH", "/user-subscription/upgrade/" + encodeURIComponent(button.getAttribute("data-plan")))
        .then(function () { window.location.reload(); })
        .catch(function (err) { App.toast(err.message); });
    });
  }

  document.getElementById("plans").innerHTML = '<div class="state-box"><span class="spin big-spin"></span>Loading available plans…</div>';
  App.ready.then(function () {
    App.hideLoader();
    if (!App.token()) { document.getElementById("plans").innerHTML = '<div class="state-box"><h3>Not signed in</h3><p>Please open this app from your Shopify admin.</p></div>'; return; }
    Promise.all([App.api("GET", "/plans"), App.plan()]).then(function (results) {
      renderCurrent(results[1]);
      renderPlans(results[0] || [], results[1]);
    }).catch(function (err) {
      document.getElementById("plans").innerHTML = '<div class="state-box"><h3>Could not load plans</h3><p>' + esc(err.message) + "</p></div>";
    });
  });
})();
