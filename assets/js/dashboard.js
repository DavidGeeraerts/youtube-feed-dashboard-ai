(function () {
  "use strict";

  var TZ = "America/Los_Angeles";
  var dashboard = document.getElementById("dashboard");
  if (!dashboard) return;

  var indexData = null;
  var currentDate = null;
  var requestToken = 0;

  function siteRoot() {
    var raw = dashboard.getAttribute("data-baseurl") || "";
    if (!raw || raw === "/") return "";
    return raw.replace(/\/$/, "");
  }

  function dataUrl(path) {
    return siteRoot() + "/assets/data/" + path;
  }

  function todayISO() {
    var parts = new Intl.DateTimeFormat("en-US", {
      timeZone: TZ,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(new Date());
    var bag = {};
    parts.forEach(function (part) {
      bag[part.type] = part.value;
    });
    return bag.year + "-" + bag.month + "-" + bag.day;
  }

  function isISODate(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    var parts = value.split("-").map(Number);
    var utc = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    return (
      utc.getUTCFullYear() === parts[0] &&
      utc.getUTCMonth() === parts[1] - 1 &&
      utc.getUTCDate() === parts[2]
    );
  }

  function addDays(isoDate, delta) {
    var parts = isoDate.split("-").map(Number);
    var utc = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2] + delta));
    var month = String(utc.getUTCMonth() + 1).padStart(2, "0");
    var day = String(utc.getUTCDate()).padStart(2, "0");
    return utc.getUTCFullYear() + "-" + month + "-" + day;
  }

  function formatLong(isoDate) {
    var parts = isoDate.split("-").map(Number);
    var noon = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2], 20));
    return new Intl.DateTimeFormat("en-US", {
      timeZone: TZ,
      weekday: "long",
      year: "numeric",
      month: "long",
      day: "numeric",
    }).format(noon);
  }

  function formatTime(iso) {
    var date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    return new Intl.DateTimeFormat("en-US", {
      timeZone: TZ,
      hour: "numeric",
      minute: "2-digit",
      timeZoneName: "short",
    }).format(date);
  }

  function formatStamp(iso) {
    var date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    return new Intl.DateTimeFormat("en-US", {
      timeZone: TZ,
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      timeZoneName: "short",
    }).format(date);
  }

  function navDays() {
    var today = todayISO();
    var set = {};
    var stored = (indexData && indexData.days) || [];
    stored.forEach(function (day) {
      if (isISODate(day)) set[day] = true;
    });
    set[today] = true;
    set[addDays(today, -1)] = true;
    return Object.keys(set).sort().reverse();
  }

  function clampDate(date) {
    var days = navDays();
    if (!days.length) return todayISO();
    if (date > days[0]) return days[0];
    if (date < days[days.length - 1]) return days[days.length - 1];
    return date;
  }

  function kickerFor(date) {
    var today = todayISO();
    if (date === today) return "Today";
    if (date === addDays(today, -1)) return "Yesterday";
    if (date > today) return "Upcoming";
    return "Earlier";
  }

  function optionLabel(date) {
    var today = todayISO();
    var label = formatLong(date);
    if (date === today) return label + " (today)";
    if (date === addDays(today, -1)) return label + " (yesterday)";
    return label;
  }

  function safeHttps(url, kind) {
    try {
      var parsed = new URL(url);
    } catch (error) {
      return "";
    }
    if (parsed.protocol !== "https:") return "";
    var host = parsed.hostname.toLowerCase();
    if (kind === "video") {
      if (host === "www.youtube.com" || host === "youtube.com" || host === "youtu.be") {
        return parsed.href;
      }
      return "";
    }
    if (kind === "image") {
      if (host === "ytimg.com" || host.endsWith(".ytimg.com") || host.endsWith(".googleusercontent.com")) {
        return parsed.href;
      }
      return "";
    }
    if (kind === "channel") {
      if (host === "www.youtube.com" || host === "youtube.com") return parsed.href;
    }
    return "";
  }

  function applyTheme(mode, persist) {
    var link = document.getElementById("dark-theme");
    if (link) {
      if (mode === "dark") link.media = "all";
      else if (mode === "light") link.media = "not all";
      else link.media = "(prefers-color-scheme: dark)";
    }
    document.documentElement.style.colorScheme =
      mode === "dark" ? "dark" : mode === "light" ? "light" : "light dark";
    document.documentElement.setAttribute("data-theme", mode);
    if (persist) {
      try {
        localStorage.setItem("yt-feed-theme", mode);
      } catch (error) {}
    }
    document.querySelectorAll(".dashboard-appearance [data-theme]").forEach(function (button) {
      var active = button.getAttribute("data-theme") === mode;
      button.classList.toggle("btn--primary", active);
      button.classList.toggle("btn--light-outline", !active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function showMessage(text, kind) {
    var box = document.getElementById("dashboard-message");
    box.replaceChildren();
    if (!text) return;
    var note = document.createElement("p");
    note.className = "notice notice--" + (kind || "info");
    note.textContent = text;
    box.append(note);
  }

  function fillSelect(date) {
    var select = document.getElementById("day-jump");
    var days = navDays();
    if (days.indexOf(date) === -1) {
      days = days.concat([date]).sort().reverse();
    }
    select.replaceChildren();
    days.forEach(function (day) {
      var option = document.createElement("option");
      option.value = day;
      option.textContent = optionLabel(day);
      select.append(option);
    });
    select.value = date;
  }

  function neighbors(date) {
    var days = navDays();
    var newer = null;
    var older = null;
    for (var i = 0; i < days.length; i++) {
      if (days[i] > date) newer = days[i];
      if (days[i] < date) {
        older = days[i];
        break;
      }
    }
    return { newer: newer, older: older };
  }

  function updateChrome(date) {
    var beside = neighbors(date);
    document.getElementById("day-kicker").textContent = kickerFor(date);
    document.getElementById("current-date").textContent = formatLong(date);
    document.title = formatLong(date) + " · YouTube feed";
    var prev = document.getElementById("prev-day");
    var next = document.getElementById("next-day");
    prev.textContent = date === todayISO() ? "← Yesterday" : "← Previous day";
    prev.disabled = !beside.older;
    next.disabled = !beside.newer;
    fillSelect(date);
  }

  function renderVideos(videos) {
    var grid = document.getElementById("video-grid");
    grid.replaceChildren();
    if (!videos.length) return;
    var list = document.createElement("ul");
    list.className = "video-grid";
    videos.forEach(function (video) {
      var watch = safeHttps(video.url, "video");
      if (!watch && video.id) watch = "https://www.youtube.com/watch?v=" + encodeURIComponent(video.id);
      var thumb = safeHttps(video.thumbnail, "image");
      if (!thumb && video.id) thumb = "https://i.ytimg.com/vi/" + encodeURIComponent(video.id) + "/hqdefault.jpg";
      var item = document.createElement("li");
      item.className = "video-card";
      var link = document.createElement("a");
      link.className = "video-card__link";
      link.href = watch || "https://www.youtube.com/";
      var frame = document.createElement("span");
      frame.className = "video-card__thumb";
      if (thumb) {
        var img = document.createElement("img");
        img.src = thumb;
        img.alt = "";
        img.loading = "lazy";
        img.decoding = "async";
        frame.append(img);
      }
      var body = document.createElement("span");
      body.className = "video-card__body";
      var title = document.createElement("h3");
      title.className = "video-card__title";
      title.textContent = video.title || "Untitled video";
      var channel = document.createElement("p");
      channel.className = "video-card__channel";
      channel.textContent = video.channel || "Unknown channel";
      var time = document.createElement("p");
      time.className = "video-card__time";
      var stamp = formatTime(video.published);
      if (video.published) {
        var timeEl = document.createElement("time");
        timeEl.dateTime = video.published;
        timeEl.textContent = stamp || video.published;
        time.append(timeEl);
      }
      body.append(title, channel, time);
      link.append(frame, body);
      item.append(link);
      list.append(item);
    });
    grid.append(list);
  }

  function renderChannels() {
    var channels = (indexData && indexData.channels) || [];
    var failed = channels.filter(function (channel) {
      return channel.status === "error";
    }).length;
    var summary = document.getElementById("channel-summary");
    summary.textContent =
      "Channel feeds (" + channels.length + (failed ? ", " + failed + " failed" : "") + ")";
    var list = document.getElementById("channel-list");
    list.replaceChildren();
    channels.forEach(function (channel) {
      var item = document.createElement("li");
      if (channel.status === "error") item.className = "channel-error";
      var name = channel.name || channel.channel_id || "Channel";
      var channelUrl = "";
      if (channel.channel_id && /^[A-Za-z0-9_-]+$/.test(channel.channel_id)) {
        channelUrl = "https://www.youtube.com/channel/" + channel.channel_id;
      }
      if (channelUrl) {
        var link = document.createElement("a");
        link.href = channelUrl;
        link.textContent = name;
        item.append(link);
      } else {
        item.append(document.createTextNode(name));
      }
      var detail = " — ";
      if (channel.status === "ok") detail += (channel.videos || 0) + " in the latest feed";
      else if (channel.status === "empty") detail += "feed returned no videos";
      else detail += channel.error || "feed failed";
      item.append(document.createTextNode(detail));
      if (channel.feed_url && safeHttps(channel.feed_url, "video")) {
        item.append(document.createTextNode(" "));
        var feed = document.createElement("a");
        feed.href = channel.feed_url;
        feed.textContent = "XML";
        item.append(feed);
      }
      list.append(item);
    });
    if (failed) document.getElementById("channel-health").open = true;
    var updated = document.getElementById("updated-at");
    if (indexData && indexData.generated_at) {
      updated.textContent = "Feed data last updated " + formatStamp(indexData.generated_at) + ".";
    }
  }

  function sortVideos(videos) {
    return videos.slice().sort(function (a, b) {
      var left = Date.parse(a.published || "") || 0;
      var right = Date.parse(b.published || "") || 0;
      if (right !== left) return right - left;
      return String(a.id || "").localeCompare(String(b.id || ""));
    });
  }

  async function loadDay(date) {
    var response = await fetch(dataUrl("days/" + date + ".json"), { cache: "no-cache" });
    if (response.status === 404) return [];
    if (!response.ok) throw new Error("HTTP " + response.status);
    var payload = await response.json();
    var videos = payload && Array.isArray(payload.videos) ? payload.videos : [];
    return sortVideos(videos);
  }

  function setUrl(date) {
    var hash = date === todayISO() ? "" : "#" + date;
    var next = location.pathname + location.search + hash;
    var current = location.pathname + location.search + location.hash;
    if (next !== current) history.pushState({ date: date }, "", next);
  }

  async function showDate(date, push) {
    date = clampDate(date);
    currentDate = date;
    updateChrome(date);
    if (push) setUrl(date);
    var token = ++requestToken;
    showMessage("");
    document.getElementById("day-summary").textContent = "Loading videos…";
    try {
      var videos = await loadDay(date);
      if (token !== requestToken) return;
      document.getElementById("day-summary").textContent = videos.length
        ? videos.length + (videos.length === 1 ? " video." : " videos.")
        : "No videos published on this day.";
      renderVideos(videos);
    } catch (error) {
      if (token !== requestToken) return;
      document.getElementById("day-summary").textContent = "";
      document.getElementById("video-grid").replaceChildren();
      showMessage("Couldn't load videos for this day.", "warning");
    }
  }

  function step(delta) {
    var beside = neighbors(currentDate);
    var next = delta > 0 ? beside.newer : beside.older;
    if (next) showDate(next, true);
  }

  function bind() {
    document.getElementById("prev-day").addEventListener("click", function () {
      step(-1);
    });
    document.getElementById("next-day").addEventListener("click", function () {
      step(1);
    });
    document.getElementById("day-jump").addEventListener("change", function (event) {
      if (isISODate(event.target.value)) showDate(event.target.value, true);
    });
    document.querySelectorAll(".dashboard-appearance [data-theme]").forEach(function (button) {
      button.addEventListener("click", function () {
        applyTheme(button.getAttribute("data-theme"), true);
      });
    });
    window.addEventListener("popstate", function () {
      var hashed = location.hash.replace(/^#/, "");
      var date = isISODate(hashed) ? hashed : todayISO();
      showDate(date, false);
    });
  }

  async function init() {
    var initial = document.documentElement.getAttribute("data-theme") || "system";
    applyTheme(initial, false);
    bind();
    try {
      var response = await fetch(dataUrl("index.json"), { cache: "no-cache" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      indexData = await response.json();
    } catch (error) {
      document.getElementById("current-date").textContent = formatLong(todayISO());
      showMessage(
        "Couldn't load the feed index. Run the Update dashboard workflow, or fetch locally with scripts/fetch_feeds.py.",
        "warning"
      );
      return;
    }
    try {
      renderChannels();
      var hashed = location.hash.replace(/^#/, "");
      var start = isISODate(hashed) ? hashed : todayISO();
      showDate(start, false);
    } catch (error) {
      showMessage("Couldn't open this day (" + error.message + ").", "warning");
    }
  }

  init();
})();
