document.querySelectorAll("[data-confirm]").forEach((el) => {
  el.addEventListener("click", (event) => {
    if (!confirm(el.dataset.confirm)) {
      event.preventDefault();
    }
  });
});

document.querySelectorAll("[data-fill]").forEach((el) => {
  el.addEventListener("click", () => {
    const data = JSON.parse(el.dataset.fill);
    Object.entries(data).forEach(([key, value]) => {
      const field = document.getElementById(key);
      if (field) field.value = value;
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
});
