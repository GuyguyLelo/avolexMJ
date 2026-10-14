/** Éditeur de mise en forme de l'acte de procuration (contenteditable). */

(function () {
  const form = document.querySelector("[data-proc-editor-form]");
  const surface = document.getElementById("proc-editor-surface");
  const hidden = document.getElementById("id_draft_html");
  const actionInput = document.getElementById("id_editor_action");
  if (!form || !surface || !hidden || !actionInput) return;

  function runCommand(cmd, value) {
    surface.focus();
    try {
      document.execCommand("styleWithCSS", false, true);
    } catch (_) {
      /* ignore */
    }
    document.execCommand(cmd, false, value === undefined ? null : value);
  }

  document.querySelectorAll(".proc-editor-tool[data-cmd]").forEach((btn) => {
    btn.addEventListener("mousedown", (event) => {
      event.preventDefault();
      const cmd = btn.getAttribute("data-cmd");
      if (!cmd) return;
      runCommand(cmd);
    });
  });

  document.querySelectorAll(".proc-editor-select[data-cmd]").forEach((select) => {
    select.addEventListener("change", () => {
      const cmd = select.getAttribute("data-cmd");
      const value = select.value;
      if (!cmd || !value) return;
      runCommand(cmd, value);
      select.selectedIndex = 0;
    });
  });

  document.querySelectorAll(".proc-editor-color[data-cmd]").forEach((input) => {
    const apply = () => {
      const cmd = input.getAttribute("data-cmd");
      if (!cmd) return;
      // Certains navigateurs utilisent backColor au lieu de hiliteColor.
      if (cmd === "hiliteColor") {
        const ok = document.execCommand("hiliteColor", false, input.value);
        if (!ok) runCommand("backColor", input.value);
        else surface.focus();
        return;
      }
      runCommand(cmd, input.value);
    };
    input.addEventListener("input", apply);
    input.addEventListener("change", apply);
  });

  form.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      const action = btn.getAttribute("data-action") || "save";
      const confirmMsg = btn.getAttribute("data-confirm");
      if (confirmMsg && !window.confirm(confirmMsg)) {
        event.preventDefault();
        return;
      }
      actionInput.value = action;
      if (action !== "reset") {
        hidden.value = surface.innerHTML;
      } else {
        hidden.value = "";
      }
    });
  });

  form.addEventListener("submit", () => {
    if (actionInput.value !== "reset") {
      hidden.value = surface.innerHTML;
    }
  });
})();
