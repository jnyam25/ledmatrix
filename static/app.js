const state = {
  frames: [],
  delay: 1000,
  index: 0,
  timer: 0,
  devices: [],
};

const leftCanvas = document.querySelector("#left-sign");
const rightCanvas = document.querySelector("#right-sign");
const statusEl = document.querySelector("#status");
const skyEl = document.querySelector("#sky");

function setStatus(text) {
  statusEl.textContent = text;
}

async function api(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || "Request failed");
  }
  return data;
}

function paint(frame) {
  const image = frame.image;
  drawHalf(leftCanvas, image, 0, 96);
  drawHalf(rightCanvas, image, 96, 96);
}

function drawHalf(canvas, image, start, width) {
  const scale = 6;
  const ctx = canvas.getContext("2d");
  canvas.width = width * scale;
  canvas.height = 16 * scale;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const sample = document.createElement("canvas");
  sample.width = image.width;
  sample.height = image.height;
  sample.getContext("2d").drawImage(image, 0, 0);
  const pixels = sample.getContext("2d").getImageData(0, 0, image.width, image.height).data;
  for (let y = 0; y < 16; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const sourceX = start + x;
      const offset = (y * image.width + sourceX) * 4;
      const red = pixels[offset];
      const green = pixels[offset + 1];
      const blue = pixels[offset + 2];
      const lit = red + green + blue > 18;
      ctx.fillStyle = lit ? `rgb(${red} ${green} ${blue})` : "#141a12";
      ctx.beginPath();
      ctx.arc(x * scale + scale / 2, y * scale + scale / 2, lit ? 2.3 : 1.5, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

function stopReel() {
  window.clearInterval(state.timer);
  state.timer = 0;
}

function play(frames, delay) {
  stopReel();
  state.frames = frames;
  state.delay = delay || 1000;
  state.index = 0;
  if (!frames.length) return;
  paint(frames[0]);
  if (frames.length < 2) return;
  state.timer = window.setInterval(() => {
    state.index = (state.index + 1) % state.frames.length;
    paint(state.frames[state.index]);
  }, Math.max(40, state.delay));
}

function loadFrames(preview) {
  if (!preview || !preview.frames) return;
  const frames = preview.frames.map((png) => {
    const image = new Image();
    image.src = `data:image/png;base64,${png}`;
    return { image, ready: image.decode ? image.decode() : Promise.resolve() };
  });
  Promise.all(frames.map((frame) => frame.ready.catch(() => {}))).then(() => play(frames, preview.delay_ms));
}

function plate(side, link) {
  if (!link) return side;
  return `${side} ${(link.address || "").slice(-5)}`;
}

function applyStatus(data) {
  const left = data.left;
  const right = data.right;
  const leftPlate = document.querySelector("#left-plate");
  const rightPlate = document.querySelector("#right-plate");
  leftPlate.textContent = plate("Left", left);
  rightPlate.textContent = plate("Right", right);
  leftPlate.classList.toggle("is-on", Boolean(left && left.connected));
  rightPlate.classList.toggle("is-on", Boolean(right && right.connected));
  document.querySelector("#brightness").value = data.brightness;
  document.querySelector("#brightness-out").value = data.brightness;
  const now = data.playlist && data.playlist.now;
  if (now) document.querySelector("#now-playing").textContent = now;
  if (data.message && data.message !== now) setStatus(data.message);
  else setStatus("");
  if (data.keypad) showPad(data.keypad.device);
  const obs = data.weather && data.weather.observation;
  if (obs) {
    const unit = data.weather.units === "celsius" ? "C" : "F";
    skyEl.textContent = describeSky(obs, data.weather.units);
  }
}

async function refresh() {
  const data = await api("/api/preview");
  applyStatus(data);
  loadFrames(data.preview);
  return data;
}

document.querySelectorAll(".mode").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".mode").forEach((item) => {
      const on = item === button;
      item.classList.toggle("is-on", on);
      item.setAttribute("aria-selected", on ? "true" : "false");
    });
    document.querySelector("#text-form").classList.toggle("is-hidden", button.dataset.mode !== "text");
    document.querySelector("#image-form").classList.toggle("is-hidden", button.dataset.mode !== "image");
    document.querySelector("#weather-form").classList.toggle("is-hidden", button.dataset.mode !== "weather");
  });
});

