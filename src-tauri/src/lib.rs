use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;
use enigo::{Enigo, Mouse, Settings};
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Emitter, Manager,
};

#[tauri::command]
fn set_cursor_passthrough(window: tauri::Window, passthrough: bool) -> Result<(), String> {
    window
        .set_ignore_cursor_events(passthrough)
        .map_err(|e| e.to_string())
}

#[tauri::command]
async fn toggle_lock(
    app: tauri::AppHandle,
    state: tauri::State<'_, Arc<Mutex<bool>>>,
) -> Result<bool, String> {
    let new_state = {
        let mut locked = state.lock().unwrap();
        *locked = !*locked;
        *locked
    };

    let window = app.get_webview_window("main").unwrap();
    window
        .set_ignore_cursor_events(new_state)
        .map_err(|e| e.to_string())?;

    let _ = window.emit("passthrough-changed", new_state);

    let label = if new_state { "🔒 当前：穿透中" } else { "🔓 当前：可交互" };
    if let Some(tray) = app.tray_by_id("main-tray") {
        let new_toggle = MenuItem::with_id(
            &app, "toggle_passthrough", label, true, None::<&str>
        ).unwrap();
        let new_settings = MenuItem::with_id(
            &app, "open_settings", "⚙️ 设置", true, None::<&str>
        ).unwrap();
        let new_quit = MenuItem::with_id(
            &app, "quit", "退出 Reverie Link", true, None::<&str>
        ).unwrap();
        let new_menu = Menu::with_items(&app, &[&new_toggle, &new_settings, &new_quit]).unwrap();
        let _ = tray.set_menu(Some(new_menu));
    }

    Ok(new_state)
}

#[tauri::command]
async fn open_settings(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_webview_window("settings") {
        win.show().map_err(|e| e.to_string())?;
        win.set_focus().map_err(|e| e.to_string())?;
    } else {
        #[cfg(dev)]
        let url = tauri::WebviewUrl::External(
            "http://localhost:17420/settings.html".parse().unwrap()
        );
        #[cfg(not(dev))]
        let url = tauri::WebviewUrl::App("settings.html".into());

        tauri::WebviewWindowBuilder::new(&app, "settings", url)
            .title("Reverie Link · 设置")
            .inner_size(520.0, 620.0)
            .resizable(false)
            .center()
            .build()
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
async fn open_history(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_webview_window("history") {
        win.show().map_err(|e| e.to_string())?;
        win.set_focus().map_err(|e| e.to_string())?;
    } else {
        #[cfg(dev)]
        let url = tauri::WebviewUrl::External(
            "http://localhost:17420/history.html".parse().unwrap()
        );
        #[cfg(not(dev))]
        let url = tauri::WebviewUrl::App("history.html".into());
 
        tauri::WebviewWindowBuilder::new(&app, "history", url)
            .title("Reverie Link · 聊天记录")
            .inner_size(700.0, 560.0)
            .resizable(true)
            .center()
            .build()
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let is_passthrough = Arc::new(Mutex::new(false));

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(is_passthrough.clone())
        .setup(move |app| {
            // ── 托盘菜单 ──────────────────────────────────────
            let toggle_item = MenuItem::with_id(
                app, "toggle_passthrough", "🔓 当前：可交互", true, None::<&str>,
            )?;
            let settings_item = MenuItem::with_id(
                app, "open_settings", "⚙️ 设置", true, None::<&str>,
            )?;
            let quit_item = MenuItem::with_id(
                app, "quit", "退出 Reverie Link", true, None::<&str>,
            )?;
            let menu = Menu::with_items(app, &[&toggle_item, &settings_item, &quit_item])?;

            TrayIconBuilder::with_id("main-tray")
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("Reverie Link")
                .menu(&menu)
                .on_menu_event(move |app, event| match event.id.as_ref() {
                    "toggle_passthrough" => {
                        let state = app.state::<Arc<Mutex<bool>>>();
                        let new_state = {
                            let mut locked = state.lock().unwrap();
                            *locked = !*locked;
                            *locked
                        };
                        let window = app.get_webview_window("main").unwrap();
                        let _ = window.set_ignore_cursor_events(new_state);
                        let _ = window.emit("passthrough-changed", new_state);

                        let label = if new_state { "🔒 当前：穿透中" } else { "🔓 当前：可交互" };
                        if let Some(tray) = app.tray_by_id("main-tray") {
                            let new_toggle = MenuItem::with_id(
                                app, "toggle_passthrough", label, true, None::<&str>
                            ).unwrap();
                            let new_settings = MenuItem::with_id(
                                app, "open_settings", "⚙️ 设置", true, None::<&str>
                            ).unwrap();
                            let new_quit = MenuItem::with_id(
                                app, "quit", "退出 Reverie Link", true, None::<&str>
                            ).unwrap();
                            let new_menu = Menu::with_items(
                                app, &[&new_toggle, &new_settings, &new_quit]
                            ).unwrap();
                            let _ = tray.set_menu(Some(new_menu));
                        }
                    }
                    "open_settings" => {
                        let app = app.clone();
                        tauri::async_runtime::spawn(async move {
                            let _ = open_settings(app).await;
                        });
                    }
                    "quit" => {
                        app.exit(0);
                    }
                    _ => {}
                })
                .build(app)?;

            // ── 鼠标轮询线程 ──────────────────────────────────
            let app_handle = app.handle().clone();
            let is_passthrough_clone = is_passthrough.clone();

            thread::spawn(move || {
                let mut enigo = Enigo::new(&Settings::default()).unwrap();
                let mut hover_frames = 0u32;
                let mut was_hovering = false;

                loop {
                    thread::sleep(Duration::from_millis(100));

                    let locked = *is_passthrough_clone.lock().unwrap();

                    if !locked {
                        hover_frames = 0;
                        if was_hovering {
                            was_hovering = false;
                            if let Some(win) = app_handle.get_webview_window("main") {
                                let _ = win.emit("mascot-hover", false);
                            }
                        }
                        continue;
                    }

                    if let Ok((mx, my)) = enigo.location() {
                        let in_range = if let Some(win) = app_handle.get_webview_window("main") {
                            if let (Ok(pos), Ok(size)) = (win.outer_position(), win.outer_size()) {
                                mx >= pos.x
                                    && my >= pos.y
                                    && mx <= pos.x + size.width as i32
                                    && my <= pos.y + size.height as i32
                            } else { false }
                        } else { false };

                        if in_range {
                            hover_frames += 1;
                            // 100ms × 15 = 1.5秒后显示解锁按钮
                            if hover_frames == 15 && !was_hovering {
                                was_hovering = true;
                                if let Some(win) = app_handle.get_webview_window("main") {
                                    // 临时关闭穿透，让解锁按钮可点击
                                    let _ = win.set_ignore_cursor_events(false);
                                    let _ = win.emit("mascot-hover", true);
                                }
                            }
                        } else {
                            hover_frames = 0;
                            if was_hovering {
                                was_hovering = false;
                                if let Some(win) = app_handle.get_webview_window("main") {
                                    // 鼠标离开，恢复穿透
                                    let _ = win.set_ignore_cursor_events(true);
                                    let _ = win.emit("mascot-hover", false);
                                }
                            }
                        }
                    }
                }
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![set_cursor_passthrough, toggle_lock, open_settings, open_history])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}