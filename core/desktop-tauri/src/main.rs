//! Amadeus on the desktop, one process that stays running:
//! - The mini core (web/mini.html): transparent, always on top, only the core. It speaks in bubbles (their own small
//!   window, web/bubble.html) and "calls" you;
//!   clicks where nothing is drawn reach the desktop. Clicking the core opens the dashboard.
//! - The dashboard (web/index.html), opened from the mini core, the tray or the `amadeus` command.
//! - The tray icon: the "dot shell" in the theme's colour, an amber dot that beats during a call, small bars while she
//!   speaks, a slashed look when the microphone is off. Its menu has the core, the dashboard, approvals and the wake word.
//! A closed window is really gone, so nothing draws or runs behind it. The core tells this app what to show through a
//! long-running request (core/amadeus_core/desktop.py), which works the same on every system.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use tauri::image::Image;
use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent};

const UA: &str = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/605.1.15 (KHTML, like Gecko) AmadeusDesktop/1";
// The mini core: the core and the small pill of buttons, so it can go right up to the edge of the screen. Without KDE's
// window scripts the speech bubble stays in this window, which is then taller.
const MW: f64 = 300.0;
const MH: f64 = 340.0;
const MH_TALL: f64 = 480.0;
const BUBBLE_H: f64 = 150.0; // a little more when it sits below the core: that's how the page knows (web/mini.css)
const BUBBLE_TITLE: &str = "Amadeus bubble";
const MINI_TITLE: &str = "Amadeus core";
const DASH_TITLE: &str = "Amadeus";
// The pages talk to their window through window.amadeusBridge (web/mini.js, web/hud.js).
const BRIDGE: &str = r#"
window.amadeusBridge = { postMessage: (msg) => window.__TAURI_INTERNALS__.invoke("native", { msg: String(msg) }) };
addEventListener("error", (e) => console.error("JS error: " + e.message + " @" + e.lineno));
addEventListener("unhandledrejection", (e) => console.error("JS rejection: " + e.reason));
"#;
const SVG_NORMAL: &str = include_str!("../../web/tray/amadeus-tray.svg");
const SVG_CALL: &str = include_str!("../../web/tray/amadeus-tray-call.svg");
const SVG_SPEAKING: &str = include_str!("../../web/tray/amadeus-tray-speaking.svg");
const SVG_VOICE_OFF: &str = include_str!("../../web/tray/amadeus-tray-voice-off.svg");

fn config() -> Value {
    let home = std::env::var("HOME").unwrap_or_default();
    fs::read_to_string(PathBuf::from(home).join(".config/amadeus-core/config.json")).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(json!({}))
}

fn data_dir() -> PathBuf {
    match config()["data_dir"].as_str() {
        Some(d) => PathBuf::from(d),
        None => PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".local/share/amadeus/core"),
    }
}

fn base() -> String {
    format!("http://127.0.0.1:{}", config()["port"].as_u64().unwrap_or(8095))
}

fn token() -> String {
    fs::read_to_string(data_dir().join("token")).unwrap_or_default().trim().to_string()
}

/// You closed the mini core: it only comes back for a call, the wake word or the tray.
fn hidden_flag() -> PathBuf {
    data_dir().join("mini-hidden")
}

fn is_local(url: &tauri::Url) -> bool {
    url.scheme() == "about" || url.host_str() == Some("127.0.0.1")
}

// What the tray icon shows: only while it's really happening (a call rings, she speaks). The pages say so.
static CALLING: AtomicBool = AtomicBool::new(false);
static SPEAKING: AtomicBool = AtomicBool::new(false);
static PILL_TOP: AtomicBool = AtomicBool::new(false); // the core is so low that there's no room under it

#[derive(Default)]
struct Shared {
    zones: Arc<Mutex<Vec<[f64; 4]>>>, // the mini core's buttons and bubbles: clicks there aren't a drag
    crashes: Mutex<Vec<Instant>>,
}

