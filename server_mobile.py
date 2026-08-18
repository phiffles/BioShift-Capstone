"""
BS BioShifting — Mobile Server
==============================
The same application as `server.py`, served with a phone-app feel:
compact chrome, a fixed bottom tab bar, thumb-sized controls, safe-area
padding, and (on a desktop browser) a phone-shaped device frame so the
mobile build can be demoed without a handset.

Nothing here re-implements the product. `server.py` is imported as a
module, so the models, the database and every `/api/...` route are the
exact same objects — this file only re-serves the pages with a mobile
skin layered on top. The skin lives in this file as two strings served
from `/mobile/skin.css` and `/mobile/skin.js`, and is injected into each
HTML response, so no existing template, stylesheet or script is touched.

Run it alongside (or instead of) the desktop server:
    python server_mobile.py                 → http://127.0.0.1:5001
    python server_mobile.py --lan           → also reachable from a phone
    python server_mobile.py --lan --https   → needed for camera on a phone

Camera note: browsers only expose getUserMedia on a secure origin. That
means localhost is fine, but a phone hitting http://192.168.x.x will have
its camera blocked — use --https (self-signed; accept the warning) for
the live-scan screens on a real device.
"""

import argparse
import re
import socket

from flask import Flask, Response, render_template

# Importing the desktop server loads SAM, InsightFace, DEX and MediaPipe
# once, and initialises the database. Everything below reuses those.
import server

BASE_DIR = server.BASE_DIR

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)
app.config["MAX_CONTENT_LENGTH"] = server.app.config["MAX_CONTENT_LENGTH"]
app.config["TEMPLATES_AUTO_RELOAD"] = True


