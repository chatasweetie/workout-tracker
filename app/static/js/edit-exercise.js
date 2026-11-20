"use strict";

const exerciseType = document.getElementById("type");
const stretchTimerFields = document.getElementById("stretch-timer-fields");

function updateTypeFields() {
  const isStrength = exerciseType.value === "strength";
  stretchTimerFields.hidden = isStrength;
  stretchTimerFields.disabled = isStrength;
}

exerciseType.addEventListener("change", updateTypeFields);
updateTypeFields();