// ---------- the windows ----------

/// The address that signs a window in (a cookie) and then goes on to a page.
fn login(path: &str) -> WebviewUrl {
    let next = path.replace('%', "%25").replace('#', "%23").replace('?', "%3F").replace('&', "%26").replace('=', "%3D");
    WebviewUrl::External(format!("{}/?token={}&next={next}", base(), token()).parse().expect("a valid address"))
}

fn window<'a>(app: &'a AppHandle, label: &str, title: &str, path: &str) -> WebviewWindowBuilder<'a, tauri::Wry, AppHandle> {
    WebviewWindowBuilder::new(app, label, login(path))
        .title(title)
        .decorations(false)
        .user_agent(UA)
        .data_directory(data_dir().join("webview"))
        .initialization_script(BRIDGE)
        // links to the web open in the normal browser, never inside these windows
        .on_navigation(|url| {
            let local = is_local(url);
            if !local {
                let _ = open::that_detached(url.as_str());
            }
            local
        })
        .on_new_window(|url, _| {
            let _ = open::that_detached(url.as_str());
            tauri::webview::NewWindowResponse::Deny
        })
}

fn show_mini(app: &AppHandle, call: bool) -> tauri::Result<()> {
    if !call {
        let _ = fs::remove_file(hidden_flag());
    }
    if let Some(w) = app.get_webview_window("mini") {
        if call {
            w.eval("window.amadeusShown && window.amadeusShown('call')")?;
        }
        return w.show();
    }
    let path = if call { "/mini.html?call=1" } else { "/mini.html" };
    let w = window(app, "mini", MINI_TITLE, path)
        .inner_size(MW, if kde() { MH } else { MH_TALL })
        .transparent(true)
        .always_on_top(true)
        .skip_taskbar(true)
        .shadow(false)
        .build()?;
    prepare(&w)?;
    make_bubble(app)?;
    tell_core_open(true);
    Ok(())
}

/// Gone, not just hidden: nothing runs or draws while it's closed.
fn close_mini(app: &AppHandle, by_you: bool) {
    if by_you {
        let _ = fs::write(hidden_flag(), "");
    }
    destroy_mini(app);
}

fn destroy_mini(app: &AppHandle) {
    CALLING.store(false, Ordering::Relaxed);
    SPEAKING.store(false, Ordering::Relaxed);
    for label in ["bubble", "mini"] {
        if let Some(w) = app.get_webview_window(label) {
            let _ = w.destroy();
        }
    }
}

/// The speech bubble is its own window, ready and hidden, so the core never resizes for it. The KWin script below keeps
/// it above the core (or below, near the top of the screen).
fn make_bubble(app: &AppHandle) -> tauri::Result<()> {
    if !kde() || app.get_webview_window("bubble").is_some() {
        return Ok(());
    }
    let w = window(app, "bubble", BUBBLE_TITLE, "/bubble.html")
        .inner_size(MW, BUBBLE_H)
        .transparent(true)
        .always_on_top(true)
        .skip_taskbar(true)
        .shadow(false)
        .focused(false)
        .visible(false)
        .build()?;
    prepare(&w)
}

fn set_bubble(app: &AppHandle, html: &str) {
    let Some(w) = app.get_webview_window("bubble") else { return };
    let _ = if html.is_empty() { w.hide() } else { w.show() };
    let _ = w.eval(&format!("window.amadeusSetBubble && window.amadeusSetBubble({})", json!(html)));
}

fn tell_pill(app: &AppHandle) {
    if let Some(mini) = app.get_webview_window("mini") {
        let _ = mini.eval(&format!("window.amadeusPillTop && window.amadeusPillTop({})", PILL_TOP.load(Ordering::Relaxed)));
    }
}

/// The KWin script below calls this when the core goes too low for the pill under it.
struct KwinBridge(AppHandle);

