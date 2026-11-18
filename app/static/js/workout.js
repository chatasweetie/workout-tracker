"use strict";

const data = JSON.parse(
  document.getElementById("workout-data").textContent
);

const items = data.items;
const $ = id => document.getElementById(id);

const stretchTimer = new window.StretchTimer();


const blocks = {
  warmup: "Opening stretches",
  strength: "Strength",
  cooldown: "Closing stretches",
  stretch: "Flexibility",
};

let index = items.findIndex(item => item.status === "pending");
let busy = false;
let dirty = false;
let finishVisible = false;

if (index === -1) {
  index = 0;
  showFinish();
} else {
  render();
}

function setMessage(message, error = false) {
  $("save-message").textContent = message;
  $("save-message").classList.toggle("save-error", error);
}

function setBusy(value) {
  busy = value;

  document.querySelectorAll(
    "main button, main input, main textarea"
  ).forEach(element => {
    element.disabled = value;
  });

  if (!value) {
    $("back-button").disabled = index === 0;
  }
}

function addSetRow(values = {}) {
  const row = document.createElement("div");
  row.className = "set-row";

  const label = document.createElement("span");
  label.className = "set-label";

  const reps = document.createElement("input");
  reps.type = "number";
  reps.min = "1";
  reps.step = "1";
  reps.placeholder = "Reps";
  reps.className = "set-reps";
  reps.value = values.reps ?? "";
  reps.setAttribute("aria-label", "Reps");

  const weight = document.createElement("input");
  weight.type = "number";
  weight.min = "0";
  weight.step = "any";
  weight.placeholder = "Weight (lb)";
  weight.className = "set-weight";
  weight.value = values.weight ?? "";
  weight.setAttribute("aria-label", "Weight in pounds");

  const remove = document.createElement("button");
  remove.type = "button";
  remove.textContent = "Remove";
  remove.addEventListener("click", () => {
    row.remove();
    renumberSets();
    markDirty();
  });

  row.append(label, reps, weight, remove);
  $("set-rows").append(row);
  renumberSets();
}

function renumberSets() {
  document.querySelectorAll(".set-label").forEach((label, i) => {
    label.textContent = `Set ${i + 1}`;
  });
}

function markDirty() {
  dirty = true;
  setMessage("Unsaved changes.");
}

function render() {
  finishVisible = false;
  $("exercise-screen").hidden = false;
  $("finish-screen").hidden = true;

  const item = items[index];
  stretchTimer.configure(item);


  $("exercise-progress").textContent =
    `Exercise ${index + 1} of ${items.length}`;
  $("exercise-block").textContent = blocks[item.block] || item.block;
  $("exercise-name").textContent = item.name;
  $("exercise-meta").textContent =
    `${item.focus} · ${item.on_floor ? "Floor" : "Standing / not on floor"}`;
  $("exercise-dose").textContent = item.dose || "No dose provided.";
  $("exercise-description").textContent =
    item.description || "No description provided.";
  $("exercise-equipment").textContent =
    item.equipment ? `Equipment: ${item.equipment}` : "";
  $("exercise-status").textContent = `Saved status: ${item.status}`;
  $("exercise-note").value = item.note || "";

  $("strength-fields").hidden = item.type !== "strength";
  $("set-rows").replaceChildren();

  if (item.type === "strength") {
    const rows = item.sets.length ? item.sets : [{}];
    rows.forEach(addSetRow);
  }

  showImage(item);

  dirty = false;
  setBusy(false);
}

function showImage(item) {
  // A new element prevents a previous image load from updating this one.
  const oldImage = $("exercise-image");
  const image = oldImage.cloneNode(false);
  image.removeAttribute("src");
  image.hidden = true;
  oldImage.replaceWith(image);

  $("image-placeholder").hidden = false;
  $("image-placeholder").textContent =
    item.image_url ? "Loading image…" : "No image available.";

  if (!item.image_url) return;

  image.alt = `Demonstration of ${item.name}`;

  image.onload = () => {
    image.hidden = false;
    $("image-placeholder").hidden = true;
  };

  image.onerror = () => {
    image.hidden = true;
    $("image-placeholder").hidden = false;
    $("image-placeholder").textContent = "Image unavailable.";
  };

  image.src = item.image_url;
}

function readSets() {
  if (items[index].type !== "strength") return [];

  return [...document.querySelectorAll(".set-row")].map(row => ({
    reps: row.querySelector(".set-reps").value,
    weight: row.querySelector(".set-weight").value,
  }));
}

async function postJSON(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });

  let result;

  try {
    result = await response.json();
  } catch {
    throw new Error(`Server error (${response.status}). Try again.`);
  }

  if (!response.ok) {
    throw new Error(result.error || `Save failed (${response.status}).`);
  }

  return result;
}

