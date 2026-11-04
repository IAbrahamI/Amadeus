//! A test of Amadeus' desktop side in Tauri: the mini core and the tray, showing the same pages as desktop/popup.py.
//! The current window and tray stay as they are. Calls and the wake word aren't connected here.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use std::sync::{Arc, Mutex};

use tauri::image::Image;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

const BASE: &str = "http://127.0.0.1:8095";
const UA: &str = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/605.1.15 (KHTML, like Gecko) AmadeusDesktop/1";
const MW: f64 = 300.0;
const MH: f64 = 480.0;
// The pages talk to their window through window.amadeusBridge when it's there (web/mini.js, web/hud.js).
const BRIDGE: &str = r#"
window.amadeusBridge = { postMessage: (msg) => window.__TAURI_INTERNALS__.invoke("native", { msg: String(msg) }) };
addEventListener("error", (e) => console.error("JS error: " + e.message + " @" + e.lineno));
"#;

#[derive(Default)]
struct Zones(Arc<Mutex<Vec<[f64; 4]>>>);

fn data_dir() -> std::path::PathBuf {
    let home = std::env::var("HOME").unwrap_or_default();
    std::path::PathBuf::from(home).join(".local/share/amadeus/core")
}

fn page(path: &str) -> WebviewUrl {
    // the first page signs the window in (a cookie), then goes on
    let token = std::fs::read_to_string(data_dir().join("token")).unwrap_or_default();
    let url = format!("{BASE}/?token={}&next={path}", token.trim());
    WebviewUrl::External(url.parse().expect("a valid address"))
}

fn window<'a>(app: &'a AppHandle, label: &str, title: &str, path: &str) -> tauri::Result<WebviewWindowBuilder<'a, tauri::Wry, AppHandle>> {
    Ok(WebviewWindowBuilder::new(app, label, page(path))
        .title(title)
        .decorations(false)
        .user_agent(UA)
        .data_directory(data_dir().join("tauri-test-webview"))
        .initialization_script(BRIDGE))
}

fn show_mini(app: &AppHandle) -> tauri::Result<()> {
    if let Some(w) = app.get_webview_window("mini") {
        return w.show();
    }
    let w = window(app, "mini", "Amadeus core", "/mini.html")?
        .inner_size(MW, MH)
        .resizable(false)
        .transparent(true)
        .always_on_top(true)
        .skip_taskbar(true)
        .shadow(false)
        .build()?;
    prepare(&w)
}

fn show_dash(app: &AppHandle, path: &str) -> tauri::Result<()> {
    if let Some(m) = app.get_webview_window("mini") {
        m.hide()?;
    }
    if let Some(w) = app.get_webview_window("dash") {
        w.show()?;
        return w.set_focus();
    }
    let w = window(app, "dash", "Amadeus", path)?.inner_size(1200.0, 800.0).build()?;
    prepare(&w)
}

/// Microphone and autoplay for our pages, as desktop/popup.py allows them; on the mini core also dragging by its edge.
#[cfg(target_os = "linux")]
fn prepare(w: &WebviewWindow) -> tauri::Result<()> {
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
        view.connect_permission_request(|_, req| {
            if req.downcast_ref::<UserMediaPermissionRequest>().is_some() {
                req.allow();
                return true;
            }
            false
        });
        if win.label() != "mini" {
            return;
        }
        let zones = win.state::<Zones>().0.clone();
        let Ok(gw) = win.gtk_window() else { return };
        view.connect_button_press_event(move |_, ev| {
            let (x, y) = ev.position();
            let (cx, cy, r) = (MW / 2.0, 150.0 + 140.0, 280.0 / 2.0 / 1.5 * 1.15); // the sphere: click and hold
            let on_sphere = (x - cx).powi(2) + (y - cy).powi(2) <= r * r;
            let on_zone = zones.lock().unwrap().iter().any(|z| x >= z[0] && x <= z[0] + z[2] && y >= z[1] && y <= z[1] + z[3]);
            if ev.button() != 1 || ev.event_type() != gtk::gdk::EventType::ButtonPress || on_sphere || on_zone {
                return gtk::glib::Propagation::Proceed;
            }
            let (rx, ry) = ev.root();
            gw.begin_move_drag(1, rx as i32, ry as i32, ev.time());
            gtk::glib::Propagation::Stop
        });
    })
}

#[cfg(not(target_os = "linux"))]
fn prepare(_w: &WebviewWindow) -> tauri::Result<()> {
    Ok(())
}

/// Clicks only where something is drawn; everywhere else they reach the desktop.
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

#[tauri::command]
fn native(app: AppHandle, window: WebviewWindow, msg: String) {
    println!("from {}: {}", window.label(), msg.chars().take(70).collect::<String>());
    let done = match msg.as_str() {
        "close" | "hide" => window.hide(),
        "mini" => window.hide().and_then(|_| show_mini(&app)),
        "quit" => {
            app.exit(0);
            Ok(())
        }
        m if m.starts_with("dash:") => {
            let path = if m.len() > 5 { m[5..].to_string() } else { "/#home".into() };
            let a = app.clone();
            app.run_on_main_thread(move || {
                if let Err(e) = show_dash(&a, &path) {
                    eprintln!("dashboard: {e}");
                }
            })
        }
        m if m.starts_with("shape:") => {
            if let Ok(rects) = serde_json::from_str::<Vec<[f64; 4]>>(&m[6..]) {
                let w = window.clone();
                app.run_on_main_thread(move || set_shape(&w, &rects)).ok();
            }
            Ok(())
        }
        m if m.starts_with("zones:") => {
            if let Ok(z) = serde_json::from_str::<Vec<[f64; 4]>>(&m[6..]) {
                *app.state::<Zones>().0.lock().unwrap() = z;
            }
            Ok(())
        }
        _ => Ok(()),
    };
    if let Err(e) = done {
        eprintln!("{msg}: {e}");
    }
}

fn tray(app: &AppHandle) -> tauri::Result<()> {
    let toggle = MenuItem::with_id(app, "toggle", "Show or hide the core", true, None::<&str>)?;
    let dash = MenuItem::with_id(app, "dash", "Dashboard", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit the test", true, None::<&str>)?;
    TrayIconBuilder::new()
        .icon(Image::from_bytes(include_bytes!("../icons/tray.png"))?)
        .tooltip("Amadeus (Tauri test)")
        .menu(&Menu::with_items(app, &[&toggle, &dash, &quit])?)
        .on_menu_event(|app, ev| match ev.id.as_ref() {
            "toggle" => match app.get_webview_window("mini") {
                Some(w) if w.is_visible().unwrap_or(false) => drop(w.hide()),
                _ => drop(show_mini(app)),
            },
            "dash" => drop(show_dash(app, "/#home")),
            "quit" => app.exit(0),
            _ => {}
        })
        .build(app)?;
    Ok(())
}

fn main() {
    #[cfg(target_os = "linux")]
    gtk::glib::set_prgname(Some("amadeus-call")); // the Wayland app id the KWin rule matches (always on top, its place)
    tauri::Builder::default()
        .manage(Zones::default())
        .invoke_handler(tauri::generate_handler![native])
        .setup(|app| {
            tray(app.handle())?;
            show_mini(app.handle())?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("the desktop app");
}