#[zbus::interface(name = "com.amadeus.Desktop")]
impl KwinBridge {
    #[zbus(name = "PillOnTop")]
    fn pill_on_top(&self, on: bool) {
        PILL_TOP.store(on, Ordering::Relaxed);
        let a = self.0.clone();
        let _ = self.0.run_on_main_thread(move || tell_pill(&a));
    }
}

/// Keeps the name on the session bus while the app runs.
fn serve_kwin_bridge(app: AppHandle) {
    std::thread::spawn(move || {
        let conn = zbus::blocking::connection::Builder::session()
            .and_then(|b| b.name("com.amadeus.Desktop"))
            .and_then(|b| b.serve_at("/", KwinBridge(app)))
            .and_then(|b| b.build());
        match conn {
            Ok(c) => {
                load_bubble_script(); // (its first call needs the name to be there)
                loop {
                    std::thread::sleep(Duration::from_secs(3600));
                    let _ = c.unique_name();
                }
            }
            Err(e) => eprintln!("KWin bridge: {e}"),
        }
    });
}

/// Stays loaded while the app runs: places the bubble the moment it opens, before you can see it, and moves it along
/// when you drag the core.
fn load_bubble_script() {
    let file = data_dir().join("place-bubble.js");
    let script = format!(
        r#"function find(t) {{ return workspace.windowList().find((w) => w.resourceClass == "amadeus-call" && w.caption == t); }}
let low = null;
function place() {{
  const core = find("{MINI_TITLE}"), b = find("{BUBBLE_TITLE}");
  if (!core) return;
  const g = core.frameGeometry, a = workspace.clientArea(KWin.MaximizeArea, core.output, workspace.currentDesktop), up = g.y - a.y >= {BUBBLE_H};
  const isLow = g.y + g.height > a.y + a.height;
  if (isLow !== low) {{ low = isLow; callDBus("com.amadeus.Desktop", "/", "com.amadeus.Desktop", "PillOnTop", isLow); }}
  if (!b) return;
  b.keepAbove = true; b.skipTaskbar = true; b.skipPager = true; b.skipSwitcher = true;
  const y = up ? g.y - {BUBBLE_H} : g.y + g.height, h = up ? {BUBBLE_H} : {BUBBLE_H} + 6, f = b.frameGeometry;
  if (Math.abs(f.x - g.x) > 1 || Math.abs(f.y - y) > 1 || Math.abs(f.height - h) > 1) b.frameGeometry = {{ x: g.x, y: y, width: g.width, height: h }};
}}
function watch(w) {{
  if (w.resourceClass != "amadeus-call") return;
  w.frameGeometryChanged.connect(place); // (a new window has no title yet, so all of ours)
  w.captionChanged.connect(place);
  place();
}}
workspace.windowAdded.connect(watch);
workspace.windowList().forEach(watch);"#
    );
    if fs::write(&file, script).is_err() {
        return;
    }
    // KWin doesn't run a new script under a name it has just unloaded, so each start of the app has its own name
    let names = data_dir().join("place-bubble.name");
    let cmd = format!(
        "old=$(cat '{0}' 2>/dev/null); [ -n \"$old\" ] && qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript \"$old\" >/dev/null 2>&1; sleep 1; \
         n=amadeus-bubble-$$; echo $n > '{0}'; \
         id=$(qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript '{1}' $n) && \
         qdbus6 org.kde.KWin /Scripting/Script$id org.kde.kwin.Script.run >/dev/null",
        names.display(),
        file.display()
    );
    let _ = std::process::Command::new("sh").arg("-c").arg(cmd).stdout(std::process::Stdio::null()).stderr(std::process::Stdio::null()).spawn();
}

