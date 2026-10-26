/* Front-end behaviour: import with progress polling, inline cell editing,
   original-document viewer, learned-rules panel, and chart tooltips.
   No framework and no build step — the pages are server-rendered. */
(function () {
  "use strict";

  const $ = (selector, root) => (root || document).querySelector(selector);
  const $$ = (selector, root) => Array.from((root || document).querySelectorAll(selector));

  /* ------------------------------------------------- top bar scroll edge */

  // The bar is translucent; its edge appears only once content slides under it.
  const topbar = $("#topbar");
  if (topbar) {
    const syncEdge = () => topbar.classList.toggle("is-scrolled", window.scrollY > 4);
    window.addEventListener("scroll", syncEdge, { passive: true });
    syncEdge();
  }

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
        const label = document.createElement("span");
        label.textContent = file.name + " ";
        const sizeEl = document.createElement("span");
        sizeEl.className = "muted small";
        sizeEl.textContent = size;
        label.appendChild(sizeEl);
        item.appendChild(label);
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

    // Files dropped anywhere on the page open the import sheet with them.
    const carriesFiles = (event) =>
      event.dataTransfer && Array.from(event.dataTransfer.types || []).includes("Files");
    document.addEventListener("dragover", (event) => { if (carriesFiles(event)) event.preventDefault(); });
    document.addEventListener("drop", (event) => {
      if (!carriesFiles(event) || dropzone.contains(event.target)) return;
      event.preventDefault();
      importPanel.hidden = false;
      files = files.concat(Array.from(event.dataTransfer.files));
      render();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !importPanel.hidden) {
        importPanel.hidden = true;
        $("#importBtn").focus();
      }
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

    const etaText = $("#etaText");

    // Elapsed time is exact, so it is shown to the second.
    function formatDuration(seconds) {
      const s = Math.max(0, Math.round(seconds));
      if (s < 60) return `${s} s`;
      if (s < 3600) return `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s`;
      return `${Math.floor(s / 3600)} h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")} min`;
    }

    // Remaining time is an estimate: rounded so it doesn't pretend to a
    // precision it doesn't have, coarser as the horizon grows.
    function formatRemaining(seconds) {
      const s = Math.max(0, seconds);
      if (s < 10) return "quelques secondes";
      if (s < 60) return `~${Math.ceil(s / 5) * 5} s`;
      if (s < 600) {
        const rounded = Math.ceil(s / 10) * 10;
        const rest = rounded % 60;
        return `~${Math.floor(rounded / 60)} min` + (rest ? ` ${rest} s` : "");
      }
      if (s < 3600) return `~${Math.ceil(s / 60)} min`;
      const minutes = Math.ceil(s / 300) * 5;
      return `~${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")} min`;
    }

    function watchBatch(batchId, total) {
      progressWrap.hidden = false;
      progressText.textContent = total ? `0 / ${total}` : "";
      etaText.hidden = false;
      etaText.textContent = "Calcul du temps restant...";

      // Last values received from the server, and when: the display counts
      // down locally every second and is re-anchored on each poll.
      let latest = null;
      let receivedAt = 0;

      const render = () => {
        if (!latest) return;
        const since = (Date.now() - receivedAt) / 1000;
        const remaining = latest.eta_seconds - since;
        const elapsed = (latest.elapsed_seconds || 0) + since;
        etaText.textContent =
          `Temps restant estime : ${formatRemaining(remaining)}` +
          (latest.eta_basis === "initiale" ? " (premiere estimation)" : "") +
          ` · ecoule : ${formatDuration(elapsed)}`;
      };
      const ticker = setInterval(render, 1000);

      const stop = () => { clearInterval(ticker); clearInterval(poller); };

      const poll = async () => {
        try {
          const response = await fetch(`/api/batches/${batchId}`);
          if (!response.ok) throw new Error();
          const batch = await response.json();
          const percent = batch.total ? (batch.done / batch.total) * 100 : 0;
          progressBar.style.width = percent + "%";
          progressText.textContent =
            `${batch.done} / ${batch.total}` +
            (batch.failed ? ` · ${batch.failed} en erreur` : "") +
            (batch.duplicates ? ` · ${batch.duplicates} doublon(s) ignore(s)` : "");

          if (batch.status === "running") {
            latest = batch;
            receivedAt = Date.now();
            render();
            return;
          }

          stop();
          if (batch.status === "done") {
            progressBar.style.width = "100%";
            etaText.textContent = batch.elapsed_seconds != null
              ? `Termine en ${formatDuration(batch.elapsed_seconds)}.`
              : "Termine.";
          } else if (batch.status === "interrupted") {
            etaText.textContent =
              "Import interrompu par un redemarrage du serveur. Redepose les memes fichiers " +
              "pour terminer : les factures deja integrees seront reconnues et ignorees.";
          } else {
            etaText.textContent = "Import interrompu par une erreur — consulte les lignes en erreur.";
          }
          // Whatever the outcome, the user gets the summary; the table is
          // refreshed when they close it.
          showImportSummary(batchId);
        } catch (error) {
          stop();
          etaText.textContent = "Suivi interrompu — actualise la page pour voir l'avancement.";
        }
      };

      const poller = setInterval(poll, 2000);
      poll();
    }

    // An import started before this page was loaded is still worth following.
    const running = $("#runningBatch");
    if (running) {
      importPanel.hidden = false;
      watchBatch(running.dataset.batch, 0);
    }
  }

  /* -------------------------------------------------------- cell editing */

  // One save path for both editing surfaces: the table cells and the panel
  // beside the original document. `holder` is the element carrying the
  // review state classes (a table cell, or a field of the panel).
  async function saveField(invoiceId, input, holder, onSaved) {
    const value = input.value;
    if (value === input.dataset.original) return;

    holder.classList.add("is-saving");
    holder.classList.remove("is-failed");
    try {
      const response = await fetch(`/api/invoices/${encodeURIComponent(invoiceId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ field: input.dataset.field, value: value }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Enregistrement refuse");

      if (data.status === "ok" && onSaved) onSaved(value, invoiceId);
      if (data.learned && data.learned.rules_updated) {
        flash(`L'automate a mis a jour ${data.learned.rules_updated} regle(s) d'extraction.`);
      }
      // The panel may already show another invoice: leave its fields alone.
      if (input.dataset.invoice !== invoiceId) return;
      input.dataset.original = value;
      if (data.status === "ok") {
        holder.classList.remove("is-uncertain");
        holder.classList.add("is-edited");
        holder.title = "Champ corrige a la main";
      }
    } catch (error) {
      if (input.dataset.invoice !== invoiceId) return;
      holder.classList.add("is-failed");
      holder.title = error.message;
      input.value = input.dataset.original;
    } finally {
      if (input.dataset.invoice === invoiceId) holder.classList.remove("is-saving");
    }
  }

  function bindEditing(input, getInvoiceId, holder, onSaved) {
    input.addEventListener("blur", () => saveField(getInvoiceId(), input, holder, onSaved));
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); input.blur(); }
      if (event.key === "Escape" && input.value !== input.dataset.original) {
        // Cancel the edit only; a second Escape closes the document viewer.
        event.stopPropagation();
        input.value = input.dataset.original;
      }
    });
  }

  $$(".cell-input").forEach((input) => {
    input.dataset.original = input.value;
    const invoiceId = input.closest("tr").dataset.id;
    input.dataset.invoice = invoiceId;
    bindEditing(input, () => invoiceId, input.closest(".cell"));
  });

  function flash(message) {
    const banner = document.createElement("div");
    banner.className = "alert alert-info";
    banner.textContent = message;
    banner.style.cssText = "position:fixed;bottom:20px;right:20px;z-index:60;margin:0";
    document.body.appendChild(banner);
    setTimeout(() => banner.remove(), 5000);
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

  /* ------------------------------------------------------ import summary */

  const summaryModal = $("#importSummary");

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    // textContent, never innerHTML: file names come from users' archives.
    if (text != null) node.textContent = text;
    return node;
  }

  function plural(count, singular, pluralForm) {
    return `${count} ${count > 1 ? (pluralForm || singular + "s") : singular}`;
  }

  function summaryDuration(seconds) {
    if (seconds == null) return "";
    const s = Math.max(0, Math.round(seconds));
    if (s < 60) return `${s} s`;
    if (s < 3600) return `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s`;
    return `${Math.floor(s / 3600)} h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")} min`;
  }

  const KIND_LABELS = {
    extraction: "echec de la lecture par l'automate",
    unsupported: "fichier non exploitable (format, fichier illisible)",
    quota: "refusee : quota de stockage atteint",
    other: "autre erreur",
  };

  function renderSummary(data) {
    const title = $("#summaryTitle");
    const meta = $("#summaryMeta");
    const content = $("#summaryContent");
    const primary = $("#summaryPrimary");

    title.textContent = data.status === "done"
      ? "Import termine"
      : data.status === "interrupted" ? "Import interrompu" : "Import arrete par une erreur";
    meta.textContent = [
      plural(data.total, "document") + " dans le lot",
      data.elapsed_seconds != null ? `duree ${summaryDuration(data.elapsed_seconds)}` : "",
      data.label || "",
    ].filter(Boolean).join(" · ");

    content.innerHTML = "";

    // One bar, one segment per outcome: the proportions read at a glance, the
    // rows below carry the exact numbers (colour is never the only cue).
    const outcomes = [
      { key: "succeeded", label: "Integrees avec succes", value: data.succeeded, tone: "good" },
      { key: "duplicates", label: "Deja importes (non integres)", value: data.duplicates, tone: "neutral" },
      { key: "failed", label: "Non integrees : erreur", value: data.failed, tone: "critical" },
      { key: "not_processed", label: "Non traitees (import interrompu)", value: data.not_processed, tone: "muted" },
    ];

    if (data.total > 0) {
      const bar = el("div", "summary-bar");
      bar.setAttribute("role", "img");
      bar.setAttribute("aria-label", outcomes.filter((o) => o.value).map((o) => `${o.label} : ${o.value}`).join(", "));
      outcomes.filter((o) => o.value > 0).forEach((o) => {
        const segment = el("span", `summary-seg tone-${o.tone}`);
        segment.style.flexGrow = String(o.value);
        bar.appendChild(segment);
      });
      content.appendChild(bar);
    }

    const list = el("ul", "summary-list");
    outcomes.forEach((o) => {
      if (o.key === "not_processed" && !o.value) return;
      const row = el("li", "summary-row" + (o.value ? "" : " is-zero"));
      const label = el("span", "summary-label");
      label.appendChild(el("span", `summary-swatch tone-${o.tone}`));
      label.appendChild(el("span", null, o.label));
      row.appendChild(label);
      row.appendChild(el("span", "summary-count", String(o.value)));
      list.appendChild(row);

      if (o.key === "succeeded" && data.needs_review) {
        const sub = el("li", "summary-sub");
        sub.appendChild(el("span", null, `dont ${plural(data.needs_review, "facture")} avec des champs a verifier `));
        const link = el("a", null, "Voir");
        link.href = `/invoices?batch=${encodeURIComponent(data.batch_id)}&status=uncertain`;
        link.dataset.summaryLink = "";
        sub.appendChild(link);
        list.appendChild(sub);
      }
      if (o.key === "failed" && data.failed) {
        Object.keys(KIND_LABELS).forEach((kind) => {
          const count = data.failed_by_kind[kind];
          if (count) list.appendChild(el("li", "summary-sub", `${count} · ${KIND_LABELS[kind]}`));
        });
      }
    });
    content.appendChild(list);

    if (data.failures.length) {
      const section = el("section", "summary-section");
      const heading = el("h3", "summary-h3", "Factures non integrees");
      section.appendChild(heading);
      const items = el("ul", "summary-files");
      data.failures.forEach((failure) => {
        const item = el("li");
        item.appendChild(el("span", "summary-file", failure.filename.split("/").pop()));
        item.appendChild(el("span", "summary-reason", failure.error));
        items.appendChild(item);
      });
      section.appendChild(items);
      const link = el("a", "summary-more",
        data.failed > data.failures.length ? `Voir les ${data.failed} factures en erreur` : "Voir dans le tableau");
      link.href = `/invoices?batch=${encodeURIComponent(data.batch_id)}&status=errors`;
      link.dataset.summaryLink = "";
      section.appendChild(link);
      content.appendChild(section);
    }

    if (data.duplicate_examples.length) {
      const section = el("section", "summary-section summary-error");
      section.appendChild(el("h3", "summary-h3", "Fichiers deja importes"));
      section.appendChild(el("p", "summary-note",
        "Ces fichiers sont identiques a des factures deja presentes : ils n'ont pas ete integres, ni comptes dans les totaux."));
      const items = el("ul", "summary-files");
      data.duplicate_examples.forEach((dup) => {
        const item = el("li");
        item.appendChild(el("span", "summary-file", dup.filename.split("/").pop()));
        item.appendChild(el("span", "summary-reason",
          dup.original_filename ? `identique a ${dup.original_filename.split("/").pop()}` : "facture d'origine depuis supprimee"));
        items.appendChild(item);
      });
      section.appendChild(items);
      if (data.duplicates > data.duplicate_examples.length) {
        section.appendChild(el("p", "summary-note",
          `et ${plural(data.duplicates - data.duplicate_examples.length, "autre fichier")} deja importe(s).`));
      }
      content.appendChild(section);
    }

    if (data.status === "interrupted" && data.not_processed) {
      content.appendChild(el("p", "summary-alert",
        `${plural(data.not_processed, "document")} n'ont pas ete traites. Redepose les memes fichiers : ` +
        "les factures deja integrees seront reconnues comme doublons et seul le reste sera traite."));
    }

    primary.href = `/invoices?batch=${encodeURIComponent(data.batch_id)}`;
    primary.hidden = !(data.succeeded || data.failed);
  }

  async function acknowledge(batchId) {
    try {
      await fetch(`/api/batches/${encodeURIComponent(batchId)}/ack`, { method: "POST", keepalive: true });
    } catch (error) { /* the summary will simply be offered again next time */ }
  }

  async function showImportSummary(batchId) {
    if (!summaryModal || !batchId) return;
    let data;
    try {
      const response = await fetch(`/api/batches/${encodeURIComponent(batchId)}/summary`);
      if (!response.ok) return;
      data = await response.json();
    } catch (error) {
      return;
    }

    renderSummary(data);
    summaryModal.hidden = false;
    const closeButton = $("[data-summary-close].btn", summaryModal);
    if (closeButton) closeButton.focus();

    const close = async () => {
      if (summaryModal.hidden) return;
      summaryModal.hidden = true;
      document.removeEventListener("keydown", onKey);
      await acknowledge(batchId);
      // New rows only appear in the table after a reload.
      if (document.body.dataset.activeTab === "invoices") window.location.reload();
    };
    const onKey = (event) => { if (event.key === "Escape") close(); };

    $$("[data-summary-close]", summaryModal).forEach((node) => { node.onclick = close; });
    document.addEventListener("keydown", onKey);
    // Following a link from the summary also counts as having seen it.
    $$("[data-summary-link], #summaryPrimary", summaryModal).forEach((link) => {
      link.onclick = () => { acknowledge(batchId); };
    });
  }

  // An import that finished while the user was elsewhere (another tab, page
  // closed): its summary is waiting for them on the next page they open.
  if (document.body.dataset.pendingSummary && !$("#runningBatch")) {
    showImportSummary(document.body.dataset.pendingSummary);
  }

  /* ---------------------------------------------------- invoices toolbar */

  // Choosing a supplier or a sort order applies it at once.
  $$("select[data-autosubmit]").forEach((select) => {
    select.addEventListener("change", () => select.form.submit());
  });

  /* ------------------------------------------------- learned rules sheet */

  const rulesPanel = $("#rulesPanel");
  const rulesBtn = $("#rulesBtn");
  if (rulesPanel && rulesBtn) {
    const closeRules = () => {
      if (rulesPanel.hidden) return;
      rulesPanel.hidden = true;
      rulesBtn.setAttribute("aria-expanded", "false");
      rulesBtn.focus();
    };
    rulesBtn.addEventListener("click", () => {
      rulesPanel.hidden = false;
      rulesBtn.setAttribute("aria-expanded", "true");
      const close = $("[data-sheet-close].btn", rulesPanel);
      if (close) close.focus();
    });
    $$("[data-sheet-close]", rulesPanel).forEach((node) => node.addEventListener("click", closeRules));
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeRules(); });
  }

  /* ------------------------------------------------------ invoice detail */

  // The list on the left, the selected invoice on the right: its document,
  // its fields (corrected in place through saveField, so every correction
  // still feeds the learning loop) and the confirm / validate actions.
  const invoiceList = $("#invoiceList");
  const detailPane = $("#detailPane");
  if (invoiceList && detailPane) {
    const rows = $$("tbody tr[data-id]", invoiceList);
    const inputs = $$(".detail-input", detailPane);
    const validateBtn = $("#validateBtn");
    const statusLine = $("#detailStatus");
    const amountFormat = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    let currentId = null;
    let current = null;
    let loadToken = 0;

    const rowFor = (id) => rows.find((row) => row.dataset.id === id);
    const stateOf = (data) => data.error ? "error"
      : data.uncertain_fields.length ? "uncertain"
      : data.edited_fields.length ? "edited" : "ok";
    const baseName = (name) => (name || "").split("/").pop();

    function announce(text) { statusLine.textContent = text || ""; }

    // Keep the list row in step with what the detail shows.
    function syncRow(data) {
      const row = rowFor(data.id);
      if (!row) return;
      row.dataset.state = stateOf(data);
      const [supplierCell, dateCell, amountCell] = row.cells;
      const label = supplierCell.querySelector(".visually-hidden");
      supplierCell.textContent = "";
      supplierCell.appendChild(el("span", "state-dot"));
      supplierCell.appendChild(data.supplier_name
        ? document.createTextNode(" " + data.supplier_name)
        : el("span", "muted", " " + baseName(data.filename)));
      if (label) supplierCell.appendChild(label);
      dateCell.textContent = data.invoice_date || "—";
      const amount = data.total_amount == null || data.total_amount === "" ? null : Number(data.total_amount);
      amountCell.textContent = amount == null || Number.isNaN(amount)
        ? "—" : `${amountFormat.format(amount)} ${data.currency || ""}`;
    }

    function emitRegions(data) {
      detailPane.dispatchEvent(new CustomEvent("invoice:regions", {
        detail: { id: data.id, regions: data.uncertain_regions || [] },
      }));
    }

    function renderDetail(data) {
      current = data;
      detailPane.removeAttribute("data-empty");
      $("#detailTitle").textContent =
        [data.supplier_name || baseName(data.filename), data.invoice_number].filter(Boolean).join(" · ");
      $("#detailMeta").textContent = [baseName(data.filename), data.archive].filter(Boolean).join(" · ");
      const openLink = $("#detailOpen");
      openLink.hidden = !data.has_file;
      openLink.href = `/invoices/${encodeURIComponent(data.id)}/file`;
      const errorEl = $("#detailError");
      errorEl.hidden = !data.error;
      errorEl.textContent = data.error || "";
      const notes = $("#detailNotes");
      notes.hidden = !data.extraction_notes;
      notes.textContent = data.extraction_notes || "";
      renderFields(data);
      announce("");
    }

    function renderFields(data) {
      inputs.forEach((input) => {
        const field = input.dataset.field;
        const holder = input.closest(".detail-field");
        const value = data[field] == null ? "" : String(data[field]);
        if (document.activeElement !== input || input.dataset.invoice !== data.id) {
          input.value = value;
          input.dataset.original = value;
        }
        input.dataset.invoice = data.id;
        const doubtful = data.uncertain_fields.includes(field);
        holder.classList.toggle("is-uncertain", doubtful);
        holder.classList.toggle("is-edited", data.edited_fields.includes(field));
        holder.classList.remove("is-failed");
        const confirm = $("[data-confirm]", holder);
        confirm.hidden = !doubtful || Boolean(data.error);
      });
      validateBtn.hidden = !data.uncertain_fields.length || Boolean(data.error);
      syncRow(data);
    }

    async function select(id, options) {
      const opts = options || {};
      const row = rowFor(id) || rows[0];
      if (!row) return;
      rows.forEach((r) => r.setAttribute("aria-selected", r === row ? "true" : "false"));
      currentId = row.dataset.id;
      const url = new URL(window.location.href);
      url.searchParams.set("id", currentId);
      window.history.replaceState(null, "", url);
      row.scrollIntoView({ block: "nearest" });
      if (opts.focusRow) row.focus({ preventScroll: true });
      if (opts.open) detailPane.classList.add("is-open");

      const token = ++loadToken;
      try {
        const response = await fetch(`/api/invoices/${encodeURIComponent(currentId)}`);
        if (!response.ok) throw new Error("Facture introuvable");
        const data = await response.json();
        if (token !== loadToken) return; // the user already moved on
        renderDetail(data);
        detailPane.dispatchEvent(new CustomEvent("invoice:selected", { detail: { id: data.id, data } }));
      } catch (error) {
        if (token === loadToken) announce(error.message);
      }
    }

    function step(delta, options) {
      const index = rows.findIndex((row) => row.dataset.id === currentId);
      const next = rows[Math.min(rows.length - 1, Math.max(0, index + delta))];
      if (next && next.dataset.id !== currentId) select(next.dataset.id, options);
    }

    rows.forEach((row) => {
      row.addEventListener("click", () => select(row.dataset.id, { open: true }));
      row.addEventListener("keydown", (event) => {
        if (event.key === "Enter") select(row.dataset.id, { open: true });
      });
    });
    $("#detailPrev").addEventListener("click", () => step(-1));
    $("#detailNext").addEventListener("click", () => step(1));
    $("#detailBack").addEventListener("click", () => {
      detailPane.classList.remove("is-open");
      const row = rowFor(currentId);
      if (row) row.focus({ preventScroll: true });
    });
    // Arrow keys walk the list — instantly: a keyboard action is never animated.
    document.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      if (event.target.closest("input, select, textarea, [contenteditable], .viewer")) return;
      if (!$("#rulesPanel") || !$("#rulesPanel").hidden) return;
      event.preventDefault();
      step(event.key === "ArrowDown" ? 1 : -1, { focusRow: true });
    });

    inputs.forEach((input) => {
      const holder = input.closest(".detail-field");
      // The id is captured when editing starts, so a save still pending while
      // the user moves to another invoice lands on the one it was typed into.
      let savingId = null;
      input.addEventListener("focus", () => {
        savingId = currentId;
        detailPane.dispatchEvent(new CustomEvent("region:focus", { detail: { field: input.dataset.field } }));
      });
      input.addEventListener("mouseenter", () => {
        detailPane.dispatchEvent(new CustomEvent("region:focus", { detail: { field: input.dataset.field } }));
      });
      bindEditing(input, () => savingId || currentId, holder, (value, invoiceId) => {
        if (!current || invoiceId !== current.id) return;
        const field = input.dataset.field;
        current[field] = value;
        current.uncertain_fields = current.uncertain_fields.filter((f) => f !== field);
        current.uncertain_regions = (current.uncertain_regions || []).filter((r) => r.field !== field);
        if (!current.edited_fields.includes(field)) current.edited_fields.push(field);
        renderFields(current);
        emitRegions(current);
      });
    });

    async function review(path, body) {
      if (!current) return;
      const invoiceId = current.id;
      announce("Enregistrement…");
      try {
        const response = await fetch(`/api/invoices/${encodeURIComponent(invoiceId)}/${path}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body || {}),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Enregistrement refuse");
        if (data.learned && data.learned.rules_updated) {
          flash(`L'automate a mis a jour ${data.learned.rules_updated} regle(s) d'extraction.`);
        }
        if (!current || current.id !== invoiceId) return;
        current.uncertain_fields = data.uncertain_fields;
        current.uncertain_regions = data.uncertain_regions;
        renderFields(current);
        emitRegions(current);
        announce(path === "validate" ? "Facture validée." : "Champ confirmé.");
      } catch (error) {
        announce(error.message);
      }
    }

    $$("[data-confirm]", detailPane).forEach((button) => {
      button.addEventListener("click", () => review("confirm", { field: button.dataset.confirm }));
    });
    validateBtn.addEventListener("click", () => review("validate"));

    const wanted = new URL(window.location.href).searchParams.get("id");
    select(wanted && rowFor(wanted) ? wanted : rows[0] && rows[0].dataset.id);
  }

  /* --------------------------------------------------------- products */

  // The alert threshold is a reading choice, not a query: every row already
  // carries its drift, so the slider repaints instead of reloading the page.
  const productTable = $("#productTable");
  if (productTable) {
    const range = $("#thresholdRange");
    const readout = $("#thresholdValue");
    const alertCount = $("#alertCount");
    const rows = $$("tbody tr", productTable);

    const apply = (threshold) => {
      let flagged = 0;
      rows.forEach((row) => {
        const over = parseFloat(row.dataset.drift) > threshold;
        row.classList.toggle("is-alert", over);
        if (over) flagged += 1;
      });
      readout.textContent = threshold;
      $$(".threshold-echo").forEach((node) => { node.textContent = threshold; });
      if (alertCount) alertCount.textContent = flagged;
      // Carried into the filter and selection forms, so the setting survives.
      $$('input[name="threshold"]').forEach((input) => { input.value = threshold; });
    };

    apply(parseInt(range.value, 10));
    range.addEventListener("input", () => apply(parseInt(range.value, 10)));
  }

  const selectionSelect = $("#selectionSelect");
  if (selectionSelect) {
    selectionSelect.addEventListener("change", () => {
      // Submitting the form would land at the top of the page, far from the
      // chart the user just changed. Navigating ourselves keeps the anchor.
      const form = $("#selectionForm");
      const query = new URLSearchParams(new FormData(form)).toString();
      window.location.href = `${form.getAttribute("action")}?${query}#evolution`;
    });
  }

  /* ------------------------------------------------ home: live import */

  // While an import runs, the home card follows it; once it ends, the page
  // reloads so the finished counts (and the import summary) appear.
  const liveImport = $("[data-batch-progress]");
  if (liveImport) {
    const batchId = liveImport.dataset.batchProgress;
    const total = Number(liveImport.dataset.total) || 0;
    const tick = async () => {
      try {
        const response = await fetch(`/api/batches/${encodeURIComponent(batchId)}`);
        if (!response.ok) return;
        const data = await response.json();
        if (data.status !== "running") { window.location.reload(); return; }
        $("[data-batch-done]", liveImport).textContent = String(data.done);
        $("[data-batch-bar]", liveImport).style.transform = `scaleX(${total ? data.done / total : 0})`;
        const eta = Number(data.eta_seconds) || 0;
        $("[data-batch-eta]", liveImport).textContent = eta < 60
          ? "moins d'une minute restante"
          : `environ ${Math.ceil(eta / 60)} min restantes`;
        setTimeout(tick, 2000);
      } catch (error) {
        setTimeout(tick, 5000);
      }
    };
    setTimeout(tick, 2000);
  }

  /* ---------------------------------------------- home: recent invoices */

  $$("tr.is-link[data-href]").forEach((row) => {
    row.addEventListener("click", (event) => {
      if (event.target.closest("a")) return; // the number link handles itself
      window.open(row.dataset.href, "_blank", "noopener");
    });
  });

  /* ------------------------------------------------------ chart tooltips */

  const tooltip = $("#chartTooltip");
  if (tooltip) {
    // Never innerHTML here: the label is a supplier name read off a document,
    // i.e. text an outsider controls by sending an invoice.
    const showTip = (event, label, value) => {
      tooltip.textContent = "";
      const strong = document.createElement("b");
      strong.textContent = label;
      tooltip.appendChild(strong);
      if (Array.isArray(value)) {
        value.forEach((text) => tooltip.appendChild(el("span", "tip-line", text)));
      } else {
        tooltip.appendChild(document.createTextNode(value));
      }
      tooltip.hidden = false;
      const box = tooltip.getBoundingClientRect();
      tooltip.style.left = Math.min(event.clientX + 14, window.innerWidth - box.width - 10) + "px";
      tooltip.style.top = Math.max(10, event.clientY - box.height - 12) + "px";
    };

    $$(".dot").forEach((dot) => {
      dot.addEventListener("mousemove", (event) => {
        showTip(event, dot.dataset.label, " · " + dot.dataset.value);
      });
      dot.addEventListener("mouseleave", () => { tooltip.hidden = true; });
    });

    // Every value comes from data-* attributes Jinja escaped, and goes back
    // out through textContent: a supplier name is never parsed as HTML.
    const heatLines = (data) => {
      const count = Number(data.count) || 0;
      const lines = [`${data.amount} · ${count} facture${count > 1 ? "s" : ""}`];
      if (data.numbers) lines.push(`N° ${data.numbers}`);
      lines.push(`Total du jour : ${data.dayTotal}`);
      lines.push(`${data.share} de son mois`);
      return lines;
    };
    $$(".heat-cell").forEach((cell) => {
      cell.addEventListener("mousemove", (event) => {
        showTip(event, `${cell.dataset.date} · ${cell.dataset.supplier}`, heatLines(cell.dataset));
      });
      cell.addEventListener("mouseleave", () => { tooltip.hidden = true; });
    });

    $$(".bar-group").forEach((group) => {
      group.addEventListener("mousemove", (event) => {
        showTip(event, group.dataset.label, group.dataset.value);
      });
      group.addEventListener("mouseleave", () => { tooltip.hidden = true; });
    });
  }
})();
