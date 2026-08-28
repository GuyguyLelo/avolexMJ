(function () {
  "use strict";

  var panel = document.getElementById("cabinet-members-panel");
  if (!panel) {
    return;
  }

  var rows = document.getElementById("cabinet-member-rows");
  var template = document.getElementById("cabinet-member-row-template");
  var addBtn = document.getElementById("cabinet-add-member-btn");
  if (!rows || !template || !addBtn) {
    return;
  }

  var rowIndex = 0;

  function addRow() {
    var clone = template.content.cloneNode(true);
    var row = clone.querySelector(".cabinet-member-row");
    if (!row) {
      return;
    }

    row.dataset.rowIndex = String(rowIndex);
    row.querySelectorAll("[data-field]").forEach(function (input) {
      var field = input.getAttribute("data-field");
      input.name = "extra_member_" + field;
      input.id = "extra_member_" + field + "_" + rowIndex;
    });

    var removeBtn = row.querySelector("[data-remove-member]");
    if (removeBtn) {
      removeBtn.addEventListener("click", function () {
        row.remove();
        syncEmptyState();
      });
    }

    rows.appendChild(clone);
    rowIndex += 1;
    syncEmptyState();

    var emailInput = row.querySelector('[data-field="email"]');
    if (emailInput) {
      emailInput.focus();
    }
  }

  function syncEmptyState() {
    var hasRows = rows.querySelector(".cabinet-member-row") !== null;
    var empty = panel.querySelector(".cabinet-members-empty");
    if (empty) {
      empty.hidden = hasRows;
    }
  }

  addBtn.addEventListener("click", addRow);
  syncEmptyState();
})();