fn show_dash(app: &AppHandle, path: &str) -> tauri::Result<()> {
    destroy_mini(app); // the mini core steps aside while the dashboard is open
    if let Some(w) = app.get_webview_window("dash") {
        w.navigate(format!("{}{path}", base()).parse().expect("a valid address"))?;
        w.show()?;
        bring_dash_forward(None);
        return w.set_focus();
    }
    let (mut width, mut height) = (1200.0, 800.0);
    if let Ok(Some(m)) = app.primary_monitor() {
        let size = m.size().to_logical::<f64>(m.scale_factor());
        (width, height) = ((size.width * 0.72).min(1500.0).round(), (size.height * 0.82).min(950.0).round());
    }
    let w = window(app, "dash", DASH_TITLE, path).inner_size(width, height).center().build()?;
    prepare(&w)?;
    tell_core_open(true);
    bring_dash_forward(Some((width, height)));
    w.set_focus()
}

fn close_dash(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("dash") {
        let _ = w.destroy();
    }
    if !hidden_flag().exists() {
        let _ = show_mini(app, false); // back to the mini core (unless you closed it)
    }
}

fn kde() -> bool {
    std::env::var("XDG_CURRENT_DESKTOP").unwrap_or_default().to_uppercase().contains("KDE")
}

/// Wayland apps can't place themselves or come to the front: on KDE a short KWin script does. (The mini core also has
/// the rule from desktop/install-kwin-rule.sh, which keeps it on top and remembers where you dragged it.)
fn kwin(script: &str, wait: f64) {
    static RUNS: AtomicU32 = AtomicU32::new(0); // each run has its own file: they can overlap
    let file = data_dir().join(format!("place-window-{}.js", RUNS.fetch_add(1, Ordering::Relaxed)));
    if fs::write(&file, script).is_err() {
        return;
    }
    let cmd = format!(
        "sleep {wait}; n=amadeus-place-$$; \
         id=$(qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript '{0}' $n) && \
         qdbus6 org.kde.KWin /Scripting/Script$id org.kde.kwin.Script.run >/dev/null; sleep 1; \
         qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript $n >/dev/null 2>&1; rm -f '{0}'",
        file.display()
    );
    let _ = std::process::Command::new("sh").arg("-c").arg(cmd).stdout(std::process::Stdio::null()).stderr(std::process::Stdio::null()).spawn();
}

/// To the front; a new dashboard also in the middle of the screen.
fn bring_dash_forward(center: Option<(f64, f64)>) {
    if !kde() {
        return;
    }
    let place = center.map_or(String::new(), |(width, height)| {
        format!("const a = workspace.clientArea(KWin.MaximizeArea, workspace.activeScreen, workspace.currentDesktop);
           w.frameGeometry = {{ x: Math.round(a.x + (a.width - {width}) / 2), y: Math.round(a.y + (a.height - {height}) / 2), width: {width}, height: {height} }};")
    });
    kwin(&format!(
        "for (const w of workspace.windowList()) if (w.resourceClass == \"amadeus-call\" && w.caption == \"{DASH_TITLE}\") {{
           {place}
           workspace.activeWindow = w;
         }}"
    ), 0.3);
}