# ==============================================================
# MOBILE SKIN — CSS
# ==============================================================
MOBILE_CSS = r"""
/* ============================================================
   BS BioShifting — Mobile Skin
   Layered on top of style.css; only overrides what has to change
   to make the desktop layout behave like a native phone app.
   ============================================================ */

:root {
  --m-tabbar-h: 64px;
  --m-safe-top: env(safe-area-inset-top, 0px);
  --m-safe-bottom: env(safe-area-inset-bottom, 0px);
}

html, body {
  overscroll-behavior-y: contain;           /* kill rubber-band bounce */
  -webkit-text-size-adjust: 100%;
}
body {
  -webkit-tap-highlight-color: transparent; /* no grey flash on tap */
  touch-action: manipulation;               /* no 300ms double-tap zoom */
  /* Flat black instead of the desktop build's navy gradient. */
  background: #000;
}
:root[data-theme="light"] body { background: #FFF; }
/* Text selection on a phone means "I fumbled a drag", not "I want to copy". */
.topbar, .admin-topbar, .m-tabbar, .btn, .stepper, .direction-card,
.scan-card, .kpi, .eyebrow, .slider-labels { -webkit-user-select:none; user-select:none; }

/* ── shells ──────────────────────────────────────────────────
   dvh over vh: the address bar collapsing must not leave a gap. */
.app-shell, .admin-shell { min-height: 100dvh; }

/* ── topbar: shorter, and it holds the notch area ─────────── */
.topbar, .admin-topbar {
  padding: 12px 16px;
  padding-top: calc(12px + var(--m-safe-top));
}
.brand { font-size: 16px; }
.brand .mark { width: 30px; height: 30px; }
.icon-btn { width: 40px; height: 40px; }        /* 40px+ tap target */

/* ── content column ──────────────────────────────────────── */
.content { padding: 18px 16px 28px; max-width: 100%; }
.admin-content { padding: 20px 16px 28px; max-width: 100%; }
.form-content { max-width: 100%; }
body.m-has-tabs .content,
body.m-has-tabs .admin-content {
  padding-bottom: calc(var(--m-tabbar-h) + var(--m-safe-bottom) + 24px);
}
.h1 { font-size: 22px; }
.sub { font-size: 13px; }

/* ── controls sized for thumbs ───────────────────────────── */
.btn { padding: 15px 18px; min-height: 50px; font-size: 15px; border-radius: 12px; }
.btn-sm { min-height: 38px; padding: 8px 14px; }
.btn-row { gap: 8px; }
/* Hover states are sticky on touch devices — press feedback only. */
@media (hover: none) {
  .btn:hover, .icon-btn:hover, .direction-card:hover, .scan-card:hover { transform: none; }
  .btn:active { transform: scale(0.97); }
  .scan-card:active, .direction-card:active { background: var(--panel-2); }
}
/* 16px is the threshold below which iOS Safari zooms the page on focus. */
.input, select, textarea.input, input.slider-value { font-size: 16px; }
.input, select, textarea.input { padding: 13px 14px; border-radius: 10px; }
input[type=range] { height: 10px; }
input[type=range]::-webkit-slider-thumb { width: 26px; height: 26px; }
input[type=range]::-moz-range-thumb { width: 26px; height: 26px; }

/* ── cards / lists ───────────────────────────────────────── */
.card { border-radius: 14px; padding: 16px; }
.scan-card { flex-direction: column; align-items: flex-start; gap: 12px; padding: 15px; border-radius: 14px; }
.scan-card > * { width: 100%; }
.kpi-grid { grid-template-columns: repeat(2, 1fr); gap: 10px; }
.direction-grid { grid-template-columns: 1fr; }
.stat-grid, .compare-admin { grid-template-columns: 1fr; }
.compare-row { flex-direction: column; }
.history-drawer { width: 100%; right: -100%; }

/* ── wizard chrome ───────────────────────────────────────── */
.stepper { overflow-x: auto; padding-bottom: 4px; scrollbar-width: none; }
.stepper::-webkit-scrollbar { display: none; }
.bottom-bar {
  padding: 12px 16px calc(16px + var(--m-safe-bottom));
}
/* The stage is 3:4, so its width decides its height — size it off what is
   left of the screen once the header, buttons and tab bar have taken their
   share, or the capture button lands below the fold. */
.capture-stage { max-width: clamp(200px, calc((100dvh - 470px) * 0.75), 340px); }

/* The two mode buttons read as a segmented control rather than two stacked
   full-width buttons (which is what the base ≤768px rule would give). */
body.m-page-age-estimator .controls-row {
  flex-direction: row; align-items: stretch; gap: 6px;
  padding: 4px; border-radius: 12px;
  background: var(--panel); border: 1px solid var(--border-soft);
}
body.m-page-age-estimator .controls-row .btn { flex: 1; min-height: 42px; border-radius: 9px; }

/* ── admin header: brand + account on one row, tabs on the next ──
   Three stacked rows ate a third of the screen before the content began. */
.admin-topbar { flex-wrap: wrap; gap: 10px; }
.admin-topbar .topbar-left { flex: 1 1 auto; min-width: 0; }
.admin-topbar .brand {
  font-size: 15px; max-width: 100%;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
/* font-size:0 drops the bare "Ops Admin" text node — a name label is noise on
   a phone — while the avatar and the icon buttons keep their own sizing. */
.admin-topbar .admin-user { order: 2; flex: 0 0 auto; margin-left: auto; gap: 6px; font-size: 0; }
.admin-topbar .admin-user .avatar { font-size: 12px; }
.admin-topbar .admin-nav {
  order: 3; flex: 1 1 100%;
  padding-top: 10px; margin-top: -2px;
  border-top: 1px solid var(--border-soft);
}
.admin-nav {
  gap: 18px; overflow-x: auto; white-space: nowrap;
  scrollbar-width: none; -webkit-overflow-scrolling: touch;
}
.admin-nav::-webkit-scrollbar { display: none; }

/* Scroll indicator for the admin tab strip. The native bar is hidden above
   because every mobile platform draws it as a transient overlay — it appears
   only once you are already scrolling, which is exactly when you no longer
   need to be told the strip scrolls. This one is always on screen, and its
   thumb reports both how much is off-screen and where you are. */
.m-nav-scroll {
  order: 4; flex: 1 1 100%; position: relative;
  height: 3px; margin-top: 8px; border-radius: 2px;
  background: var(--border-soft); overflow: hidden;
}
.m-nav-scroll span {
  position: absolute; top: 0; bottom: 0; left: 0;
  border-radius: 2px; background: var(--text-faint);
}

/* ── bottom tab bar ──────────────────────────────────────── */
.m-tabbar {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 120;
  display: flex; align-items: stretch;
  height: calc(var(--m-tabbar-h) + var(--m-safe-bottom));
  padding-bottom: var(--m-safe-bottom);
  background: var(--topbar-bg);
  backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
  border-top: 1px solid var(--border-soft);
}
.m-tab {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 3px;
  color: var(--text-faint); font-size: 10px; font-weight: 600;
  letter-spacing: .04em; text-transform: uppercase;
  background: none; border: 0; padding: 0;
  transition: color .15s ease;
}
.m-tab svg { width: 21px; height: 21px; }
.m-tab.active { color: var(--accent); }
.m-tab.active svg { filter: drop-shadow(0 0 8px var(--accent-glow)); }
.m-tab:active { opacity: .6; }

/* ── desktop preview: render the whole app inside a handset ──
   Only kicks in on a screen too wide to read as a phone; a real
   device never sees any of this. */
@media (min-width: 900px) {
  body.m-framed { display: flex; align-items: center; justify-content: center; min-height: 100dvh; }
  .m-frame {
    position: relative; width: 412px; height: min(880px, 94dvh);
    background: #000;
    border: 12px solid #0a0e17;
    border-radius: 46px; overflow: hidden;
    box-shadow: 0 0 0 2px #1e2637, 0 40px 80px -20px rgba(0,0,0,.75);
    /* Own stacking context: the ambient layers below sit at z-index -1 in
       style.css and would otherwise escape behind the frame entirely. */
    isolation: isolate;
  }
  :root[data-theme="light"] .m-frame { background: #FFF; }
  /* The drifting portraits and the starfield belong to the app, so they move
     inside the handset — the desktop surround stays a flat, static backdrop.
     particles.js writes its own inline width/height from the window size, so
     the canvas keeps its natural scale here and the frame's overflow:hidden
     crops it to the screen instead of squashing it. */
  .m-frame #particles-canvas { position: absolute; top: 0; left: 0; z-index: 0; }
  .m-frame .tech-bg-container { position: absolute; inset: 0; z-index: 0; }
  .m-frame .m-viewport { z-index: 1; }
  /* The notch sits above the scroller so it never scrolls away. */
  .m-notch {
    position: absolute; top: 0; left: 50%; transform: translateX(-50%);
    width: 132px; height: 26px; background: #0a0e17;
    border-radius: 0 0 16px 16px; z-index: 200; pointer-events: none;
  }
  .m-viewport {
    position: absolute; inset: 0; overflow-y: auto; overflow-x: hidden;
    -webkit-overflow-scrolling: touch; scrollbar-width: none;
  }
  .m-viewport::-webkit-scrollbar { display: none; }
  /* Inside the frame, "full height" means the frame, not the monitor. */
  .m-viewport .app-shell, .m-viewport .admin-shell { min-height: 100%; }
  .m-viewport .topbar, .m-viewport .admin-topbar { padding-top: 32px; }
  /* fixed would attach to the monitor — pin these to the frame instead */
  .m-frame .m-tabbar { position: absolute; }
  .m-frame .boot-overlay { position: absolute; z-index: 190; }
  .m-frame .toast { position: absolute; bottom: calc(var(--m-tabbar-h) + 18px); }
  .m-viewport .capture-stage { max-width: 260px; }
  .m-viewport .content, .m-viewport .admin-content { padding-left: 18px; padding-right: 18px; }
}

@media (prefers-reduced-motion: reduce) {
  .m-tab, .btn { transition: none; }
}
"""