document.querySelector("#brightness").addEventListener("input", (event) => {
  document.querySelector("#brightness-out").value = event.target.value;
});

document.querySelector("#brightness").addEventListener("change", async (event) => {
  try {
    applyStatus(await api("/api/brightness", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ level: Number(event.target.value) }),
    }));
  } catch (error) {
    setStatus(error.message);
  }
});

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function cssColor(value) {
  return /^#[0-9a-fA-F]{6}$/.test(String(value || "")) ? value : "#d6ff4a";
}

function coloredRuns(item) {
  const runs = item.runs && item.runs.length ? item.runs : [{ text: item.text, color: item.color }];
  return runs.map((run) => `<b style="color:${cssColor(run.color)}">${escapeHtml(run.text)}</b>`).join("");
}

async function loadLibrary() {
  const saved = await api("/api/library");
  const list = document.querySelector("#library-list");
  const rows = [];
  for (const item of saved.texts) {
    rows.push(`<li><span>${coloredRuns(item)}</span><button type="button" data-kind="text" data-id="${item.id}" aria-label="Remove">×</button></li>`);
  }
  for (const item of saved.images) {
    rows.push(`<li><span>${escapeHtml(item.name)}</span><button type="button" data-kind="image" data-id="${item.id}" aria-label="Remove">×</button></li>`);
  }
  list.innerHTML = rows.join("");
}

const PAD_ACTIONS = [
  ["item", "Library item"],
  ["weather", "Weather"],
  ["next", "Next"],
  ["previous", "Previous"],
  ["pause", "Pause or resume"],
  ["brighter", "Brighter"],
  ["dimmer", "Dimmer"],
];

function showPad(device) {
  const line = document.querySelector("#pad-status");
  if (!line) return;
  line.textContent = device || "";
}

async function loadKeypad() {
  const data = await api("/api/keypad");
  const rows = document.querySelector("#keypad-rows");
  rows.innerHTML = data.keys.map((item) => {
    const options = PAD_ACTIONS.map(([value, label]) => (
      `<option value="${value}"${item.action === value ? " selected" : ""}>${label}</option>`
    )).join("");
    const keyName = item.key === "enter" ? "Enter" : item.key;
    const slotHidden = item.action === "item" ? "" : " hidden";
    return `<div class="keypad-row">
      <span class="keypad-key">${escapeHtml(keyName)}</span>
      <input type="hidden" value="${escapeHtml(item.key)}">
      <select aria-label="Command for ${escapeHtml(keyName)}">${options}</select>
      <input class="slot" type="number" min="1" max="99" value="${Number(item.slot) || 1}" aria-label="Library slot"${slotHidden}>
      <input class="pad-label" type="text" value="${escapeHtml(item.label)}" aria-label="Command name" maxlength="80">
      <button type="button" data-key="${escapeHtml(item.key)}">Try</button>
    </div>`;
  }).join("");
  showPad(data.device);
}

document.querySelector("#keypad-rows").addEventListener("change", (event) => {
  const row = event.target.closest(".keypad-row");
  if (!row || event.target.tagName !== "SELECT") return;
  const slot = row.querySelector(".slot");
  slot.hidden = event.target.value !== "item";
});

document.querySelector("#keypad-rows").addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  try {
    const data = await api("/api/keypad/press", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: button.dataset.key }),
    });
    applyStatus(data);
  } catch (error) {
    setStatus(error.message);
  }
});

document.querySelector("#keypad-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const keys = [...document.querySelectorAll(".keypad-row")].map((row) => {
    const action = row.querySelector("select").value;
    const key = {
      key: row.querySelector("input[type='hidden']").value,
      action,
      label: row.querySelector(".pad-label").value,
    };
    if (action === "item") key.slot = Number(row.querySelector(".slot").value);
    return key;
  });
  const button = event.target.querySelector("button[type='submit']");
  button.disabled = true;
  try {
    const data = await api("/api/keypad", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keys }),
    });
    showPad(data.device);
    setStatus("Saved");
  } catch (error) {
    setStatus(error.message);
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#library-list").addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  try {
    await api(`/api/library/${button.dataset.kind}/${button.dataset.id}`, { method: "DELETE" });
    await loadLibrary();
    setStatus("Removed");
  } catch (error) {
    setStatus(error.message);
  }
});

let pen = "#d6ff4a";
let ground = "#000000";
let wordColors = [];
let pickedWord = -1;

