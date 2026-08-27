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
          username: signupForm.username.value,
          email: signupForm.email.value,
          password: signupForm.password.value,
          next: signupForm.getAttribute("data-next") || "/setup"
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
    var sessionMinutes = Number(bookPage.getAttribute("data-minutes") || 50);
    var consultMinutes = Number(bookPage.getAttribute("data-consult-minutes") || 15);
    var consultEnabled = bookPage.getAttribute("data-consult-enabled") === "1";
    var minutes = consultEnabled ? consultMinutes : sessionMinutes;
    var visitKind = consultEnabled ? "consult" : "session";
    var first = bookPage.getAttribute("data-first") || "Your clinician";
    var needCategory = "general";
    var state = { date: null, time: null, phase: "pick", recs: null, weekHasRoom: true };

    function currentMinutes() {
      return visitKind === "consult" ? consultMinutes : sessionMinutes;
    }

    $$("#need-kind [data-need]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        needCategory = btn.getAttribute("data-need") || "general";
        $$("#need-kind [data-need]").forEach(function (b) {
          var on = b === btn;
          b.classList.toggle("active", on);
          b.setAttribute("aria-pressed", on ? "true" : "false");
        });
      });
    });

    $$("#visit-kind [data-kind]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        visitKind = btn.getAttribute("data-kind") || "session";
        minutes = currentMinutes();
        $$("#visit-kind [data-kind]").forEach(function (b) {
          var on = b === btn;
          b.classList.toggle("active", on);
          b.setAttribute("aria-pressed", on ? "true" : "false");
        });
        var help = $("#visit-kind-help");
        if (help) {
          help.textContent = visitKind === "consult"
            ? "Free consultation (" + consultMinutes + " min) — see if it’s a fit. Returning clients book a full session automatically."
            : "Full session (" + sessionMinutes + " min) — therapy hour for ongoing work.";
        }
        state.time = null;
        $("#book-result").innerHTML = "";
        if (state.date) loadSlots();
      });
    });

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

    function slotSkeleton() {
      return '<div class="slot-loading" role="status" aria-label="Loading times">' +
        '<div class="slot-skel"></div><div class="slot-skel"></div><div class="slot-skel"></div>' +
        '<div class="slot-skel"></div><div class="slot-skel"></div><div class="slot-skel"></div>' +
        "</div>";
    }

    async function loadSlots() {
      var grid = $("#slot-grid");
      grid.setAttribute("aria-busy", "true");
      grid.innerHTML = slotSkeleton();
      var data = await api("/api/p/" + encodeURIComponent(slug) + "/availability?date=" + state.date +
        "&minutes=" + currentMinutes() + "&visit_kind=" + encodeURIComponent(visitKind));
      grid.setAttribute("aria-busy", "false");
      if (!data.ok && !data.slots) {
        grid.innerHTML =
          '<div class="empty-state compact">' +
            '<p class="empty-title">Could not load times</p>' +
            '<p class="muted">Check your connection, then try again.</p>' +
            '<button type="button" class="btn btn-ghost btn-sm empty-retry" id="slot-retry">Retry</button>' +
          "</div>";
        var retry = $("#slot-retry");
        if (retry) retry.addEventListener("click", loadSlots);
        return;
      }
      state.weekHasRoom = data.weekHasRoom;
      if (!data.slots || !data.slots.length) {
        grid.innerHTML =
          '<div class="empty-state compact">' +
            '<p class="empty-title">No clinic hours this day</p>' +
            '<p class="muted">Try another day above, or check back later.</p>' +
          '</div>';
        return;
      }
      var openCount = data.slots.filter(function (s) { return !(s.booked || s.past || !s.open); }).length;
      if (openCount === 0) {
        var fuller = data.weekHasRoom === false
          ? '<p class="muted">This week looks full on hours. Pick another day, or confirm a time to see a trusted referral.</p>'
          : '<p class="muted">Every slot for this day is taken. Pick another day above.</p>';
        grid.innerHTML =
          '<div class="empty-state compact">' +
            '<p class="empty-title">No open times left</p>' +
            fuller +
          '</div>';
        return;
      }
      var banner = "";
      if (data.weekHasRoom === false) {
        banner = '<p class="notice slot-banner" role="status">This week is at the clinical hour cap. Open squares may still show — confirming one will offer a trusted peer instead of overbooking.</p>';
      } else if (openCount <= 2) {
        banner = '<p class="help-tip slot-banner" role="status">Only a few times left this day — ' + openCount + ' still open.</p>';
      }
      grid.innerHTML = banner + data.slots.map(function (s) {
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
      var kindLabel = visitKind === "consult" ? "free consultation" : "full session";
      $("#book-result").innerHTML =
        '<section class="card">' +
          "<h2>Confirm with " + escapeHtml(first) + "</h2>" +
          "<p>" + formatLong(d) + " at " + formatTime(state.time) + " · " + currentMinutes() + " minutes · " + kindLabel + "</p>" +
          '<form id="visit-form" class="fields">' +
            '<p class="err hidden" id="visit-err" aria-live="polite"></p>' +
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
      var peerFirst = (r.name || "").split(" ")[0] || r.name || "them";
      var hops = r.hops || 1;
      var trustPrimary = featured
        ? '<div class="rec-trust">' + escapeHtml(r.recommendedBy) + " recommends " + escapeHtml(r.name) + "</div>"
        : "";
      var hopSecondary = featured && hops > 1
        ? '<div class="tiny rec-hop">In ' + escapeHtml(r.recommendedBy) + "’s wider network.</div>"
        : "";
      var needLine = r.categoryLabel
        ? '<div class="tiny rec-need">' + (r.matchPhase === 0
            ? "Fits what you asked for: "
            : r.matchPhase === 1
              ? "General fallback: "
              : "Also available: ") + escapeHtml(r.categoryLabel) + "</div>"
        : "";
      var metaTiny;
      if (featured) {
        metaTiny = r.miles + " miles · " + escapeHtml(r.clinic);
      } else if (hops > 1) {
        metaTiny = "Also via " + escapeHtml(r.viaName || r.recommendedBy) +
          " · " + r.miles + " miles · " + escapeHtml(r.clinic);
      } else {
        metaTiny = "Also in " + escapeHtml(r.recommendedBy) + "’s network · " +
          r.miles + " miles · " + escapeHtml(r.clinic);
      }
      return (
        '<div class="rec-card' + (featured ? " featured" : "") + '">' +
          '<div class="person">' +
            '<div class="avatar ' + escapeHtml(r.avatar) + '" aria-hidden="true">' + escapeHtml(r.initials) + "</div>" +
            "<div><strong>" + escapeHtml(r.name) + "</strong>" +
            trustPrimary +
            hopSecondary +
            needLine +
            '<div class="tiny">' + metaTiny + "</div></div></div>" +
          "<p style=\"margin:0\"><strong>" + escapeHtml(r.displayWhen) + "</strong> · " + r.minutes + " minutes</p>" +
          '<div class="row">' +
            '<button type="button" class="btn btn-primary btn-sm" data-book-ref="' + escapeHtml(r.peerSlug) +
              '" data-ref-date="' + r.date + '" data-ref-time="' + r.time +
              '" data-ref-minutes="' + (r.minutes || sessionMinutes) + '">Book this time with ' +
              escapeHtml(peerFirst) + "</button>" +
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
        body =
          '<section class="waitlist-panel" id="waitlist-panel" tabindex="-1">' +
            '<p class="eyebrow">Waitlist</p>' +
            "<h2>No openings in " + escapeHtml(first) + "’s network right now</h2>" +
            "<p class=\"muted\">Everyone reachable through " + escapeHtml(first) +
              "’s trusted colleagues is also at capacity this week. Leave your name and email — " +
              escapeHtml(first) + " will see it on their dashboard when room opens.</p>" +
            '<form id="waitlist-form" class="fields">' +
              '<p class="err hidden" id="waitlist-err" aria-live="polite"></p>' +
              '<label class="field">Your name<input type="text" name="name" required placeholder="Jordan Lee" autocomplete="name"></label>' +
              '<label class="field">Email<input type="email" name="email" required placeholder="you@email.com" autocomplete="email"></label>' +
              '<button type="submit" class="btn btn-primary">Join the waitlist</button>' +
            "</form>" +
            '<p class="help-tip">You can still pick a different day above. Later weeks may have room with ' +
              escapeHtml(first) + ".</p>" +
            '<p class="tiny" id="waitlist-ok" hidden></p>' +
          "</section>";
      } else {
        var hops = rec.hops || 1;
        var hopLine = hops > 1
          ? "If the closest peer is also full, we keep walking " + escapeHtml(first) +
            "’s trusted network until someone has room."
          : "You still get a time — with a colleague they trust.";
        body =
          '<section class="referral" id="referral-panel" tabindex="-1">' +
            '<p class="eyebrow">Weekly capacity</p>' +
            "<h2>" + escapeHtml(first) + "’s week is at capacity</h2>" +
            "<p>" + hopLine + " The weekly cap already includes people seen every week, plus notes and emergencies — so open squares are not always bookable with " +
            escapeHtml(first) + ".</p>" +
            recCard(rec, true) +
            (rest.length
              ? '<button type="button" class="btn btn-text" id="see-more" aria-expanded="false" aria-controls="more-list">Show other trusted colleagues</button>' +
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
          if (!list) return;
          var open = list.classList.toggle("open");
          more.textContent = open ? "Hide other colleagues" : "Show other trusted colleagues";
          more.setAttribute("aria-expanded", open ? "true" : "false");
        });
      }
      var wlForm = $("#waitlist-form");
      if (wlForm) {
        wlForm.addEventListener("submit", async function (e) {
          e.preventDefault();
          var err = $("#waitlist-err");
          var okEl = $("#waitlist-ok");
          err.classList.add("hidden");
          if (okEl) okEl.hidden = true;
          var data = await api("/api/p/" + encodeURIComponent(slug) + "/waitlist", {
            method: "POST",
            body: {
              name: this.name.value.trim(),
              email: this.email.value.trim(),
              requested_minutes: currentMinutes()
            }
          });
          if (!data.ok) {
            err.textContent = data.error || "Could not join the waitlist.";
            err.classList.remove("hidden");
            return;
          }
          this.querySelectorAll("input, button").forEach(function (el) { el.disabled = true; });
          if (okEl) {
            okEl.hidden = false;
            okEl.textContent = data.message || ("You're on " + first + "'s waitlist. They will see your request on their dashboard.");
          }
          toast("You're on the waitlist");
        });
      }
      var panel = $("#referral-panel") || $("#waitlist-panel");
      if (panel && panel.focus) {
        try { panel.focus(); } catch (e) {}
      }
      $$("[data-book-ref]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          showRefConfirm(
            btn.getAttribute("data-book-ref"),
            btn.getAttribute("data-ref-date"),
            btn.getAttribute("data-ref-time"),
            Number(btn.getAttribute("data-ref-minutes") || sessionMinutes)
          );
        });
      });
      $("#book-result").scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function showRefConfirm(peerSlug, date, time, refMinutes) {
      var d = parseISODate(date);
      var peerMinutes = refMinutes || sessionMinutes;
      $("#book-result").innerHTML =
        '<section class="card">' +
          "<h2>Confirm this referred visit</h2>" +
          "<p>" + formatLong(d) + " at " + formatTime(time) + " · " + peerMinutes + " minutes</p>" +
          '<form id="ref-form" class="fields">' +
            '<p class="err hidden" id="visit-err" aria-live="polite"></p>' +
            '<label class="field">Your name<input type="text" name="name" required placeholder="Jordan Lee" autocomplete="name"></label>' +
            '<label class="field">Email<input type="email" name="email" required placeholder="you@email.com" autocomplete="email"></label>' +
            '<label class="field">Phone <span class="tiny">(optional)</span><input type="tel" name="phone" autocomplete="tel"></label>' +
            '<button type="submit" class="btn btn-primary">Confirm this visit</button>' +
          "</form>" +
        "</section>";
      $("#book-result").scrollIntoView({ behavior: "smooth", block: "start" });
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
            email: this.email.value.trim(),
            phone: (this.phone && this.phone.value ? this.phone.value.trim() : "")
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
          phone: form.phone.value.trim(),
          visitKind: visitKind,
          category: needCategory
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
        var feedback = $("#copy-link-feedback");
        function showCopied() {
          toast("Link copied — paste on your site or Psychology Today profile.");
          if (feedback) {
            feedback.hidden = false;
            feedback.setAttribute("role", "status");
          }
          copy.textContent = "Copied";
          setTimeout(function () { copy.textContent = "Copy link"; }, 2200);
        }
        function fallbackCopy() {
          try {
            var ta = document.createElement("textarea");
            ta.value = text || "";
            ta.setAttribute("readonly", "");
            ta.style.position = "fixed";
            ta.style.left = "-9999px";
            document.body.appendChild(ta);
            ta.select();
            var ok = document.execCommand("copy");
            document.body.removeChild(ta);
            if (ok) showCopied();
            else toast(text);
          } catch (err) {
            toast(text);
          }
        }
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(showCopied).catch(fallbackCopy);
        } else {
          fallbackCopy();
        }
      });
    }
    $$("[data-cancel]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        var who = btn.getAttribute("data-name");
        var prompt = who
          ? "Cancel " + who + "’s visit? The time opens immediately, and this week’s hours drop right away."
          : "Cancel this visit? The time opens immediately, and this week’s hours drop right away.";
        if (!confirm(prompt)) return;
        var data = await api("/api/me/appointments/" + btn.getAttribute("data-cancel") + "/cancel", { method: "POST" });
        if (!data.ok) { toast(data.error || "Could not cancel"); return; }
        toast("Cancelled — that hour is free now");
        location.reload();
      });
    });

    (function setupReschedule() {
      var modal = $("#reschedule-modal");
      if (!modal) return;
      var slug = ($("#dashboard-page") && $("#dashboard-page").getAttribute("data-slug")) || "";
      var rs = { id: null, date: null, time: null, minutes: 50, origDate: null, origTime: null, name: "", kind: "session" };
      var saveBtn = $("#reschedule-save");

      function closeReschedule() {
        modal.classList.add("hidden");
        rs.id = null;
        rs.time = null;
      }

      function setErr(msg) {
        var err = $("#reschedule-err");
        if (!msg) {
          err.classList.add("hidden");
          err.textContent = "";
          return;
        }
        err.textContent = msg;
        err.classList.remove("hidden");
      }

      function renderRsDates() {
        var strip = $("#reschedule-dates");
        var start = new Date();
        start = new Date(start.getFullYear(), start.getMonth(), start.getDate());
        var html = "";
        for (var i = 0; i < 16; i++) {
          var d = addDays(start, i);
          var iso = toISODate(d);
          var active = iso === rs.date;
          html += '<button type="button" class="date-chip' + (active ? " active" : "") +
            '" data-date="' + iso + '" aria-pressed="' + active + '">' +
            '<span class="w">' + weekdayName(d) + "</span>" +
            '<span class="d">' + d.getDate() + "</span></button>";
        }
        strip.innerHTML = html;
        $$(".date-chip", strip).forEach(function (btn) {
          btn.addEventListener("click", function () {
            rs.date = btn.getAttribute("data-date");
            rs.time = null;
            if (saveBtn) saveBtn.disabled = true;
            renderRsDates();
            loadRsSlots();
          });
        });
      }

      async function loadRsSlots() {
        var grid = $("#reschedule-slots");
        grid.setAttribute("aria-busy", "true");
        grid.innerHTML = '<div class="slot-loading" role="status" aria-label="Loading times">' +
          '<div class="slot-skel"></div><div class="slot-skel"></div><div class="slot-skel"></div>' +
          "</div>";
        if (!slug || !rs.date) {
          grid.innerHTML = '<p class="muted">Could not load times.</p>';
          return;
        }
        var data = await api("/api/p/" + encodeURIComponent(slug) + "/availability?date=" + rs.date +
          "&minutes=" + rs.minutes + "&visit_kind=" + encodeURIComponent(rs.kind || "session"));
        grid.setAttribute("aria-busy", "false");
        if (!data.ok && !data.slots) {
          grid.innerHTML = '<p class="muted">Could not load times. Try another day.</p>';
          return;
        }
        var slots = data.slots || [];
        slots.forEach(function (s) {
          if (rs.date === rs.origDate && s.time === rs.origTime) {
            s.booked = false;
            s.open = !s.past;
          }
        });
        if (!slots.length) {
          grid.innerHTML = '<div class="empty-state compact"><p class="empty-title">No clinic hours this day</p>' +
            '<p class="muted">Try another day above.</p></div>';
          return;
        }
        var html = slots.map(function (s) {
          var isCurrent = rs.date === rs.origDate && s.time === rs.origTime;
          var gone = (s.booked || s.past || !s.open) && !isCurrent;
          var active = rs.time === s.time;
          return '<button type="button" class="time-slot' + (gone ? " gone" : "") +
            (active ? " active" : "") + (isCurrent ? " current" : "") +
            '" data-time="' + s.time + '" ' + (gone ? "disabled" : "") +
            ' aria-pressed="' + active + '">' + formatTime(s.time) +
            (isCurrent ? ' <span class="tiny">now</span>' : "") + "</button>";
        }).join("");
        grid.innerHTML = html;
        $$(".time-slot", grid).forEach(function (btn) {
          if (btn.disabled) return;
          btn.addEventListener("click", function () {
            rs.time = btn.getAttribute("data-time");
            $$(".time-slot", grid).forEach(function (b) {
              var on = b === btn;
              b.classList.toggle("active", on);
              b.setAttribute("aria-pressed", on ? "true" : "false");
            });
            if (saveBtn) saveBtn.disabled = !rs.time;
            setErr("");
          });
        });
      }

      $$("[data-reschedule]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          rs.id = btn.getAttribute("data-reschedule");
          rs.origDate = btn.getAttribute("data-date") || "";
          rs.origTime = btn.getAttribute("data-time") || "";
          rs.date = rs.origDate;
          rs.time = null;
          rs.minutes = Number(btn.getAttribute("data-minutes") || 50);
          rs.name = btn.getAttribute("data-name") || "this client";
          rs.kind = btn.getAttribute("data-kind") || "session";
          var who = $("#reschedule-who");
          who.textContent = rs.name + " · currently " + (rs.origDate || "") + " at " +
            (rs.origTime ? formatTime(rs.origTime) : "") + " · " + rs.minutes + " min";
          setErr("");
          if (saveBtn) saveBtn.disabled = true;
          renderRsDates();
          loadRsSlots();
          modal.classList.remove("hidden");
        });
      });

      if (saveBtn) {
        saveBtn.addEventListener("click", async function () {
          if (!rs.id || !rs.date || !rs.time) return;
          setErr("");
          saveBtn.disabled = true;
          var data = await api("/api/me/appointments/" + rs.id + "/reschedule", {
            method: "POST",
            body: { date: rs.date, time: rs.time }
          });
          if (!data.ok) {
            setErr(data.error || "Could not move this visit.");
            saveBtn.disabled = false;
            return;
          }
          closeReschedule();
          toast("Visit moved — hours updated with the new time");
          location.reload();
        });
      }
      var closeBtn = $("#reschedule-close");
      if (closeBtn) closeBtn.addEventListener("click", closeReschedule);
      modal.addEventListener("click", function (e) {
        if (e.target === modal) closeReschedule();
      });
    })();
    $$("[data-dismiss]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        if (!confirm("Dismiss " + btn.getAttribute("data-name") + "? Future visits cancel and they leave the weekly projection.")) return;
        var data = await api("/api/me/clients/" + btn.getAttribute("data-dismiss") + "/dismiss", { method: "POST" });
        if (!data.ok) { toast(data.error || "Could not dismiss"); return; }
        toast("Client dismissed — slot story updated");
        location.reload();
      });
    });
    $$("[data-restore]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        if (!confirm("Restore " + btn.getAttribute("data-name") + " to your caseload?")) return;
        var data = await api("/api/me/clients/" + btn.getAttribute("data-restore") + "/restore", { method: "POST" });
        if (!data.ok) { toast(data.error || "Could not restore"); return; }
        toast("Client restored to your caseload");
        location.reload();
      });
    });

    (function () {
      var input = $("#client-filter");
      var list = $("#clients-list");
      var empty = $("#clients-filter-empty");
      if (!input || !list) return;
      function applyFilter() {
        var q = (input.value || "").trim().toLowerCase();
        var items = $$(".list-item[data-name]", list);
        var shown = 0;
        items.forEach(function (row) {
          var name = (row.getAttribute("data-name") || "").toLowerCase();
          var match = !q || name.indexOf(q) !== -1;
          row.hidden = !match;
          if (match) shown += 1;
        });
        if (empty) empty.hidden = !(q && shown === 0);
      }
      input.addEventListener("input", applyFilter);
      input.addEventListener("search", applyFilter);
    })();
    $$("[data-waitlist-dismiss]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        if (!confirm("Dismiss waitlist request from " + btn.getAttribute("data-name") + "?")) return;
        var data = await api("/api/me/waitlist/" + btn.getAttribute("data-waitlist-dismiss") + "/dismiss", { method: "POST" });
        if (!data.ok) { toast(data.error || "Could not dismiss"); return; }
        toast("Waitlist request dismissed");
        location.reload();
      });
    });
    function copyInviteLink(url, btn) {
      function done() {
        toast("Invite link copied — paste it to your colleague");
        if (btn) {
          var prev = btn.textContent;
          btn.textContent = "Copied";
          setTimeout(function () { btn.textContent = prev; }, 2000);
        }
      }
      function fallback() {
        var ta = document.createElement("textarea");
        ta.value = url;
        ta.setAttribute("readonly", "");
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand("copy"); done(); }
        catch (err) { toast("Copy failed — select the link instead"); }
        document.body.removeChild(ta);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(done).catch(fallback);
      } else {
        fallback();
      }
    }

    $$("[data-copy-invite]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        copyInviteLink(btn.getAttribute("data-copy-invite"), btn);
      });
    });

    $$("[data-peer-cat]").forEach(function (sel) {
      sel.addEventListener("change", async function () {
        var peerId = Number(sel.getAttribute("data-peer-cat"));
        var data = await api("/api/me/network/recommend", {
          method: "POST",
          body: { peerId: peerId, category: sel.value }
        });
        if (!data.ok) {
          toast(data.error || "Could not save that category");
          return;
        }
        toast("Saved — " + (data.categoryLabel || sel.value));
        var meta = sel.closest(".peer") && sel.closest(".peer").querySelector(".person .tiny");
        if (meta && data.categoryLabel) {
          meta.textContent = meta.textContent.replace(/ · [^·]+$/, " · " + data.categoryLabel);
        }
      });
    });

    var invite = $("#invite-form");
    if (invite) {
      invite.addEventListener("submit", async function (e) {
        e.preventDefault();
        var out = $("#invite-result");
        var email = (invite.email.value || "").trim();
        if (!email) {
          out.className = "tiny invite-err";
          out.textContent = "Enter a colleague’s email address.";
          return;
        }
        var btn = invite.querySelector('button[type="submit"]');
        if (btn) btn.disabled = true;
        var cat = (invite.category && invite.category.value) || "general";
        var data = await api("/api/me/network/invite", { method: "POST", body: { email: email, category: cat } });
        if (btn) btn.disabled = false;
        if (!data.ok) {
          out.className = "tiny invite-err";
          out.textContent = data.error || "Could not create that invite. Check the email and try again.";
          toast(data.error || "Could not invite");
          return;
        }
                out.className = "tiny invite-ok";
        out.innerHTML =
          (data.already
            ? "You already have a pending invite for <strong>" + escapeHtml(data.email || email) + "</strong>. "
            : "Invite ready for <strong>" + escapeHtml(data.email || email) + "</strong>. ") +
          "Copy and share — we do not send email:<br><code class=\"invite-link-code\">" +
          escapeHtml(data.url) + "</code> " +
          "<button type=\"button\" class=\"btn btn-ghost btn-sm\" data-copy-invite=\"" +
          escapeHtml(data.url) + "\">Copy link</button>";
        toast(data.message || "Invite link ready — share it with your colleague");
        invite.email.value = "";
        var fresh = out.querySelector("[data-copy-invite]");
        if (fresh) {
          fresh.addEventListener("click", function () {
            copyInviteLink(fresh.getAttribute("data-copy-invite"), fresh);
          });
        }
        upsertPendingInviteRow(data.email || email, data.url);
      });
    }

    function upsertPendingInviteRow(email, url) {
      if (!email || !url) return;
      var section = document.getElementById("pending-invites");
      var list = document.getElementById("pending-invites-list");
      var form = $("#invite-form");
      if (!section && form) {
        section = document.createElement("div");
        section.className = "pending-invites";
        section.id = "pending-invites";
        section.innerHTML =
          "<h3 class=\"pending-invites-heading\">Pending invites</h3>" +
          "<p class=\"tiny\" style=\"margin:0 0 10px\">We do not send email — copy the link and share it yourself.</p>" +
          "<div class=\"list\" role=\"list\" id=\"pending-invites-list\"></div>";
        form.parentNode.insertBefore(section, form);
        list = section.querySelector("#pending-invites-list");
      }
      if (!list) return;
      var existing = null;
      $$(".invite-pending-row", list).forEach(function (row) {
        var strong = row.querySelector("strong");
        if (strong && strong.textContent.trim().toLowerCase() === String(email).toLowerCase()) existing = row;
      });
      var row = existing || document.createElement("div");
      row.className = "waitlist-row invite-pending-row";
      row.setAttribute("role", "listitem");
      row.innerHTML =
        "<div><strong>" + escapeHtml(email) + "</strong>" +
        "<div class=\"meta\">Waiting for them to accept</div></div>" +
        "<button type=\"button\" class=\"btn btn-ghost btn-sm\" data-copy-invite=\"" +
        escapeHtml(url) + "\">Copy link</button>";
      var btn = row.querySelector("[data-copy-invite]");
      if (btn) {
        btn.addEventListener("click", function () {
          copyInviteLink(btn.getAttribute("data-copy-invite"), btn);
        });
      }
      if (!existing) list.insertBefore(row, list.firstChild);
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
    var remForm = $("#reminders-form");
    if (remForm) {
      remForm.addEventListener("submit", async function (e) {
        e.preventDefault();
        var data = await api("/api/me", {
          method: "PATCH",
          body: {
            reminders_opt_in: remForm.reminders_opt_in && remForm.reminders_opt_in.checked ? 1 : 0,
            phone: remForm.phone ? remForm.phone.value.trim() : ""
          }
        });
        if (!data.ok) { toast(data.error || "Could not save"); return; }
        toast("Reminder settings saved");
      });
    }

    (function wireNotifications() {
      var card = $("#notifications-card");
      if (!card) return;
      var markAll = $("#mark-all-read");
      var badge = $("#notes-unread-badge");

      function refreshUnreadChrome() {
        var left = $$(".note[data-unread]", card).length;
        if (badge) {
          if (left) {
            badge.hidden = false;
            badge.textContent = left + " new";
          } else {
            badge.hidden = true;
          }
        }
        if (markAll) markAll.hidden = left === 0;
      }

      function markNoteRead(article) {
        if (!article || !article.getAttribute("data-unread")) return;
        article.classList.remove("unread");
        article.removeAttribute("data-unread");
        var btn = article.querySelector("[data-note-read]");
        if (btn) btn.remove();
        refreshUnreadChrome();
      }

      $$("[data-note-read]", card).forEach(function (btn) {
        btn.addEventListener("click", async function () {
          var id = btn.getAttribute("data-note-read");
          var data = await api("/api/me/notifications/" + id + "/read", { method: "POST" });
          if (!data.ok) { toast(data.error || "Could not mark read"); return; }
          markNoteRead(btn.closest(".note"));
        });
      });

      if (markAll) {
        markAll.addEventListener("click", async function () {
          var data = await api("/api/me/notifications/read-all", { method: "POST" });
          if (!data.ok) { toast(data.error || "Could not mark all read"); return; }
          $$(".note[data-unread]", card).forEach(markNoteRead);
          toast("All notifications marked read");
        });
      }
    })();

    var calCard = $("#month-cal-card");
    if (calCard) {
      var calYear = Number(calCard.getAttribute("data-year"));
      var calMonth = Number(calCard.getAttribute("data-month"));
      var calSession = Number(calCard.getAttribute("data-session-minutes") || 50);
      var MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];
      var DOW = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];

      function openBlockModal(opts) {
        var modal = $("#block-modal");
        var form = $("#block-form");
        var del = $("#block-delete");
        $("#block-err").classList.add("hidden");
        $("#block-modal-title").textContent = opts.id ? (opts.editable === false ? "Visit" : "Edit this block") : "Add a client";
        form.id.value = opts.id || "";
        form.name.value = opts.name || "";
        form.date.value = opts.date || "";
        form.time.value = opts.time || "09:00";
        form.minutes.value = opts.minutes || calSession;
        var locked = opts.editable === false;
        ["name", "date", "time", "minutes"].forEach(function (n) { form[n].disabled = locked; });
        form.querySelector("[type=submit]").classList.toggle("hidden", locked);
        del.classList.toggle("hidden", !opts.id || locked);
        modal.classList.remove("hidden");
      }

      function closeBlockModal() {
        $("#block-modal").classList.add("hidden");
      }

      function openMarkModal(b) {
        var modal = $("#mark-modal");
        var form = $("#mark-form");
        if (!modal || !form) return;
        $("#mark-err").classList.add("hidden");
        form.id.value = b.id || "";
        form.name.value = b.clientName || "";
        form.counts.checked = !!b.countsTowardCap;
        $("#mark-title").textContent = b.calendarTitle || b.name || "Busy";
        var when = formatLong(parseISODate(b.date)) + " · " + formatTime(b.time);
        if (b.minutes) when += " · " + b.minutes + " min";
        $("#mark-when").textContent = when;
        modal.classList.remove("hidden");
      }

      function closeMarkModal() {
        var modal = $("#mark-modal");
        if (modal) modal.classList.add("hidden");
      }

      async function loadMonth() {
        var grid = $("#month-cal");
        $("#cal-title").textContent = MONTHS[calMonth - 1] + " " + calYear;
        var skel = "";
        for (var s = 0; s < 7; s++) skel += '<div class="slot-skel"></div>';
        grid.innerHTML = '<div class="cal-loading" role="status" aria-label="Loading calendar">' + skel + skel + "</div>";
        var data = await api("/api/calendar?year=" + calYear + "&month=" + calMonth);
        if (!data.ok) {
          grid.innerHTML =
            '<div class="empty-state compact">' +
              '<p class="empty-title">Could not load the calendar</p>' +
              '<p class="muted">Try Previous / Next, or refresh the page.</p>' +
            "</div>";
          return;
        }
        var todayIso = toISODate(new Date());
        var start = parseISODate(data.gridStart);
        var html = DOW.map(function (d) { return '<div class="cal-dow">' + d + "</div>"; }).join("");
        for (var i = 0; i < 42; i++) {
          var d = addDays(start, i);
          var iso = toISODate(d);
          var inMonth = d.getMonth() + 1 === calMonth;
          var blocks = (data.days && data.days[iso]) || [];
          var classes = "cal-day" + (inMonth ? "" : " out") + (iso === todayIso ? " is-today" : "") +
            (blocks.length ? "" : " is-empty");
          html += '<div class="' + classes + '" data-date="' + iso + '">';
          html += '<button type="button" class="cal-day-num" data-add-date="' + iso + '" aria-label="Add client on ' + iso + '">' + d.getDate() + "</button>";
          blocks.forEach(function (b) {
            var extra = (b.source === "ical" && b.countsTowardCap) ? " session" : "";
            html += '<button type="button" class="cal-block ' + escapeHtml(b.source) + extra + '" data-block="' +
              encodeURIComponent(JSON.stringify(b)) + '" title="' + escapeHtml(formatTime(b.time) + " " + b.name) + '">' +
              escapeHtml(formatTime(b.time)) + " " + escapeHtml(b.name) + "</button>";
          });
          html += "</div>";
        }
        grid.innerHTML = html;
        $$("[data-add-date]", grid).forEach(function (btn) {
          btn.addEventListener("click", function (e) {
            e.stopPropagation();
            openBlockModal({ date: btn.getAttribute("data-add-date"), time: "09:00", minutes: calSession });
          });
        });
        $$(".cal-day", grid).forEach(function (dayEl) {
          dayEl.addEventListener("click", function (e) {
            if (e.target.closest("[data-block], [data-add-date]")) return;
            openBlockModal({ date: dayEl.getAttribute("data-date"), time: "09:00", minutes: calSession });
          });
        });
        $$("[data-block]", grid).forEach(function (btn) {
          btn.addEventListener("click", function (e) {
            e.stopPropagation();
            var b;
            try { b = JSON.parse(decodeURIComponent(btn.getAttribute("data-block"))); } catch (err) { return; }
            if (b.markable) {
              openMarkModal(b);
              return;
            }
            openBlockModal({
              id: b.id,
              name: b.name,
              date: b.date,
              time: b.time,
              minutes: b.minutes,
              editable: b.editable
            });
          });
        });
      }

      var prev = $("#cal-prev");
      var next = $("#cal-next");
      if (prev) prev.addEventListener("click", function () {
        calMonth -= 1;
        if (calMonth < 1) { calMonth = 12; calYear -= 1; }
        loadMonth();
      });
      if (next) next.addEventListener("click", function () {
        calMonth += 1;
        if (calMonth > 12) { calMonth = 1; calYear += 1; }
        loadMonth();
      });
      var blockForm = $("#block-form");
      if (blockForm) {
        blockForm.addEventListener("submit", async function (e) {
          e.preventDefault();
          var err = $("#block-err");
          err.classList.add("hidden");
          var id = blockForm.id.value;
          var body = {
            name: blockForm.name.value.trim(),
            date: blockForm.date.value,
            time: blockForm.time.value,
            minutes: Number(blockForm.minutes.value)
          };
          var path = id ? "/api/calendar/block/" + id + "/update" : "/api/calendar/block";
          var data = await api(path, { method: "POST", body: body });
          if (!data.ok) {
            err.textContent = data.error || "Could not save.";
            err.classList.remove("hidden");
            return;
          }
          closeBlockModal();
          toast(id ? "Block updated" : "Client added to the calendar");
          location.reload();
        });
      }
      var delBtn = $("#block-delete");
      if (delBtn) {
        delBtn.addEventListener("click", async function () {
          var id = $("#block-form").id.value;
          if (!id) return;
          if (!confirm("Remove this block? The person stays on your client list.")) return;
          var data = await api("/api/calendar/block/" + id + "/delete", { method: "POST" });
          if (!data.ok) { toast(data.error || "Could not remove"); return; }
          closeBlockModal();
          toast("Block removed");
          location.reload();
        });
      }
      var closeBtn = $("#block-close");
      if (closeBtn) closeBtn.addEventListener("click", closeBlockModal);
      var backdrop = $("#block-modal");
      if (backdrop) {
        backdrop.addEventListener("click", function (e) {
          if (e.target === backdrop) closeBlockModal();
        });
      }
      var markForm = $("#mark-form");
      if (markForm) {
        markForm.addEventListener("submit", async function (e) {
          e.preventDefault();
          var err = $("#mark-err");
          err.classList.add("hidden");
          var id = markForm.id.value;
          var data = await api("/api/calendar/block/" + id + "/mark", {
            method: "POST",
            body: {
              counts: markForm.counts.checked,
              name: markForm.name.value.trim()
            }
          });
          if (!data.ok) {
            err.textContent = data.error || "Could not save.";
            err.classList.remove("hidden");
            return;
          }
          closeMarkModal();
          toast(markForm.counts.checked ? "Marked as a counseling session" : "Saved as imported busy");
          location.reload();
        });
      }
      var markClose = $("#mark-close");
      if (markClose) markClose.addEventListener("click", closeMarkModal);
      var markBackdrop = $("#mark-modal");
      if (markBackdrop) {
        markBackdrop.addEventListener("click", function (e) {
          if (e.target === markBackdrop) closeMarkModal();
        });
      }
      loadMonth();
    }
  }

  /* ——— Setup wizard ——— */
  var setupForm = $("#setup-form");
  if (setupForm) {
    setupForm.addEventListener("submit", async function (e) {
      e.preventDefault();
      var err = $("#setup-err");
      err.classList.add("hidden");
      var days = $$("input[name=workday]:checked", setupForm).map(function (el) { return Number(el.value); });
      var kindEl = setupForm.querySelector("input[name=portal_kind]:checked");
      var data = await api("/api/setup", {
        method: "POST",
        body: {
          name: setupForm.name.value,
          credentials: setupForm.credentials.value,
          title: setupForm.title.value,
          specialty: setupForm.specialty.value,
          about: setupForm.about.value,
          clinic: setupForm.clinic.value,
          address: setupForm.address.value,
          weekly_target_hours: Number(setupForm.weekly_target_hours.value),
          buffer_hours: Number(setupForm.buffer_hours.value),
          slot_start: Number(setupForm.slot_start.value),
          slot_end: Number(setupForm.slot_end.value),
          lunch: Number(setupForm.lunch.value),
          session_minutes: Number(setupForm.session_minutes.value),
          consult_minutes: Number(setupForm.consult_minutes.value),
          consult_enabled: setupForm.consult_enabled.checked ? 1 : 0,
          workdays: days,
          portal_kind: kindEl ? kindEl.value : "none",
          portal_url: setupForm.portal_url.value.trim(),
          ical_url: setupForm.ical_url.value.trim(),
          phone: setupForm.phone ? setupForm.phone.value.trim() : "",
          reminders_opt_in: setupForm.reminders_opt_in && setupForm.reminders_opt_in.checked ? 1 : 0
        }
      });
      if (!data.ok) {
        err.textContent = data.error || "Could not save.";
        err.classList.remove("hidden");
        err.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
      location.href = data.redirect || "/dashboard";
    });

    var steps = $$(".setup-step");
    if (steps.length) {
      var sections = ["#who-you-are", "#your-hours", "#client-portal", "#calendar-ical"].map(function (id) {
        return document.querySelector(id);
      });
      var fill = $("#setup-progress-fill");
      var status = $("#setup-progress-status");
      var bar = document.querySelector(".setup-progress-bar");
      function markActive() {
        var idx = 0;
        sections.forEach(function (sec, i) {
          if (!sec) return;
          var top = sec.getBoundingClientRect().top;
          if (top < 160) idx = i;
        });
        steps.forEach(function (el, i) {
          var on = i === idx;
          el.classList.toggle("is-active", on);
          el.classList.toggle("is-done", i < idx);
          if (on) el.setAttribute("aria-current", "step");
          else el.removeAttribute("aria-current");
        });
        sections.forEach(function (sec, i) {
          if (sec) sec.classList.toggle("is-current", i === idx);
        });
        if (fill) fill.style.width = (((idx + 1) / steps.length) * 100) + "%";
        if (bar) bar.setAttribute("aria-valuenow", String(idx + 1));
        if (status) {
          var label = steps[idx] && steps[idx].getAttribute("data-label");
          status.textContent = "Step " + (idx + 1) + " of " + steps.length + (label ? " — " + label : "");
        }
      }
      window.addEventListener("scroll", markActive, { passive: true });
      markActive();
    }
  }

  /* ——— Change password (setup / settings) ——— */
  var passwordForm = $("#password-form");
  if (passwordForm) {
    passwordForm.addEventListener("submit", async function (e) {
      e.preventDefault();
      var err = $("#password-err");
      var ok = $("#password-ok");
      err.classList.add("hidden");
      ok.classList.add("hidden");
      var current = passwordForm.current_password.value;
      var neu = passwordForm.new_password.value;
      var confirm = passwordForm.confirm_password.value;
      if (neu.length < 6) {
        err.textContent = "Please use at least 6 characters for the new password.";
        err.classList.remove("hidden");
        return;
      }
      if (neu !== confirm) {
        err.textContent = "Those two new passwords don’t match yet. Try typing them again.";
        err.classList.remove("hidden");
        return;
      }
      var data = await api("/api/me/password", {
        method: "POST",
        body: {
          current_password: current,
          new_password: neu,
          confirm_password: confirm
        }
      });
      if (!data.ok) {
        err.textContent = data.error || "Could not update password.";
        err.classList.remove("hidden");
        return;
      }
      passwordForm.reset();
      ok.textContent = data.message || "Your password is updated.";
      ok.classList.remove("hidden");
    });
  }
})();