async function saveCurrent(status, navigation = null) {
  if (busy || finishVisible) return;

  const inputs = [
    ...$("exercise-screen").querySelectorAll("input"),
  ];

  for (const input of inputs) {
    if (!input.reportValidity()) return;
  }

  const item = items[index];
  const payload = {
    status: status ?? item.status,
    note: $("exercise-note").value,
    sets: readSets(),
  };

  stretchTimer.pause();

  setBusy(true);
  setMessage("Saving…");

  try {
    const result = await postJSON(item.save_url, payload);

    item.status = result.status;
    item.note = payload.note;
    item.sets = payload.sets.filter(
      row => row.reps !== "" || row.weight !== ""
    );
    dirty = false;

    setMessage("Saved.");

    if (navigation === "back") {
      index -= 1;
      render();
    } else if (navigation === "next") {
      if (items.every(row => row.status !== "pending")) {
        showFinish();
      } else if (index < items.length - 1) {
        index += 1;
        render();
      } else {
        index = items.findIndex(row => row.status === "pending");
        render();
      }
    } else {
      $("exercise-status").textContent =
        `Saved status: ${item.status}`;
    }
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    setBusy(false);
  }
}

function showFinish() {
  stretchTimer.stopInterval();

  finishVisible = true;
  $("exercise-screen").hidden = true;
  $("finish-screen").hidden = false;

  const done = items.filter(
    item => item.status === "done"
  ).length;

  const skipped = items.filter(
    item => item.status === "skipped"
  ).length;

  $("finish-counts").textContent =
    `${done} completed · ${skipped} skipped`;

  const titles = done === 0
    ? ["Session saved"]
    : [
        "Workout complete!",
        "You showed up!",
        "Another session in the books!",
        "Nice work today!",
        "Session complete!",
      ];

  $("celebration-title").textContent =
    titles[Math.floor(Math.random() * titles.length)];

  const celebration = $("celebration");
  celebration.replaceChildren();

  // Avoid a large celebration for an entirely skipped session.
  if (done === 0) {
    return;
  }

  const themes = [
    ["#fbbf24", "#fb7185", "#60a5fa", "#a78bfa"],
    ["#34d399", "#22d3ee", "#f9fafb", "#818cf8"],
    ["#fb923c", "#f472b6", "#fde047", "#c084fc"],
  ];

  const colors = themes[
    Math.floor(Math.random() * themes.length)
  ];

  const shapes = ["confetti-squares", "confetti-circles"];
  celebration.className =
    `celebration ${shapes[Math.floor(Math.random() * shapes.length)]}`;

  for (let i = 0; i < 48; i += 1) {
    const piece = document.createElement("span");
    piece.className = "confetti-piece";

    piece.style.left = `${Math.random() * 100}%`;
    piece.style.backgroundColor =
      colors[Math.floor(Math.random() * colors.length)];

    piece.style.setProperty(
      "--delay",
      `${Math.random() * 0.7}s`
    );

    piece.style.setProperty(
      "--duration",
      `${2.2 + Math.random() * 1.5}s`
    );

    piece.style.setProperty(
      "--drift",
      `${Math.random() * 160 - 80}px`
    );

    celebration.append(piece);
  }
}

$("complete-button").addEventListener("click", () => {
  saveCurrent("done", "next");
});

$("skip-button").addEventListener("click", () => {
  saveCurrent("skipped", "next");
});

$("save-button").addEventListener("click", () => {
  saveCurrent();
});

$("back-button").addEventListener("click", () => {
  if (index > 0) saveCurrent(undefined, "back");
});

$("add-set").addEventListener("click", () => {
  addSetRow();
  markDirty();
});

$("exercise-note").addEventListener("input", markDirty);
$("set-rows").addEventListener("input", markDirty);

document.addEventListener("keydown", event => {
  const target = event.target;
  const interactive = target instanceof Element &&
    target.closest("input, textarea, select, button, a, [contenteditable]");

  if (
    interactive ||
    busy ||
    finishVisible ||
    event.repeat ||
    event.ctrlKey ||
    event.metaKey ||
    event.altKey
  ) return;

  if (event.key === "ArrowRight" && stretchTimer.enabled) {
    event.preventDefault();
    stretchTimer.toggle();
  } else if (event.code === "Space") {
    event.preventDefault();
    saveCurrent("done", "next");
  } else if (event.key.toLowerCase() === "s") {
    event.preventDefault();
    saveCurrent("skipped", "next");
  } else if (event.key === "ArrowLeft" && index > 0) {
    event.preventDefault();
    saveCurrent(undefined, "back");
  }
});

window.addEventListener("beforeunload", event => {
  if (dirty || busy) {
    event.preventDefault();
    event.returnValue = "";
  }
});