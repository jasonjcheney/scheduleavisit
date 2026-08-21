/* ScheduleAVisit — vanilla JS, talks to JSON APIs */
(function () {
  "use strict";

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  function toast(msg) {
    var root = $("#toast-root");
    if (!root) return;
    root.innerHTML = '<div class="toast" role="status"></div>';
    root.firstChild.textContent = msg;
    setTimeout(function () { root.innerHTML = ""; }, 2400);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  }

  async function api(path, opts) {
    opts = opts || {};
    var res = await fetch(path, {
      method: opts.method || "GET",
      headers: opts.body ? { "Content-Type": "application/json" } : {},
      credentials: "same-origin",
      body: opts.body ? JSON.stringify(opts.body) : undefined
    });
    var data = {};
    try { data = await res.json(); } catch (e) { data = { ok: false, error: "Bad response" }; }
    if (data.ok === undefined) data.ok = res.ok;
    return data;
  }

  function pad(n) { return String(n).padStart(2, "0"); }
  function toISODate(d) {
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }
  function parseISODate(s) {
    var p = s.split("-").map(Number);
    return new Date(p[0], p[1] - 1, p[2]);
  }
  function addDays(d, n) {
    var x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    x.setDate(x.getDate() + n);
    return x;
  }
  function formatTime(hhmm) {
    var parts = hhmm.split(":").map(Number);
    var h = parts[0], m = parts[1];
    var ampm = h >= 12 ? "pm" : "am";
    var hr = ((h + 11) % 12) + 1;
    return m === 0 ? hr + " " + ampm : hr + ":" + pad(m) + " " + ampm;
  }
  function weekdayName(d) {
    return d.toLocaleDateString("en-US", { weekday: "short" });
  }
  function formatLong(d) {
    return d.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
  }

  $$("[data-logout]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      api("/api/auth/logout", { method: "POST" }).then(function () { location.href = "/"; });
    });
  });

  /* ——— Login / signup ——— */
  var loginForm = $("#login-form");
  if (loginForm) {
    loginForm.addEventListener("submit", async function (e) {
      e.preventDefault();
      var err = $("#login-err");
      err.classList.add("hidden");
      var data = await api("/api/auth/login", {
        method: "POST",
        body: {
          email: loginForm.email.value,
          password: loginForm.password.value,
          next: loginForm.getAttribute("data-next") || "/dashboard"
        }
      });
      if (!data.ok) {
        err.textContent = data.error || "Could not log in.";
        err.classList.remove("hidden");
        return;
      }
      location.href = data.redirect || "/dashboard";
    });
  }

  var signupForm = $("#signup-form");
  if (signupForm) {
    signupForm.addEventListener("submit", async function (e) {
      e.preventDefault();
      var err = $("#signup-err");
      err.classList.add("hidden");
      var data = await api("/api/auth/signup", {
        method: "POST",
        body: {
          name: signupForm.name.value,
          credentials: signupForm.credentials.value,
          email: signupForm.email.value,
          password: signupForm.password.value,
          clinic: signupForm.clinic.value,
          next: signupForm.getAttribute("data-next") || "/dashboard"
        }
      });
      if (!data.ok) {
        err.textContent = data.error || "Could not create the account.";
        err.classList.remove("hidden");
        return;
      }
      location.href = data.redirect || "/dashboard";
    });
  }

  /* ——— Booking ——— */
  var bookPage = $("#booking-page");
  if (bookPage) {
    var slug = bookPage.getAttribute("data-slug");
    var minutes = Number(bookPage.getAttribute("data-minutes") || 50);
    var first = bookPage.getAttribute("data-first") || "Your clinician";
    var state = { date: null, time: null, phase: "pick", recs: null, weekHasRoom: true };

    function renderDates() {
      var strip = $("#date-strip");
      var start = new Date();
      start = new Date(start.getFullYear(), start.getMonth(), start.getDate());
      var html = "";
      for (var i = 0; i < 16; i++) {
        var d = addDays(start, i);
        var iso = toISODate(d);
        var active = iso === state.date;
        html += '<button type="button" class="date-chip' + (active ? " active" : "") +
          '" data-date="' + iso + '" aria-pressed="' + active + '">' +
          '<span class="w">' + weekdayName(d) + "</span>" +
          '<span class="d">' + d.getDate() + "</span></button>";
      }
      strip.innerHTML = html;
      $$(".date-chip", strip).forEach(function (btn) {
        btn.addEventListener("click", function () {
          state.date = btn.getAttribute("data-date");
          state.time = null;
          state.phase = "pick";
          renderDates();
          loadSlots();
          $("#book-result").innerHTML = "";
        });
      });
    }

    async function loadSlots() {
      var grid = $("#slot-grid");
      grid.innerHTML = '<p class="muted">Loading times…</p>';
      var data = await api("/api/p/" + encodeURIComponent(slug) + "/availability?date=" + state.date);
      if (!data.ok && !data.slots) {
        grid.innerHTML = '<p class="muted">Could not load times.</p>';
        return;
      }
      state.weekHasRoom = data.weekHasRoom;
      if (!data.slots || !data.slots.length) {
        grid.innerHTML = '<p class="muted">No clinic hours this day.</p>';
        return;
      }
      grid.innerHTML = data.slots.map(function (s) {
        var gone = s.booked || s.past || !s.open;
        var active = state.time === s.time;
        return '<button type="button" class="time-slot' + (gone ? " gone" : "") + (active ? " active" : "") +
          '" data-time="' + s.time + '" ' + (gone ? "disabled" : "") +
          ' aria-pressed="' + active + '">' + formatTime(s.time) + "</button>";
      }).join("");
      $$(".time-slot", grid).forEach(function (btn) {
        btn.addEventListener("click", function () {
          if (btn.disabled) return;
          state.time = btn.getAttribute("data-time");
          state.phase = "confirm";
          loadSlots();
          showConfirm();
        });
      });
    }

    function showConfirm() {
      var d = parseISODate(state.date);
      $("#book-result").innerHTML =
        '<section class="card">' +
          "<h2>Confirm with " + escapeHtml(first) + "</h2>" +
          "<p>" + formatLong(d) + " at " + formatTime(state.time) + " · " + minutes + " minutes</p>" +
          '<form id="visit-form" class="fields">' +
            '<p class="err hidden" id="visit-err"></p>' +
            '<label class="field">Your name<input type="text" name="name" required placeholder="Jordan Lee" autocomplete="name"></label>' +
            '<label class="field">Email so the office can reach you<input type="email" name="email" required placeholder="you@email.com" autocomplete="email"></label>' +
            '<label class="field">Phone <span class="tiny">(optional)</span><input type="tel" name="phone" autocomplete="tel"></label>' +
            '<button type="submit" class="btn btn-primary">Confirm this visit</button>' +
          "</form>" +
        "</section>";
      $("#visit-form").addEventListener("submit", onBook);
      $("#book-result").scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function recCard(r, featured) {
      return (
        '<div class="rec-card">' +
          '<div class="person">' +
            '<div class="avatar ' + escapeHtml(r.avatar) + '" aria-hidden="true">' + escapeHtml(r.initials) + "</div>" +
            "<div><strong>" + escapeHtml(r.name) + "</strong>" +
            '<div class="tiny">' +
              (featured ? "Recommended by " + escapeHtml(r.recommendedBy) : "Also in " + escapeHtml(r.recommendedBy) + "’s network") +
              " · " + r.miles + " miles · " + escapeHtml(r.clinic) +
            "</div></div></div>" +
          "<p style=\"margin:0\"><strong>" + escapeHtml(r.displayWhen) + "</strong> · " + r.minutes + " minutes</p>" +
          '<div class="row">' +
            '<button type="button" class="btn btn-primary btn-sm" data-book-ref="' + escapeHtml(r.peerSlug) +
              '" data-ref-date="' + r.date + '" data-ref-time="' + r.time + '">Book this time</button>' +
            '<a class="btn btn-ghost btn-sm" href="' + escapeHtml(r.rideUrl) + '">Get a ride</a>' +
          "</div>" +
        "</div>"
      );
    }

    function showReferral(payload) {
      var rec = payload.recommendation;
      var rest = payload.alternatives || [];
      var body;
      if (!rec) {
        body = '<section class="card"><h2>No openings nearby this week</h2><p>Please try another day, or call the office.</p></section>';
      } else {
        body =
          '<section class="referral" id="referral-panel">' +
            '<p class="eyebrow">This week is full</p>' +
            "<h2>" + escapeHtml(first) + " does not have room for another " + minutes + "-minute visit this week.</h2>" +
            "<p>The weekly cap already includes the people seen every week, plus time for notes and emergencies. You are not being sent away — " +
            escapeHtml(first) + " recommends someone they trust, on this same page.</p>" +
            recCard(rec, true) +
            (rest.length
              ? '<button type="button" class="btn btn-text" id="see-more">See more options</button>' +
                '<div class="more-list" id="more-list">' + rest.map(function (r) { return recCard(r, false); }).join("") + "</div>"
              : "") +
            '<p class="tiny">You can still pick a different day above. Later weeks may have room with ' + escapeHtml(first) + ".</p>" +
          "</section>";
      }
      $("#book-result").innerHTML = body;
      var more = $("#see-more");
      if (more) {
        more.addEventListener("click", function () {
          var list = $("#more-list");
          var open = list.classList.toggle("open");
          more.textContent = open ? "Hide extra options" : "See more options";
        });
      }
      $$("[data-book-ref]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          showRefConfirm(btn.getAttribute("data-book-ref"), btn.getAttribute("data-ref-date"), btn.getAttribute("data-ref-time"));
        });
      });
      $("#book-result").scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function showRefConfirm(peerSlug, date, time) {
      var d = parseISODate(date);
      $("#book-result").innerHTML =
        '<section class="card">' +
          "<h2>Confirm this referred visit</h2>" +
          "<p>" + formatLong(d) + " at " + formatTime(time) + " · " + minutes + " minutes</p>" +
          '<form id="ref-form" class="fields">' +
            '<p class="err hidden" id="visit-err"></p>' +
            '<label class="field">Your name<input type="text" name="name" required placeholder="Jordan Lee" autocomplete="name"></label>' +
            '<label class="field">Email<input type="email" name="email" required placeholder="you@email.com" autocomplete="email"></label>' +
            '<button type="submit" class="btn btn-primary">Confirm this visit</button>' +
          "</form>" +
        "</section>";
      $("#ref-form").addEventListener("submit", async function (e) {
        e.preventDefault();
        var err = $("#visit-err");
        var data = await api("/api/p/" + encodeURIComponent(slug) + "/book-referral", {
          method: "POST",
          body: {
            peerSlug: peerSlug,
            date: date,
            time: time,
            name: this.name.value.trim(),
            email: this.email.value.trim()
          }
        });
        if (!data.ok) {
          err.textContent = data.error || "Could not book that time.";
          err.classList.remove("hidden");
          return;
        }
        location.href = data.redirect;
      });
    }

    async function onBook(e) {
      e.preventDefault();
      var form = e.target;
      var err = $("#visit-err");
      err.classList.add("hidden");
      var data = await api("/api/p/" + encodeURIComponent(slug) + "/book", {
        method: "POST",
        body: {
          date: state.date,
          time: state.time,
          name: form.name.value.trim(),
          email: form.email.value.trim(),
          phone: form.phone.value.trim()
        }
      });
      if (data.full) {
        showReferral(data);
        return;
      }
      if (!data.ok) {
        err.textContent = data.error || "Could not book that time.";
        err.classList.remove("hidden");
        return;
      }
      location.href = data.redirect;
    }

    var start = new Date();
    state.date = toISODate(new Date(start.getFullYear(), start.getMonth(), start.getDate()));
    renderDates();
    loadSlots();
  }

  /* ——— Dashboard ——— */
  if ($("#dashboard-page")) {
    var cap = $("#cap-form");
    if (cap) {
      cap.addEventListener("submit", async function (e) {
        e.preventDefault();
        var data = await api("/api/me", {
          method: "PATCH",
          body: {
            weekly_target_hours: Number(cap.weekly_target_hours.value),
            buffer_hours: Number(cap.buffer_hours.value)
          }
        });
        if (!data.ok) { toast(data.error || "Could not save"); return; }
        toast("Hour settings saved");
        location.reload();
      });
    }
    var copy = $("#copy-link");
    if (copy) {
      copy.addEventListener("click", function () {
        var text = copy.getAttribute("data-copy");
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(function () { toast("Booking link copied"); }).catch(function () { toast(text); });
        } else {
          toast(text);
        }
      });
    }
    $$("[data-cancel]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        if (!confirm("Cancel this visit? The slot will open again.")) return;
        var data = await api("/api/me/appointments/" + btn.getAttribute("data-cancel") + "/cancel", { method: "POST" });
        if (!data.ok) { toast(data.error || "Could not cancel"); return; }
        toast("Visit cancelled — slot is open");
        location.reload();
      });
    });
    $$("[data-dismiss]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        if (!confirm("Dismiss " + btn.getAttribute("data-name") + "? Future visits cancel and they leave the weekly projection.")) return;
        var data = await api("/api/me/clients/" + btn.getAttribute("data-dismiss") + "/dismiss", { method: "POST" });
        if (!data.ok) { toast(data.error || "Could not dismiss"); return; }
        toast("Client dismissed — slot story updated");
        location.reload();
      });
    });
    var invite = $("#invite-form");
    if (invite) {
      invite.addEventListener("submit", async function (e) {
        e.preventDefault();
        var data = await api("/api/me/network/invite", { method: "POST", body: { email: invite.email.value } });
        var out = $("#invite-result");
        if (!data.ok) { out.textContent = data.error || "Could not invite."; return; }
        out.innerHTML = "Invite link (share it — we do not send email): <code>" + escapeHtml(data.url) + "</code>";
        toast("Invite link ready");
      });
    }
    var profile = $("#profile-form");
    if (profile) {
      profile.addEventListener("submit", async function (e) {
        e.preventDefault();
        var body = {};
        $$("input, textarea", profile).forEach(function (el) { body[el.name] = el.value; });
        var data = await api("/api/me", { method: "PATCH", body: body });
        if (!data.ok) { toast(data.error || "Could not save"); return; }
        toast("Profile saved");
        location.reload();
      });
    }
    fetch("/api/me/notifications", { credentials: "same-origin" });
  }
})();
