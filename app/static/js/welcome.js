(function () {
  "use strict";
  App.ready.then(App.hideLoader);
  var first = document.getElementById("screen1");
  var second = document.getElementById("screen2");
  document.getElementById("exploreBtn").addEventListener("click", function () {
    first.classList.remove("active");
    first.classList.add("slide-out-left");
    second.classList.add("active");
  });
  document.getElementById("startBtn").addEventListener("click", function () {
    App.setVisited();
    window.location.href = "/dashboard";
  });
})();
