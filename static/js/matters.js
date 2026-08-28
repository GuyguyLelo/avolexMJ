/** Nouveau dossier : matière → cabinets spécialisés, cabinet → clients et avocats. */

const root = document.querySelector("[data-matter-create]");
if (root) {
  const contextUrl = root.dataset.contextUrl;
  const areaSelect = root.querySelector("[name=practice_area]");
  const cabinetSelect = root.querySelector("[name=target_cabinet]");
  const clientSelect = root.querySelector("[name=client]");
  const lawyerSelect = root.querySelector("[name=responsible_lawyer]");
  const suggestBox = root.querySelector("[data-cabinet-suggestions]");

  const fillSelect = (select, items, current) => {
    if (!select) {
      return;
    }
    const keep = current || select.value;
    select.replaceChildren();
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "—";
    select.append(blank);
    items.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.label;
      select.append(option);
    });
    if (keep && [...select.options].some((opt) => opt.value === keep)) {
      select.value = keep;
    }
  };

  const renderSuggestions = (cabinets) => {
    if (!suggestBox) {
      return;
    }
    const list = suggestBox.querySelector(".suggest-cabinets-list");
    if (!list) {
      return;
    }
    list.replaceChildren();
    if (!cabinets.length) {
      const empty = document.createElement("li");
      empty.className = "suggest-cabinets-empty";
      empty.textContent = "Aucun cabinet n'a encore déclaré cette spécialité.";
      list.append(empty);
      suggestBox.hidden = !areaSelect?.value;
      return;
    }
    cabinets.forEach((cabinet) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "suggest-cabinet-card";
      if (cabinetSelect && cabinetSelect.value === cabinet.id) {
        button.classList.add("is-selected");
      }
      button.dataset.cabinetId = cabinet.id;
      const name = document.createElement("span");
      name.className = "suggest-cabinet-name";
      name.textContent = cabinet.name;
      const meta = document.createElement("span");
      meta.className = "suggest-cabinet-meta";
      meta.textContent = [cabinet.city, cabinet.bar_association].filter(Boolean).join(" · ");
      button.append(name, meta);
      item.append(button);
      list.append(item);
    });
    suggestBox.hidden = false;
  };

  const loadContext = async () => {
    if (!contextUrl) {
      return;
    }
    const params = new URLSearchParams();
    if (areaSelect?.value) {
      params.set("practice_area", areaSelect.value);
    }
    if (cabinetSelect?.value) {
      params.set("cabinet", cabinetSelect.value);
    }
    const response = await fetch(`${contextUrl}?${params.toString()}`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      return;
    }
    const data = await response.json();
    fillSelect(clientSelect, data.clients || []);
    fillSelect(lawyerSelect, data.lawyers || []);
    renderSuggestions(data.suggested_cabinets || []);
  };

  areaSelect?.addEventListener("change", () => {
    loadContext();
  });
  cabinetSelect?.addEventListener("change", () => {
    loadContext();
  });
  suggestBox?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-cabinet-id]");
    if (!button || !cabinetSelect) {
      return;
    }
    cabinetSelect.value = button.dataset.cabinetId;
    loadContext();
  });
}

document.querySelectorAll("[data-matter-procuration]").forEach((select) => {
  select.addEventListener("change", () => {
    const url = new URL(window.location.href);
    if (select.value) {
      url.searchParams.set("procuration", select.value);
    } else {
      url.searchParams.delete("procuration");
    }
    window.location.assign(url.toString());
  });
});