/// What only this system can do: the microphone and speaking without a click first, reloading a crashed page, moving
/// the windows by their edge or top bar.
#[cfg(target_os = "linux")]
fn prepare(w: &WebviewWindow) -> tauri::Result<()> {
    use gtk::gdk::EventType;
    use gtk::glib::Propagation;
    use gtk::prelude::*;
    use webkit2gtk::{PermissionRequestExt, SettingsExt, UserMediaPermissionRequest, WebViewExt};
    let win = w.clone();
    w.with_webview(move |pv| {
        let view = pv.inner();
        if let Some(st) = WebViewExt::settings(&view) {
            st.set_enable_media_stream(true);
            st.set_media_playback_requires_user_gesture(false);
            st.set_enable_write_console_messages_to_stdout(true);
        }
        // only Amadeus' own pages run here: the microphone is allowed, everything else refused
        view.connect_permission_request(|_, req| {
            if req.downcast_ref::<UserMediaPermissionRequest>().is_some() {
                req.allow();
            } else {
                req.deny();
            }
            true
        });
        let app = win.app_handle().clone();
        view.connect_web_process_terminated(move |v, reason| {
            println!("web process terminated: {reason:?}");
            if crashed_too_often(&app) {
                let _ = fs::write(software_flag(), "");
                app.restart();
            }
            v.reload();
        });
        let Ok(gw) = win.gtk_window() else { return };
        if win.label() == "bubble" {
            return;
        }
        if win.label() == "mini" {
            let zones = win.state::<Shared>().zones.clone();
            let gw2 = gw.clone();
            view.connect_button_press_event(move |_, ev| {
                let (x, y) = ev.position();
                let top = if gw2.allocated_height() as f64 == MH_TALL { 150.0 } else { 10.0 }; // web/mini.css
                let (cx, cy, r) = (MW / 2.0, top + 140.0, 280.0 / 2.0 / 1.5 * 1.15); // the sphere: click and hold
                let on_sphere = (x - cx).powi(2) + (y - cy).powi(2) <= r * r;
                let on_zone = zones.lock().unwrap().iter().any(|z| x >= z[0] && x <= z[0] + z[2] && y >= z[1] && y <= z[1] + z[3]);
                if ev.button() != 1 || ev.event_type() != EventType::ButtonPress || on_sphere || on_zone {
                    return Propagation::Proceed;
                }
                let (rx, ry) = ev.root();
                gw.begin_move_drag(1, rx as i32, ry as i32, ev.time());
                Propagation::Stop
            });
        } else {
            // the top bar (52 px, right of the rail, left of the clock and X) moves it; a double click maximizes
            view.connect_button_press_event(move |_, ev| {
                let (x, y) = ev.position();
                if ev.button() != 1 || !(x > 64.0 && x < gw.allocated_width() as f64 - 170.0 && y < 52.0) {
                    return Propagation::Proceed;
                }
                match ev.event_type() {
                    EventType::DoubleButtonPress => {
                        if gw.is_maximized() {
                            gw.unmaximize();
                        } else {
                            gw.maximize();
                        }
                        Propagation::Stop
                    }
                    EventType::ButtonPress => {
                        let (rx, ry) = ev.root();
                        gw.begin_move_drag(1, rx as i32, ry as i32, ev.time());
                        Propagation::Stop
                    }
                    _ => Propagation::Proceed,
                }
            });
        }
    })
}

#[cfg(not(target_os = "linux"))]
fn prepare(_w: &WebviewWindow) -> tauri::Result<()> {
    Ok(())
}

/// Clicks only where something is drawn (the core, the bubbles); everywhere else they reach the desktop.
#[cfg(target_os = "linux")]
fn set_shape(w: &WebviewWindow, rects: &[[f64; 4]]) {
    use gtk::cairo::{RectangleInt, Region};
    use gtk::prelude::*;
    let list: Vec<RectangleInt> = rects.iter().map(|r| RectangleInt::new(r[0].max(0.0) as i32, r[1].max(0.0) as i32, r[2].max(1.0) as i32, r[3].max(1.0) as i32)).collect();
    if let Ok(gw) = w.gtk_window() {
        gw.input_shape_combine_region(Some(&Region::create_rectangles(&list)));
    }
}

#[cfg(not(target_os = "linux"))]
fn set_shape(_w: &WebviewWindow, _rects: &[[f64; 4]]) {}

/// Drawing without the GPU (the slow, CPU-only way) is only for graphics drivers where WebKit's GPU drawing crashes:
/// "gpu_rendering": false in the config, or automatically after the page crashed a few times in a row (this marker
/// file; delete it to try the GPU again).
fn software_flag() -> PathBuf {
    data_dir().join("popup-software-rendering")
}

#[cfg(target_os = "linux")]
fn crashed_too_often(app: &AppHandle) -> bool {
    let shared = app.state::<Shared>();
    let mut crashes = shared.crashes.lock().unwrap();
    crashes.retain(|t| t.elapsed() < Duration::from_secs(120));
    crashes.push(Instant::now());
    crashes.len() >= 3 && std::env::var("WEBKIT_DISABLE_DMABUF_RENDERER").is_err()
}

