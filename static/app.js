/* Front-end behaviour: import with progress polling, inline cell editing,
   original-document viewer, learned-rules panel, and chart tooltips.
   No framework and no build step — the pages are server-rendered. */
(function () {
  "use strict";

  const $ = (selector, root) => (root || document).querySelector(selector);
  const $$ = (selector, root) => Array.from((root || document).querySelectorAll(selector));

  /* ------------------------------------------------------------- import */

  const importPanel = $("#importPanel");
  if (importPanel) {
    const dropzone = $("#dropzone");
    const fileInput = $("#fileInput");
    const fileList = $("#fileList");
    const startBtn = $("#startImport");
    const statusEl = $("#importStatus");
    const progressWrap = $("#progressWrap");
    const progressBar = $("#progressBar");
    const progressText = $("#progressText");
    let files = [];

    $("#importBtn").addEventListener("click", () => {
      importPanel.hidden = !importPanel.hidden;
      if (!importPanel.hidden) importPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });

    function render() {
      fileList.innerHTML = "";
      files.forEach((file, index) => {
        const item = document.createElement("li");
        const size = file.size > 1e6
          ? (file.size / 1e6).toFixed(1) + " Mo"
          : Math.max(1, Math.round(file.size / 1024)) + " Ko";
        item.innerHTML = `<span>${file.name} <span class="muted small">${size}</span></span>`;
        const remove = document.createElement("button");
        remove.className = "btn btn-ghost btn-sm";
        remove.textContent = "Retirer";
        remove.onclick = () => { files.splice(index, 1); render(); };
        item.appendChild(remove);
        fileList.appendChild(item);
      });
      startBtn.disabled = files.length === 0;
    }

    dropzone.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", (event) => {
      files = files.concat(Array.from(event.target.files));
      fileInput.value = "";
      render();
    });
    ["dragenter", "dragover"].forEach((name) =>
      dropzone.addEventListener(name, (event) => {
        event.preventDefault();
        dropzone.classList.add("is-over");
      })
    );
    ["dragleave", "drop"].forEach((name) =>
      dropzone.addEventListener(name, (event) => {
        event.preventDefault();
        dropzone.classList.remove("is-over");
      })
    );
    dropzone.addEventListener("drop", (event) => {
      files = files.concat(Array.from(event.dataTransfer.files));
      render();
    });

    startBtn.addEventListener("click", async () => {
      startBtn.disabled = true;
      statusEl.textContent = "Envoi des fichiers...";

      const payload = new FormData();
      files.forEach((file) => payload.append("files", file));

      try {
        const response = await fetch("/api/import", { method: "POST", body: payload });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Erreur serveur");

        files = [];
        render();
        statusEl.textContent = "";
        watchBatch(data.batch_id, data.total);
      } catch (error) {
        statusEl.textContent = error.message;
        startBtn.disabled = false;
      }
    });

    function watchBatch(batchId, total) {
      progressWrap.hidden = false;
      progressText.textContent = `0 / ${total}`;

      const timer = setInterval(async () => {
        try {
          const response = await fetch(`/api/batches/${batchId}`);
          if (!response.ok) throw new Error();
          const batch = await response.json();
          const percent = batch.total ? (batch.done / batch.total) * 100 : 0;
          progressBar.style.width = percent + "%";
          progressText.textContent =
            `${batch.done} / ${batch.total}` + (batch.failed ? ` · ${batch.failed} en erreur` : "");

          if (batch.status !== "running") {
            clearInterval(timer);
            progressText.textContent = "Termine — actualisation...";
            setTimeout(() => window.location.reload(), 800);
          }
        } catch (error) {
          clearInterval(timer);
          progressText.textContent = "Suivi interrompu — actualise la page pour voir l'avancement.";
        }
      }, 2000);
    }

    // An import started before this page was loaded is still worth following.
    const running = $("#runningBatch");
    if (running) {
      importPanel.hidden = false;
      watchBatch(running.dataset.batch, 0);
    }
  }

  /* -------------------------------------------------------- cell editing */

  $$(".cell-input").forEach((input) => {
    input.dataset.original = input.value;

    const save = async () => {
      const value = input.value;
      if (value === input.dataset.original) return;

      const cell = input.closest(".cell");
      const invoiceId = input.closest("tr").dataset.id;
      cell.classList.add("is-saving");
      cell.classList.remove("is-failed");

      try {
        const response = await fetch(`/api/invoices/${invoiceId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ field: input.dataset.field, value: value }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Enregistrement refuse");

        input.dataset.original = value;
        cell.classList.remove("is-uncertain");
        cell.classList.add("is-edited");
        cell.title = "Champ corrige a la main";
        if (data.learned && data.learned.rules_updated) {
          flash(`Claude a mis a jour ${data.learned.rules_updated} regle(s) d'extraction.`);
        }
      } catch (error) {
        cell.classList.add("is-failed");
        cell.title = error.message;
        input.value = input.dataset.original;
      } finally {
        cell.classList.remove("is-saving");
      }
    };

    input.addEventListener("blur", save);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); input.blur(); }
      if (event.key === "Escape") { input.value = input.dataset.original; input.blur(); }
    });
  });

  function flash(message) {
    const banner = document.createElement("div");
    banner.className = "alert alert-info";
    banner.textContent = message;
    banner.style.cssText = "position:fixed;bottom:20px;right:20px;z-index:60;margin:0";
    document.body.appendChild(banner);
    setTimeout(() => banner.remove(), 5000);
  }

  /* ------------------------------------------------------ document modal */

  const modal = $("#docModal");
  if (modal) {
    const frame = $("#docFrame");
    const title = $("#docTitle");
    const openLink = $("#docOpen");

    $$(".view-doc").forEach((button) => {
      button.addEventListener("click", () => {
        const url = `/invoices/${button.dataset.id}/file`;
        frame.src = url;
        openLink.href = url;
        title.textContent = button.dataset.name;
        modal.hidden = false;
      });
    });

    const close = () => { modal.hidden = true; frame.src = "about:blank"; };
    $$("[data-close]", modal).forEach((element) => element.addEventListener("click", close));
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !modal.hidden) close();
    });
  }

  /* --------------------------------------------------------------- rules */

  const learnBtn = $("#learnBtn");
  if (learnBtn) {
    const learnStatus = $("#learnStatus");
    learnBtn.addEventListener("click", async () => {
      learnBtn.disabled = true;
      learnStatus.textContent = "Analyse des corrections...";
      try {
        const response = await fetch("/api/learn", { method: "POST" });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Erreur");
        learnStatus.textContent = data.corrections
          ? `${data.corrections} correction(s) analysee(s), ${data.rules_updated} regle(s) mise(s) a jour.`
          : "Aucune correction en attente.";
        if (data.rules_updated) setTimeout(() => window.location.reload(), 1200);
      } catch (error) {
        learnStatus.textContent = error.message;
      } finally {
        learnBtn.disabled = false;
      }
    });
  }

  $$(".rule-delete").forEach((button) => {
    button.addEventListener("click", async () => {
      await fetch(`/api/rules/${button.dataset.id}`, { method: "DELETE" });
      button.closest("li").remove();
    });
  });

  /* ------------------------------------------------------ chart tooltips */

  const tooltip = $("#chartTooltip");
  if (tooltip) {
    $$(".bar-group").forEach((group) => {
      group.addEventListener("mousemove", (event) => {
        tooltip.innerHTML = `<b>${group.dataset.label}</b>${group.dataset.value}`;
        tooltip.hidden = false;
        const box = tooltip.getBoundingClientRect();
        const x = Math.min(event.clientX + 14, window.innerWidth - box.width - 10);
        tooltip.style.left = x + "px";
        tooltip.style.top = Math.max(10, event.clientY - box.height - 12) + "px";
      });
      group.addEventListener("mouseleave", () => { tooltip.hidden = true; });
    });
  }
})();
