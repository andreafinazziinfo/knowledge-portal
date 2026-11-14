var pollTimer = null;
/**
 * Knowledge Portal Portal Live Reload Client
 * Listens for repository changes via SSE (/api/live-events) with progressive fallback to HTTP polling.
 */
(function() {
  if (window.location.protocol !== "http:" && window.location.protocol !== "https:") {
    return;
  }

  let lastKnownSync = null;

  function showToast(msg) {
    let toast = document.getElementById("portal-live-toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "portal-live-toast";
      toast.style.position = "fixed";
      toast.style.bottom = "20px";
      toast.style.right = "20px";
      toast.style.backgroundColor = "#064e3b";
      toast.style.color = "#34d399";
      toast.style.border = "1px solid #059669";
      toast.style.borderRadius = "8px";
      toast.style.padding = "10px 18px";
      toast.style.fontFamily = "system-ui, sans-serif";
      toast.style.fontSize = "13px";
      toast.style.fontWeight = "600";
      toast.style.boxShadow = "0 8px 24px rgba(0,0,0,0.5)";
      toast.style.zIndex = "99999";
      toast.style.transition = "all 0.3s ease";
      toast.style.display = "flex";
      toast.style.alignItems = "center";
      toast.style.gap = "8px";
      document.body.appendChild(toast);
    }
    toast.innerHTML = `<span>⚡</span> ${msg}`;
  }

  function triggerReload() {
    showToast("Modifiche rilevate nel codebase. Aggiornamento vista in corso...");
    setTimeout(() => {
      window.location.reload();
    }, 400);
  }

  // 1. Native Server-Sent Events (SSE)
  if (typeof EventSource !== "undefined") {
    try {
      const sse = new EventSource("/api/live-events");
      sse.onmessage = function(e) {
        try {
          const data = JSON.parse(e.data);
          if (data && data.last_sync) {
            if (lastKnownSync === null) {
              lastKnownSync = data.last_sync;
            } else if (data.last_sync > lastKnownSync + 0.1) {
              lastKnownSync = data.last_sync;
              triggerReload();
            }
          }
        } catch(err) {}
      };
      sse.addEventListener("change", function(e) {
        try {
          const data = JSON.parse(e.data);
          if (data && data.last_sync && lastKnownSync !== null && data.last_sync > lastKnownSync + 0.1) {
            lastKnownSync = data.last_sync;
            triggerReload();
          }
        } catch(err) {}
      });
      sse.onerror = function() {
        startPollingFallback();
      };
      return;
    } catch(e) {}
  }

  // 2. Progressive Fallback: HTTP polling
    function startPollingFallback() {
    if (pollTimer) return;
    pollTimer = setInterval(async () => {
      try {
        const res = await fetch("/api/live-status", { cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        if (!data || !data.last_sync) return;

        if (lastKnownSync === null) {
          lastKnownSync = data.last_sync;
          return;
        }

        if (data.last_sync > lastKnownSync + 0.1) {
          lastKnownSync = data.last_sync;
          triggerReload();
        }
      } catch(e) {}
    }, 3000);
  }

  startPollingFallback();
})();