/// Messages from the pages.
#[tauri::command]
fn native(app: AppHandle, window: WebviewWindow, msg: String) {
    let a = app.clone();
    let w = window.clone();
    let _ = app.run_on_main_thread(move || {
        let m = msg.as_str();
        let done = if m == "close" {
            close_mini(&a, true);
            Ok(())
        } else if m == "hide" {
            close_mini(&a, false); // a call is over: back to how it was
            Ok(())
        } else if m == "mini" {
            let _ = fs::remove_file(hidden_flag());
            close_dash(&a);
            Ok(())
        } else if m == "quit" {
            // the X: the windows close, the tray icon stays (a click there brings the core back)
            let _ = fs::write(hidden_flag(), "");
            for w in a.webview_windows().values() {
                let _ = w.destroy();
            }
            Ok(())
        } else if let Some(html) = m.strip_prefix("bubble:") {
            set_bubble(&a, html);
            Ok(())
        } else if m == "calling:1" || m == "calling:0" {
            CALLING.store(m.ends_with('1'), Ordering::Relaxed);
            Ok(())
        } else if m == "speaking:1" || m == "speaking:0" {
            SPEAKING.store(m.ends_with('1'), Ordering::Relaxed);
            Ok(())
        } else if m == "pill?" {
            tell_pill(&a);
            Ok(())
        } else if m == "bubble-ready" {
            if let Some(mini) = a.get_webview_window("mini") {
                let _ = mini.eval("window.amadeusBubbleReady && window.amadeusBubbleReady()");
            }
            Ok(())
        } else if let Some(act) = m.strip_prefix("bubble-click:") {
            if let Some(mini) = a.get_webview_window("mini") {
                let _ = mini.eval(&format!("window.amadeusBubbleClick && window.amadeusBubbleClick({})", json!(act)));
            }
            Ok(())
        } else if let Some(path) = m.strip_prefix("dash:") {
            show_dash(&a, if path.is_empty() { "/#home" } else { path })
        } else if let Some(path) = m.strip_prefix("open:") {
            w.navigate(format!("{}{path}", base()).parse().expect("a valid address"))
        } else if let Some(list) = m.strip_prefix("shape:") {
            if let Ok(rects) = serde_json::from_str::<Vec<[f64; 4]>>(list) {
                set_shape(&w, &rects);
            }
            Ok(())
        } else if let Some(list) = m.strip_prefix("zones:") {
            if let Ok(zones) = serde_json::from_str::<Vec<[f64; 4]>>(list) {
                *a.state::<Shared>().zones.lock().unwrap() = zones;
            }
            Ok(())
        } else {
            Ok(())
        };
        if let Err(e) = done {
            eprintln!("{msg}: {e}");
        }
    });
}

// ---------- the core tells us what to show ----------

fn api(path: &str) -> ureq::Request {
    ureq::get(&format!("{}{path}", base())).set("authorization", &format!("Bearer {}", token())).timeout(Duration::from_secs(5))
}

/// The core only "calls" through a new window when none is open: an open one looks for new events itself.
fn tell_core_open(open: bool) {
    std::thread::spawn(move || {
        let _ = ureq::post(&format!("{}/api/desktop/state", base()))
            .set("authorization", &format!("Bearer {}", token()))
            .timeout(Duration::from_secs(5))
            .send_json(json!({ "open": open }));
    });
}

fn on_wake(app: &AppHandle, data: &Value) {
    // the dashboard listens if it's in front, else the mini core
    let js = format!("window.amadeusWake && window.amadeusWake({data})");
    if let Some(d) = app.get_webview_window("dash") {
        if d.is_focused().unwrap_or(false) {
            let _ = d.eval(&js);
            return;
        }
    }
    if let Some(m) = app.get_webview_window("mini") {
        let _ = m.eval(&js);
        return;
    }
    if data["stage"] == "cancel" {
        return;
    }
    let _ = show_mini(app, false);
    let a = app.clone();
    std::thread::spawn(move || {
        std::thread::sleep(Duration::from_millis(1500)); // the page needs a moment to load
        if let Some(m) = a.get_webview_window("mini") {
            let _ = m.eval(&js);
        }
    });
}