function syncWords() {
  const parts = document.querySelector("#message").value.split(/\s+/).filter(Boolean);
  wordColors = parts.map((text, index) => wordColors[index] || pen);
  if (pickedWord >= parts.length) pickedWord = -1;
  document.querySelector("#words").innerHTML = parts.map((text, index) => (
    `<button type="button" class="word${index === pickedWord ? " is-on" : ""}" data-index="${index}" style="color:${cssColor(wordColors[index])}">${escapeHtml(text)}</button>`
  )).join("");
}

function messageRuns() {
  const parts = document.querySelector("#message").value.split(/\s+/).filter(Boolean);
  const runs = [];
  parts.forEach((text, index) => {
    const color = wordColors[index] || pen;
    const piece = `${index ? " " : ""}${text}`;
    const last = runs[runs.length - 1];
    if (last && last.color === color) last.text += piece;
    else runs.push({ text: piece, color });
  });
  return runs;
}

document.querySelector("#message").addEventListener("input", syncWords);

document.querySelector("#words").addEventListener("click", (event) => {
  const button = event.target.closest(".word");
  if (!button) return;
  pickedWord = Number(button.dataset.index);
  syncWords();
});

document.querySelector("#inks").addEventListener("click", (event) => {
  const button = event.target.closest(".swatch");
  if (!button) return;
  pen = button.dataset.color;
  document.querySelectorAll("#inks .swatch").forEach((item) => item.classList.toggle("is-on", item === button));
  if (pickedWord >= 0) {
    wordColors[pickedWord] = pen;
    syncWords();
  }
});

document.querySelector("#grounds").addEventListener("click", (event) => {
  const button = event.target.closest(".swatch");
  if (!button) return;
  ground = button.dataset.color;
  document.querySelectorAll("#grounds .swatch").forEach((item) => item.classList.toggle("is-on", item === button));
});

document.querySelector("#text-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.target.querySelector("button[type='submit']");
  button.disabled = true;
  try {
    const runs = messageRuns();
    await api("/api/library/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: document.querySelector("#message").value,
        color: pen,
        background: ground,
        speed: Number(document.querySelector("#speed").value),
        runs,
      }),
    });
    document.querySelector("#message").value = "";
    wordColors = [];
    pickedWord = -1;
    syncWords();
    await loadLibrary();
  } catch (error) {
    setStatus(error.message);
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#image-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = document.querySelector("#picture").files[0];
  if (!file) {
    setStatus("Choose a picture.");
    return;
  }
  const button = event.target.querySelector("button");
  button.disabled = true;
  setStatus("");
  const body = new FormData();
  body.append("file", file);
  body.append("mode", document.querySelector("#fit").value);
  try {
    await api("/api/library/image", { method: "POST", body });
    document.querySelector("#picture").value = "";
    await loadLibrary();
    setStatus("");
  } catch (error) {
    setStatus(error.message);
  } finally {
    button.disabled = false;
  }
});

let placeTimer = 0;
let chosenPlace = null;

document.querySelector("#city").addEventListener("input", (event) => {
  chosenPlace = null;
  window.clearTimeout(placeTimer);
  const query = event.target.value.trim();
  const list = document.querySelector("#places");
  if (query.length < 2) {
    list.hidden = true;
    list.innerHTML = "";
    return;
  }
  placeTimer = window.setTimeout(async () => {
    try {
      const data = await api(`/api/places?q=${encodeURIComponent(query)}`);
      list.innerHTML = "";
      data.places.forEach((place) => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = place.label;
        button.addEventListener("click", () => {
          chosenPlace = place;
          document.querySelector("#city").value = place.label;
          list.hidden = true;
        });
        list.append(button);
      });
      list.hidden = data.places.length === 0;
      if (!data.places.length) skyEl.textContent = "No matching city.";
    } catch (error) {
      setStatus(error.message);
    }
  }, 250);
});