# ==============================================================
# MOBILE SKIN — JS
# ==============================================================
MOBILE_JS = r"""
/* BS BioShifting — mobile skin behaviour.
   Adds the bottom tab bar and, on a wide screen, wraps the page in a
   phone-shaped frame. Purely additive: it never rewrites page markup
   that the app's own scripts reach for by id. */
(function () {
  "use strict";

  var ICON = {
    home: '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    scan: '<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/><path d="M4 12h16"/>',
    age:  '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>'
  };

  // Operator-facing screens only. The admin console is deliberately absent:
  // this bar sits on the scan operator's home screen, and putting a one-tap
  // route to the review queue there advertises it to the wrong audience.
  // Administrators reach it the same way as on the desktop build, through
  // "Operations / Admin access" on the login screen.
  var TABS = [
    { label: "Home", href: "/home",          icon: "home", match: ["/home"] },
    { label: "Scan", href: "/scan",          icon: "scan", match: ["/scan"] },
    { label: "Age",  href: "/age-estimator", icon: "age",  match: ["/age-estimator"] }
  ];
  // Login screens are a dead end by design; the admin console has its own
  // navigation and no business showing operator tabs; and the scan wizard is a
  // modal task — it owns the bottom of the screen with its own Back/Next bar,
  // so a tab bar on top of that would both crowd it and invite a mid-scan
  // exit. (Its logo still links home, so the flow is never a trap.)
  var NO_TABS = ["/", "/admin-login", "/admin", "/scan"];

  var path = window.location.pathname.replace(/\/+$/, "") || "/";

  // Page-scoped hook for the few tweaks that must not leak to other screens.
  document.body.classList.add("m-page-" + (path === "/" ? "login" : path.slice(1)));

  function svg(d) {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
           'stroke-linecap="round" stroke-linejoin="round">' + d + "</svg>";
  }

  function buildTabBar() {
    if (NO_TABS.indexOf(path) !== -1) return null;
    var bar = document.createElement("nav");
    bar.className = "m-tabbar";
    bar.setAttribute("aria-label", "Primary");
    TABS.forEach(function (t) {
      var a = document.createElement("a");
      a.className = "m-tab" + (t.match.indexOf(path) !== -1 ? " active" : "");
      a.href = t.href;
      a.innerHTML = svg(ICON[t.icon]) + "<span>" + t.label + "</span>";
      bar.appendChild(a);
    });
    document.body.classList.add("m-has-tabs");
    return bar;
  }

  var tabBar = buildTabBar();
  if (tabBar) document.body.appendChild(tabBar);

  // ── Admin tab strip: visible scroll indicator ───────────────
  // Four tabs do not fit a phone width, and with the native overlay bar there
  // was nothing on screen to say so.
  function initNavScrollbar() {
    var nav = document.querySelector(".admin-topbar .admin-nav");
    if (!nav) return;
    var bar = document.createElement("div");
    bar.className = "m-nav-scroll";
    var thumb = document.createElement("span");
    bar.appendChild(thumb);
    nav.parentNode.insertBefore(bar, nav.nextSibling);

    function sync() {
      var visible = nav.clientWidth;
      var total = nav.scrollWidth;
      var hidden = total - visible;
      if (hidden < 2) { bar.style.display = "none"; return; }
      bar.style.display = "block";
      var ratio = visible / total;
      thumb.style.width = (ratio * 100).toFixed(2) + "%";
      thumb.style.left = ((nav.scrollLeft / hidden) * (1 - ratio) * 100).toFixed(2) + "%";
    }

    nav.addEventListener("scroll", sync, { passive: true });
    window.addEventListener("resize", sync);
    // Tab labels are laid out with a webfont; re-measure once it lands.
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(sync);
    sync();
  }

  initNavScrollbar();

  // ── Desktop device frame ────────────────────────────────────
  // Elements are moved, never recreated, so ids and any references the
  // page scripts already hold stay valid.
  var frameQuery = window.matchMedia("(min-width: 900px)");
  var frame = null;

  function pick(selector) {
    return Array.prototype.slice.call(document.querySelectorAll(selector));
  }

  function addFrame() {
    if (frame) return;
    frame = document.createElement("div");
    frame.className = "m-frame";
    var notch = document.createElement("div");
    notch.className = "m-notch";
    var viewport = document.createElement("div");
    viewport.className = "m-viewport";
    frame.appendChild(notch);
    frame.appendChild(viewport);
    document.body.appendChild(frame);

    // The ambient background layers move into the handset, so the desktop
    // surround stays flat and static while the app keeps its atmosphere.
    pick("body > #particles-canvas, body > .tech-bg-container").forEach(function (el) {
      frame.insertBefore(el, viewport);
    });
    // The page itself scrolls inside the frame…
    pick("body > .app-shell, body > .admin-shell").forEach(function (s) {
      viewport.appendChild(s);
    });
    // …while overlays anchored to <body> ride on the frame, or they would
    // paint across the whole monitor: the boot splash is fixed, and the login
    // screens park a loose theme toggle in the corner.
    pick("body > .boot-overlay, body > .icon-btn").forEach(function (el) {
      frame.appendChild(el);
    });
    if (tabBar) frame.appendChild(tabBar);
    // app.js creates the toast lazily on <body>; seeding an empty one inside
    // the frame means its querySelector finds this node and pops toasts on
    // the phone screen rather than in the corner of the desktop.
    var toast = document.querySelector(".toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.className = "toast";
    }
    frame.appendChild(toast);
    document.body.classList.add("m-framed");
  }

  function removeFrame() {
    if (!frame) return;
    var viewport = frame.querySelector(".m-viewport");
    Array.prototype.slice.call(viewport.children).forEach(function (s) {
      document.body.appendChild(s);
    });
    pick(".m-frame > .boot-overlay, .m-frame > .icon-btn, .m-frame > .toast," +
         ".m-frame > #particles-canvas, .m-frame > .tech-bg-container")
      .forEach(function (el) { document.body.appendChild(el); });
    if (tabBar) document.body.appendChild(tabBar);
    frame.remove();
    frame = null;
    document.body.classList.remove("m-framed");
  }

  function syncFrame() {
    if (frameQuery.matches) addFrame(); else removeFrame();
  }

  syncFrame();
  if (frameQuery.addEventListener) frameQuery.addEventListener("change", syncFrame);
  else if (frameQuery.addListener) frameQuery.addListener(syncFrame);

  // scrollIntoView() targets sit inside the frame's scroller on desktop and
  // inside the window on a phone — both are handled by the browser, but the
  // sticky topbar needs the offset either way.
  document.documentElement.style.scrollPaddingTop = "72px";
})();
"""