fn listen(app: AppHandle) {
    let mut lost = true;
    loop {
        let reply = api("/api/desktop/wait").timeout(Duration::from_secs(45)).call().and_then(|r| Ok(r.into_json::<Value>()?));
        let Ok(reply) = reply else {
            lost = true;
            std::thread::sleep(Duration::from_secs(3));
            continue;
        };
        if lost {
            lost = false; // the core (re)started: it doesn't know about our windows yet
            tell_core_open(app.webview_windows().keys().any(|l| l != "bubble"));
        }
        for cmd in reply["cmds"].as_array().cloned().unwrap_or_default() {
            let a = app.clone();
            let _ = app.run_on_main_thread(move || match cmd["do"].as_str() {
                Some("call") if a.webview_windows().keys().all(|l| l == "bubble") => drop(show_mini(&a, true)),
                Some("wake") => on_wake(&a, &cmd["data"]),
                _ => {}
            });
        }
    }
}

// ---------- the tray icon ----------

/// A tray icon in the theme's main colour (web/themes.js).
fn tray_icon(svg: &str, theme: &str) -> Option<Image<'static>> {
    let colour = match theme {
        "purple" => "#B68CFF",
        "red" => "#FF5260",
        _ => "#5FD8FF",
    };
    let tree = resvg::usvg::Tree::from_str(&svg.replace("#5FD8FF", colour), &Default::default()).ok()?;
    let mut pixmap = resvg::tiny_skia::Pixmap::new(64, 64)?;
    let scale = 64.0 / tree.size().width();
    resvg::render(&tree, resvg::tiny_skia::Transform::from_scale(scale, scale), &mut pixmap.as_mut());
    let rgba = pixmap.pixels().iter().flat_map(|p| {
        let c = p.demultiply();
        [c.red(), c.green(), c.blue(), c.alpha()]
    });
    Some(Image::new_owned(rgba.collect(), 64, 64))
}