document.querySelector("#weather-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!chosenPlace) {
    setStatus("Pick a city from the list.");
    return;
  }
  const button = event.target.querySelector("button");
  button.disabled = true;
  setStatus("Fetching the sky…");
  try {
    const data = await api("/api/weather", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        place: chosenPlace,
        units: document.querySelector("#units").value,
        live: true,
        refresh_seconds: Number(document.querySelector("#refresh").value),
      }),
    });
    applyStatus(data);
    loadFrames(data.preview);
  } catch (error) {
    setStatus(error.message);
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#scan").addEventListener("click", async () => {
  const button = document.querySelector("#scan");
  button.disabled = true;
  setStatus("Scanning Bluetooth…");
  try {
    const data = await api("/api/scan", { method: "POST" });
    applyStatus(data);
    state.devices = data.devices || [];
    const list = document.querySelector("#device-list");
    list.innerHTML = "";
    if (!state.devices.length) {
      list.innerHTML = "<p>No named Bluetooth devices in range. Power the panels and scan again.</p>";
    }
    state.devices.forEach((device) => {
      const row = document.createElement("div");
      row.className = device.likely ? "device is-likely" : "device";
      row.innerHTML = `<div><strong></strong><small></small></div><div class="device-actions"></div>`;
      row.querySelector("strong").textContent = device.name;
      row.querySelector("small").textContent = `${device.address} · ${device.rssi} dBm`;
      ["left", "right"].forEach((side) => {
        const pick = document.createElement("button");
        pick.type = "button";
        pick.className = "ghost";
        pick.textContent = side === "left" ? "Left" : "Right";
        pick.addEventListener("click", async () => {
          pick.disabled = true;
          setStatus(`Linking ${side} panel…`);
          try {
            const linked = await api("/api/panels", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ side, address: device.address, name: device.name }),
            });
            applyStatus(linked);
            pick.textContent = side === "left" ? "Left linked" : "Right linked";
          } catch (error) {
            setStatus(error.message);
          } finally {
            pick.disabled = false;
          }
        });
        row.querySelector(".device-actions").append(pick);
      });
      list.append(row);
    });
    document.querySelector("#picker").showModal();
  } catch (error) {
    setStatus(error.message);
  } finally {
    button.disabled = false;
  }
});

function showKiosk(data) {
  const board = document.querySelector("#kiosk-board");
  const obs = data.weather && data.weather.observation;
  board.hidden = false;
  if (!obs) {
    document.querySelector("#kiosk-place").textContent = data.weather.label || "Set a city";
    document.querySelector("#kiosk-temp").textContent = "--";
    document.querySelector("#kiosk-detail").textContent = "Weather starts when a city is saved.";
    return;
  }
  const unit = data.weather.units === "celsius" ? "C" : "F";
  document.querySelector("#kiosk-place").textContent = obs.place || data.weather.label;
  document.querySelector("#kiosk-temp").textContent = `${Math.round(obs.temperature)}°${unit}`;
  document.querySelector("#kiosk-detail").textContent = obs.humidity != null
    ? `${obs.feel || "Humidity"}  ·  ${Math.round(obs.humidity)}%  ·  ${obs.clock || ""}`
    : `High ${Math.round(obs.high)}  ·  Low ${Math.round(obs.low)}  ·  ${obs.clock || ""}`;
}

function describeSky(obs, units) {
  const unit = units === "celsius" ? "C" : "F";
  const temp = `${Math.round(obs.temperature)}°${unit}`;
  if (obs.humidity != null) {
    const feel = obs.feel ? `${obs.feel} ` : "";
    return `${obs.place}: ${temp}, ${feel}${Math.round(obs.humidity)}%`;
  }
  return `${obs.place}: ${temp}, high ${Math.round(obs.high)} / low ${Math.round(obs.low)}`;
}

const kiosk = new URLSearchParams(location.search).has("kiosk");
if (kiosk) document.body.classList.add("kiosk");

let shownNow = "";

async function followPlaylist() {
  const data = await api("/api/status");
  applyStatus(data);
  const now = data.playlist && data.playlist.now;
  if (!now || now === shownNow) return;
  shownNow = now;
  const preview = await api("/api/preview");
  applyStatus(preview);
  loadFrames(preview.preview);
  if (kiosk) showKiosk(preview);
}

refresh()
  .then(async (data) => {
    shownNow = (data.playlist && data.playlist.now) || "";
    await loadLibrary();
    await loadKeypad();
    if (kiosk && data) showKiosk(data);
  })
  .catch((error) => setStatus(error.message));

window.setInterval(() => {
  followPlaylist().catch((error) => setStatus(error.message));
}, 4000);

if (kiosk) {
  window.setInterval(async () => {
    try {
      const data = await api("/api/status");
      applyStatus(data);
      showKiosk(data);
    } catch (error) {
      setStatus(error.message);
    }
  }, 20000);
}