# ==============================================================
# SKIN DELIVERY
# ==============================================================
SKIN_MARKER = "/mobile/skin.css"

_HEAD_INJECT = (
    '<meta name="theme-color" content="#0F172A">\n'
    '<meta name="mobile-web-app-capable" content="yes">\n'
    '<meta name="apple-mobile-web-app-capable" content="yes">\n'
    '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">\n'
    f'<link rel="stylesheet" href="{SKIN_MARKER}">\n'
)
_BODY_INJECT = '<script src="/mobile/skin.js"></script>\n'

# The templates ship a desktop viewport tag; the mobile build needs the
# notch-aware variant so safe-area insets resolve to real numbers.
_VIEWPORT_RE = re.compile(r'<meta\s+name=["\']viewport["\'][^>]*>', re.I)
_VIEWPORT_TAG = ('<meta name="viewport" content="width=device-width, '
                 'initial-scale=1.0, viewport-fit=cover">')


@app.route("/mobile/skin.css")
def mobile_skin_css():
    return Response(MOBILE_CSS, mimetype="text/css")


@app.route("/mobile/skin.js")
def mobile_skin_js():
    return Response(MOBILE_JS, mimetype="application/javascript")


@app.after_request
def inject_mobile_skin(resp):
    """Splice the skin into every HTML page this server returns.

    Doing it here rather than in the templates keeps `templates/` byte-for-byte
    shared with the desktop server — one set of pages, two presentations.
    """
    if resp.direct_passthrough or resp.mimetype != "text/html":
        return resp
    html = resp.get_data(as_text=True)
    if SKIN_MARKER in html or "</head>" not in html:
        return resp
    html = _VIEWPORT_RE.sub(_VIEWPORT_TAG, html, count=1)
    html = html.replace("</head>", _HEAD_INJECT + "</head>", 1)
    html = html.replace("</body>", _BODY_INJECT + "</body>", 1)
    resp.set_data(html)
    return resp


