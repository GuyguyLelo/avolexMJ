/** Délivrance ministérielle : le choix du cabinet recharge la liste des dossiers. */

document.querySelectorAll("[data-procuration-cabinet]").forEach((select) => {
  select.addEventListener("change", () => {
    const url = new URL(window.location.href);
    if (select.value) {
      url.searchParams.set("cabinet", select.value);
    } else {
      url.searchParams.delete("cabinet");
    }
    url.searchParams.delete("matter");
    window.location.assign(url.toString());
  });
});
