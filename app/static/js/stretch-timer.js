"use strict";

window.StretchTimer = class StretchTimer {
  constructor() {
    this.panel = document.getElementById("stretch-timer");
    this.display = document.getElementById("timer-display");
    this.roundLabel = document.getElementById("timer-round");
    this.message = document.getElementById("timer-message");
    this.toggleButton = document.getElementById("timer-toggle");
    this.resetButton = document.getElementById("timer-reset");

    this.interval = null;
    this.audio = null;

    this.enabled = false;
    this.running = false;
    this.duration = 0;
    this.remaining = 0;
    this.deadline = 0;

    this.bufferDuration = 2000;

    this.round = 1;
    this.totalRounds = 1;

    // phase: ready, buffer, hold, or done
    this.phase = "ready";

    this.toggleButton.addEventListener("click", () => {
      this.toggle();
    });

    this.resetButton.addEventListener("click", () => {
      this.reset();
    });

    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && this.running) {
        this.tick();
      }
    });
  }

  configure(item) {
    this.stopInterval();

    const seconds = Number(item.seconds);

    this.enabled =
      item.type === "stretch" &&
      Number.isFinite(seconds) &&
      seconds > 0;

    this.panel.hidden = !this.enabled;
    this.duration = this.enabled ? seconds * 1000 : 0;
    this.totalRounds = Number(item.per_side) === 1 ? 2 : 1;

    this.reset();
  }

  reset() {
    this.stopInterval();

    this.round = 1;
    this.phase = "ready";
    this.remaining = this.duration;

    this.draw();
  }

  toggle() {
    if (!this.enabled || this.phase === "done") {
      return;
    }

    if (this.running) {
      this.pause();
      return;
    }

    this.prepareAudio();

    if (this.phase === "ready") {
      this.phase = "buffer";
      this.remaining = this.bufferDuration;
    }

    // A paused buffer or hold resumes where it stopped.
    this.deadline = performance.now() + this.remaining;
    this.running = true;

    this.interval = window.setInterval(() => this.tick(), 100);

    this.draw();
  }

  pause() {
    if (!this.running) {
      return;
    }

    this.tick();

    // tick() may have completed the final hold.
    if (!this.running) {
      return;
    }

    this.stopInterval();
    this.draw();
  }

  tick() {
    if (!this.running) {
      return;
    }

    this.remaining = Math.max(
      0,
      this.deadline - performance.now()
    );

    if (this.remaining === 0) {
      if (this.phase === "buffer") {
        // Buffer finished: start a full timed hold.
        this.phase = "hold";
        this.remaining = this.duration;
        this.deadline = performance.now() + this.remaining;
      } else if (this.phase === "hold") {
        this.beep();

        if (this.round < this.totalRounds) {
          // First side finished: automatically start switch buffer.
          this.round += 1;
          this.phase = "buffer";
          this.remaining = this.bufferDuration;
          this.deadline = performance.now() + this.remaining;
        } else {
          this.phase = "done";
          this.stopInterval();
        }
      }
    }

    this.draw();
  }

  stopInterval() {
    if (this.interval !== null) {
      window.clearInterval(this.interval);
      this.interval = null;
    }

    this.running = false;
  }

  draw() {
    if (!this.enabled) {
      return;
    }

    const seconds = Math.ceil(this.remaining / 1000);

    const minutesPart = String(
      Math.floor(seconds / 60)
    ).padStart(2, "0");

    const secondsPart = String(seconds % 60).padStart(2, "0");

    this.display.textContent = `${minutesPart}:${secondsPart}`;

    this.roundLabel.textContent =
      this.totalRounds === 2
        ? `Side ${this.round} of 2`
        : "One timed hold";

    let message;
    let buttonLabel;

    if (this.phase === "ready") {
      message = "Press Right Arrow to start after a 2-second buffer.";
      buttonLabel = "Start timer (→)";
    } else if (this.phase === "done") {
      message =
        "Timer complete. Press Space when ready to log the exercise.";
      buttonLabel = "Timer complete";
    } else {
      if (this.phase === "buffer") {
        message = this.round === 1
          ? "Get ready — hold starts after this countdown."
          : "Switch sides — the next hold starts automatically.";
      } else {
        message = "Hold — timer running.";
      }

      if (!this.running) {
        message = `Paused. ${message}`;
      }

      buttonLabel = this.running
        ? "Pause timer (→)"
        : "Resume timer (→)";
    }

    this.message.textContent = message;
    this.toggleButton.textContent = buttonLabel;

    this.toggleButton.setAttribute(
      "aria-disabled",
      String(this.phase === "done")
    );

    this.panel.classList.toggle(
      "timer-buffer",
      this.phase === "buffer"
    );
  }

  prepareAudio() {
    try {
      const AudioContextClass =
        window.AudioContext || window.webkitAudioContext;


      if (!AudioContextClass) {
        return;
      }


      if (!this.audio) {
        this.audio = new AudioContextClass();
      }


      if (this.audio.state === "suspended") {
        this.audio.resume().catch(() => {
          // Visual timer remains usable without audio.
        });
      }
    } catch {
      // Audio is optional.
    }
  }


  beep() {
    if (!this.audio || this.audio.state !== "running") {
      return;
    }


    try {
      const start = this.audio.currentTime;
      const oscillator = this.audio.createOscillator();
      const gain = this.audio.createGain();


      oscillator.type = "sine";
      oscillator.frequency.value = 880;


      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.15, start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.3);


      oscillator.connect(gain);
      gain.connect(this.audio.destination);


      oscillator.onended = () => {
        oscillator.disconnect();
        gain.disconnect();
      };


      oscillator.start(start);
      oscillator.stop(start + 0.32);
    } catch {
      // Do not interrupt the workout if sound is unavailable.
    }
  }
};