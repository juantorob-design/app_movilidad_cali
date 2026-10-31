if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    const scope = new URL("./", window.location.href);
    navigator.serviceWorker
      .register(new URL("sw.js", scope), { scope: scope.pathname })
      .catch((error) => {
        console.error("No se pudo registrar el modo instalable:", error);
      });
  });
}