# ==============================================================
# PAGE ROUTES (same templates, mobile presentation)
# ==============================================================
@app.route("/")
def index():
    return render_template("login.html")


@app.route("/home")
def home_page():
    return render_template("home.html")


@app.route("/scan")
def scan_page():
    return render_template("scan.html")


@app.route("/age-estimator")
def age_estimator_page():
    return render_template("age-estimator.html")


@app.route("/admin-login")
def admin_login_page():
    return render_template("admin-login.html")


@app.route("/admin")
def admin_page():
    return render_template("admin.html")


# ==============================================================
# SHARED ROUTES — mounted straight off the desktop server
# ==============================================================
_SHARED_PREFIXES = ("/api/", "/image_folder/")


def _mount_shared_routes():
    """Re-register `server.py`'s API and image routes on this app.

    The view functions are the same objects, so behaviour cannot drift
    between the two servers — there is exactly one implementation of the
    pipeline, and both front-ends call it.
    """
    for rule in server.app.url_map.iter_rules():
        if rule.endpoint == "static" or not rule.rule.startswith(_SHARED_PREFIXES):
            continue
        methods = sorted(rule.methods - {"HEAD", "OPTIONS"})
        app.add_url_rule(
            rule.rule,
            rule.endpoint,
            server.app.view_functions[rule.endpoint],
            methods=methods,
        )