fn tray(app: &AppHandle) -> tauri::Result<()> {
    let off_file = data_dir().join("wake-off");
    let toggle = MenuItem::with_id(app, "toggle", "Show or hide the core", true, None::<&str>)?;
    let dash = MenuItem::with_id(app, "dash", "Open dashboard", true, None::<&str>)?;
    let appr = MenuItem::with_id(app, "approvals", "Approvals", true, None::<&str>)?;
    let rem = MenuItem::with_id(app, "reminders", "Reminders", true, None::<&str>)?;
    let wake = CheckMenuItem::with_id(app, "wake", "Wake word", true, !off_file.exists(), None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
    let line = PredefinedMenuItem::separator(app)?;
    let line2 = PredefinedMenuItem::separator(app)?;
    let wake2 = wake.clone();
    let off = off_file.clone();
    let icon = tray_icon(SVG_NORMAL, "blue").expect("the tray icon");
    let t = TrayIconBuilder::with_id("main")
        .icon(icon)
        .tooltip("Amadeus")
        .menu(&Menu::with_items(app, &[&toggle, &dash, &appr, &rem, &line, &wake, &line2, &quit])?)
        .on_menu_event(move |app, ev| match ev.id.as_ref() {
            "toggle" => {
                if app.get_webview_window("mini").is_some() {
                    close_mini(app, true);
                } else {
                    let _ = show_mini(app, false);
                }
            }
            "dash" => drop(show_dash(app, "/#home")),
            "approvals" => drop(show_dash(app, "/#approvals")),
            "reminders" => drop(show_dash(app, "/#reminders")),
            "wake" => {
                let _ = if wake2.is_checked().unwrap_or(true) { fs::remove_file(&off) } else { fs::write(&off, "") };
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .build(app)?;
    // every few beats a look at what's going on
    std::thread::spawn(move || {
        let (mut theme, mut beat, mut shown, mut tick) = ("blue".to_string(), false, (String::new(), ""), 0);
        loop {
            if tick % 5 == 0 {
                let _ = wake.set_checked(!off_file.exists()); // it may have been switched by voice or chat ("voice off")
                if let Some(t) = api("/api/theme").call().ok().and_then(|r| r.into_json::<Value>().ok()) {
                    theme = t["theme"].as_str().unwrap_or("blue").to_string();
                }
                let n = api("/api/approvals?status=pending").call().ok().and_then(|r| r.into_json::<Value>().ok()).and_then(|l| l.as_array().map(Vec::len));
                let _ = appr.set_text(match n {
                    Some(n) if n > 0 => format!("Approvals ({n} waiting)"),
                    _ => "Approvals".to_string(),
                });
            }
            tick += 1;
            let calling = CALLING.load(Ordering::Relaxed);
            beat = calling && !beat;
            let svg = if calling {
                if beat { SVG_CALL } else { SVG_NORMAL } // the amber dot beats
            } else if SPEAKING.load(Ordering::Relaxed) {
                SVG_SPEAKING
            } else if off_file.exists() {
                SVG_VOICE_OFF
            } else {
                SVG_NORMAL
            };
            if shown != (theme.clone(), svg) {
                shown = (theme.clone(), svg);
                let _ = t.set_icon(tray_icon(svg, &theme));
            }
            std::thread::sleep(Duration::from_millis(950));
        }
    });
    Ok(())
}

// ---------- start ----------

/// amadeus-desktop /#path   the dashboard at a page, e.g. /#approvals
/// amadeus-desktop --mini   the mini core
/// Without anything it starts with the mini core (unless you closed it). A running app is handed the request.
fn handle(app: &AppHandle, arg: Option<&String>) {
    match arg {
        Some(a) if a.starts_with('/') => drop(show_dash(app, a)),
        Some(a) if a == "--mini" => drop(show_mini(app, false)),
        _ => {}
    }
}

fn main() {
    if config()["gpu_rendering"] == json!(false) || software_flag().exists() {
        std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
    }
    #[cfg(target_os = "linux")]
    gtk::glib::set_prgname(Some("amadeus-call")); // the Wayland app id the KWin rule matches
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, args, _| handle(app, args.get(1))))
        .manage(Shared::default())
        .invoke_handler(tauri::generate_handler![native])
        .on_window_event(|w, ev| match ev {
            WindowEvent::CloseRequested { api, .. } => {
                api.prevent_close();
                let app = w.app_handle();
                if w.label() == "dash" {
                    close_dash(app);
                } else if w.label() == "bubble" {
                    let _ = w.hide();
                } else {
                    close_mini(app, true);
                }
            }
            WindowEvent::Destroyed => {
                if w.label() != "bubble" {
                    CALLING.store(false, Ordering::Relaxed);
                    SPEAKING.store(false, Ordering::Relaxed);
                }
                let left = w.app_handle().webview_windows().keys().filter(|l| l.as_str() != w.label() && l.as_str() != "bubble").count();
                tell_core_open(left > 0);
            }
            _ => {}
        })
        .setup(|app| {
            let h = app.handle().clone();
            tray(&h)?;
            if kde() {
                serve_kwin_bridge(h.clone());
            }
            let arg = std::env::args().nth(1);
            if arg.is_some() {
                handle(&h, arg.as_ref());
            } else if !hidden_flag().exists() {
                show_mini(&h, false)?;
            }
            std::thread::spawn(move || listen(h));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("the desktop app")
        .run(|_, ev| {
            if let tauri::RunEvent::ExitRequested { api, code, .. } = ev {
                if code.is_none() {
                    api.prevent_exit(); // no window open is normal: the tray icon stays
                }
            }
        });
}
