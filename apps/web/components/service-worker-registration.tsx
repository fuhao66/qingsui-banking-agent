"use client";

import { useEffect } from "react";

export function ServiceWorkerRegistration() {
  useEffect(() => {
    const secureContext = window.location.protocol === "https:" || ["localhost", "127.0.0.1"].includes(window.location.hostname);
    if ("serviceWorker" in navigator && secureContext) {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }
  }, []);
  return null;
}
