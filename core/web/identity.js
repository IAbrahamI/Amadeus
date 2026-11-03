// Who the assistant is (name, avatar, theme), from the server's settings. Fills in the name wherever the page
// marks it: data-name (text), data-name-placeholder / data-name-title (templates with {name}) and the page title.
window.IDENTITY = fetch("/api/identity").then((r) => r.json()).catch(() => ({})).then((d) => {
  const id = { name: d.name || "Amadeus", avatar: d.avatar || "" };
  const fill = () => {
    document.querySelectorAll("[data-name]").forEach((e) => (e.textContent = id.name));
    document.querySelectorAll("[data-name-placeholder]").forEach((e) => (e.placeholder = e.dataset.namePlaceholder.replace("{name}", id.name)));
    document.querySelectorAll("[data-name-title]").forEach((e) => (e.title = e.dataset.nameTitle.replace("{name}", id.name)));
    if (document.title.includes("{name}")) document.title = document.title.replace("{name}", id.name);
  };
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", fill); else fill();
  return id;
});
window.NAME = () => (window._id && window._id.name) || "Amadeus";
window.IDENTITY.then((id) => (window._id = id));
