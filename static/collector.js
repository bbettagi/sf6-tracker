/* SF6 Tracker collector. Runs inside your logged-in Buckler's Boot Camp tab, reads your
   ranked battle log and sends it to the tracker on this computer. */
(async () => {
  const PORT = __PORT__;
  const TOKEN = "__TOKEN__";
  const SAVED_SID = __SID__;
  const box = document.createElement("div");
  box.style.cssText = "position:fixed;top:16px;right:16px;z-index:2147483647;max-width:380px;padding:12px 16px;" +
    "border-radius:10px;background:#1a1a19;color:#f0efec;font:14px/1.45 system-ui,sans-serif;box-shadow:0 4px 20px rgba(0,0,0,.35)";
  document.body.appendChild(box);
  const say = (msg) => { box.textContent = "SF6 Tracker: " + msg; };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    if (!/(^|\.)streetfighter\.com$/.test(location.hostname) || !location.pathname.startsWith("/6/buckler")) {
      throw new Error("open Buckler's Boot Camp (streetfighter.com/6/buckler) while logged in, then run this again.");
    }
    const el = document.getElementById("__NEXT_DATA__");
    if (!el) throw new Error("this doesn't look like a Buckler page. Reload it and try again.");
    const next = JSON.parse(el.textContent);
    const fromPage = (next.props && next.props.pageProps && next.props.pageProps.sid) ||
      (next.query && next.query.sid) || (location.pathname.match(/profile\/(\d+)/) || [])[1];
    let sid = String(SAVED_SID || fromPage || "");
    if (!sid) sid = (prompt("Your Buckler user code (the number in your profile URL):") || "").trim();
    if (!/^\d+$/.test(sid)) throw new Error("no user code given.");

    const base = `${location.origin}/6/buckler/_next/data/${next.buildId}/${next.locale || "en"}/profile/${sid}/battlelog/rank.json`;
    const replays = [];
    let total = 1;
    for (let page = 1; page <= Math.min(total, 10); page++) {
      say(`reading ranked battle log, page ${page}${total > 1 ? ` of ${Math.min(total, 10)}` : ""}…`);
      const res = await fetch(`${base}?page=${page}&sid=${sid}`, { credentials: "same-origin", headers: { accept: "application/json" } });
      if (res.status === 404) throw new Error("Buckler has been updated since this page loaded. Reload the page and run the collector again.");
      if (!res.ok) throw new Error(`Buckler returned HTTP ${res.status}. Make sure you're logged in.`);
      const data = await res.json();
      const props = data.pageProps || {};
      if (props.__N_REDIRECT) throw new Error("Buckler wants you to log in first.");
      total = props.total_page || 1;
      const list = props.replay_list || [];
      if (!list.length) break;
      replays.push(...list);
      if (page < Math.min(total, 10)) await sleep(600 + Math.random() * 600);
    }
    if (!replays.length) throw new Error("Buckler returned no ranked matches for this user code.");

    const payload = { kind: "sf6-tracker-import", sid: Number(sid), collected_at: Date.now(), replay_list: replays };
    say(`read ${replays.length} ranked matches, sending them to the tracker…`);
    try {
      const res = await fetch(`http://localhost:${PORT}/api/import`, {
        method: "POST",
        headers: { "Content-Type": "text/plain" },
        body: JSON.stringify({ ...payload, token: TOKEN }),
      });
      const out = await res.json();
      if (!res.ok) throw new Error(out.error || `HTTP ${res.status}`);
      say(`done. ${out.added} new ranked match${out.added === 1 ? "" : "es"} added (${out.ranked} read). You can close this.`);
    } catch (err) {
      const blob = new Blob([JSON.stringify(payload)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `sf6-ranked-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      say(`couldn't reach the tracker at localhost:${PORT} (${err.message}). Saved ${replays.length} matches to a file instead: import it on the tracker's Sync tab.`);
    }
  } catch (err) {
    say(err.message);
  }
  setTimeout(() => box.remove(), 20000);
})();