_mount_shared_routes()
app.register_error_handler(413, server.handle_too_large)


# ==============================================================
# MAIN
# ==============================================================
def _lan_ip():
    """Best-effort LAN address to type into a phone. No traffic is sent —
    connect() on a UDP socket only picks the outbound interface."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def main():
    parser = argparse.ArgumentParser(description="BS BioShifting — mobile server")
    parser.add_argument("--port", type=int, default=5001, help="port (default 5001)")
    parser.add_argument("--lan", action="store_true",
                        help="bind 0.0.0.0 so a phone on the same Wi-Fi can connect")
    parser.add_argument("--https", action="store_true",
                        help="serve over self-signed TLS — required for the camera on a phone")
    args = parser.parse_args()

    host = "0.0.0.0" if args.lan else "127.0.0.1"
    scheme = "https" if args.https else "http"

    ssl_context = None
    if args.https:
        try:
            import ssl  # noqa: F401  (presence check only)
            ssl_context = "adhoc"
        except ImportError:
            ssl_context = None
        # Flask's "adhoc" certificates come from cryptography via werkzeug.
        try:
            import cryptography  # noqa: F401
        except ImportError:
            print("  [!] --https needs the 'cryptography' package: pip install cryptography")
            print("      Falling back to plain HTTP (the camera will be blocked on a phone).")
            ssl_context = None
            scheme = "http"

    ip = _lan_ip() if args.lan else None
    print()
    print("  +-----------------------------------------------+")
    print("  | BS BioShifting - MOBILE                       |")
    print(f"  |   {scheme}://127.0.0.1:{args.port}".ljust(48) + "|")
    if ip:
        print(f"  |   {scheme}://{ip}:{args.port}  (phone)".ljust(48) + "|")
    print("  +-----------------------------------------------+")
    if args.lan and scheme == "http":
        print("  Note: the camera stays blocked over plain http on a phone.")
        print("        Re-run with --https to use the live-scan screens.")
    print()
    app.run(host=host, port=args.port, debug=False, ssl_context=ssl_context)


if __name__ == "__main__":
    main()
