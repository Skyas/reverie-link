use serde::Deserialize;
use std::sync::Mutex;
use std::thread;
use std::time::Duration;
use enigo::{Enigo, Mouse, Settings};
use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem, Submenu},
    tray::TrayIconBuilder,
    Emitter, Manager,
};

// 接收前端传来的菜单数据格式
#[derive(Deserialize, Clone)]
pub struct TrayMenuData {
    pub id: String,
    pub name: String,
}

// 集中管理全局状态
pub struct AppState {
    pub is_passthrough: Mutex<bool>,
    pub is_muted: Mutex<bool>,
    pub characters: Mutex<Vec<TrayMenuData>>,
    pub models: Mutex<Vec<TrayMenuData>>,
    // 当前激活项（用于托盘菜单勾选显示）
    pub active_character_id: Mutex<Option<String>>,
    pub active_model_path: Mutex<Option<String>>,
}

// 辅助函数：根据当前状态重新构建并更新托盘菜单
fn update_tray_menu(app: &tauri::AppHandle) {
    let state = app.state::<AppState>();
    let is_locked = *state.is_passthrough.lock().unwrap();
    let is_muted = *state.is_muted.lock().unwrap();
    let chars = state.characters.lock().unwrap().clone();
    let models = state.models.lock().unwrap().clone();
    let active_char = state.active_character_id.lock().unwrap().clone();
    let active_model = state.active_model_path.lock().unwrap().clone();

    let is_visible = if let Some(win) = app.get_webview_window("main") {
        win.is_visible().unwrap_or(true)
    } else {
        true
    };

    // ── 固定项 ────────────────────────────────────────────────────
    let toggle_label = if is_locked { "🔒 当前：穿透中" } else { "🔓 当前：可交互" };
    let toggle_item = MenuItem::with_id(
        app, "toggle_passthrough", toggle_label, true, None::<&str>
    ).unwrap();

    let visibility_label = if is_visible { "👁️ 隐藏桌宠" } else { "👁️ 显示桌宠" };
    let visibility_item = MenuItem::with_id(
        app, "toggle_visibility", visibility_label, true, None::<&str>
    ).unwrap();

    let sep1 = PredefinedMenuItem::separator(app).unwrap();

    // ── 动态角色子菜单（当前激活项前缀 ✓）────────────────────────
    let mut char_items: Vec<MenuItem<tauri::Wry>> = Vec::new();
    if chars.is_empty() {
        char_items.push(
            MenuItem::with_id(app, "char_empty", "暂无角色", false, None::<&str>).unwrap()
        );
    } else {
        for c in chars.iter() {
            let is_active = active_char.as_deref() == Some(c.id.as_str());
            let display = if is_active {
                format!("✓  {}", c.name)
            } else {
                format!("    {}", c.name) // 与 ✓ 宽度对齐
            };
            char_items.push(
                MenuItem::with_id(
                    app, format!("char_{}", c.id), display, true, None::<&str>
                ).unwrap()
            );
        }
    }
    let char_refs: Vec<&dyn tauri::menu::IsMenuItem<tauri::Wry>> =
        char_items.iter().map(|i| i as _).collect();
    let switch_char_menu = Submenu::with_items(app, "切换角色", true, &char_refs).unwrap();

    // ── 动态模型子菜单（当前激活项前缀 ✓）────────────────────────
    let mut model_items: Vec<MenuItem<tauri::Wry>> = Vec::new();
    if models.is_empty() {
        model_items.push(
            MenuItem::with_id(app, "model_empty", "暂无模型", false, None::<&str>).unwrap()
        );
    } else {
        for m in models.iter() {
            let is_active = active_model.as_deref() == Some(m.id.as_str());
            let display = if is_active {
                format!("✓  {}", m.name)
            } else {
                format!("    {}", m.name)
            };
            model_items.push(
                MenuItem::with_id(
                    app, format!("model_{}", m.id), display, true, None::<&str>
                ).unwrap()
            );
        }
    }
    let model_refs: Vec<&dyn tauri::menu::IsMenuItem<tauri::Wry>> =
        model_items.iter().map(|i| i as _).collect();
    let switch_model_menu = Submenu::with_items(app, "切换模型", true, &model_refs).unwrap();

    let sep2 = PredefinedMenuItem::separator(app).unwrap();

    // ── 静音 ──────────────────────────────────────────────────────
    let mute_label = if is_muted { "🔊 取消静音" } else { "🔇 静音" };
    let mute_item = MenuItem::with_id(
        app, "toggle_mute", mute_label, true, None::<&str>
    ).unwrap();

    let sep3 = PredefinedMenuItem::separator(app).unwrap();

    // ── 设置 / 重载 ───────────────────────────────────────────────
    let reset_pos_item = MenuItem::with_id(
        app, "reset_position", "📍 重置位置", true, None::<&str>
    ).unwrap();
    let settings_item = MenuItem::with_id(
        app, "open_settings", "⚙️ 设置", true, None::<&str>
    ).unwrap();
    let reload_item = MenuItem::with_id(
        app, "reload_window", "🔄 重新加载", true, None::<&str>
    ).unwrap();

    let sep4 = PredefinedMenuItem::separator(app).unwrap();

    let quit_item = MenuItem::with_id(
        app, "quit", "❌ 退出", true, None::<&str>
    ).unwrap();

    // ── 组装菜单 ──────────────────────────────────────────────────
    let menu = Menu::with_items(app, &[
        &toggle_item, &visibility_item, &sep1,
        &switch_char_menu, &switch_model_menu, &sep2,
        &mute_item, &sep3,
        &reset_pos_item, &settings_item, &reload_item, &sep4,
        &quit_item,
    ]).unwrap();

    if let Some(tray) = app.tray_by_id("main-tray") {
        let _ = tray.set_menu(Some(menu));
    }
}

// ── Tauri Commands ────────────────────────────────────────────────────────────

/// 前端同步角色列表、模型列表、当前激活项到 Rust 侧
#[tauri::command]
fn update_menu_data(
    app: tauri::AppHandle,
    state: tauri::State<'_, AppState>,
    characters: Vec<TrayMenuData>,
    models: Vec<TrayMenuData>,
    active_character_id: Option<String>,
    active_model_path: Option<String>,
) -> Result<(), String> {
    *state.characters.lock().unwrap() = characters;
    *state.models.lock().unwrap() = models;
    // 仅在前端明确传入时才更新，None 表示"不变"
    if let Some(id) = active_character_id {
        *state.active_character_id.lock().unwrap() = if id.is_empty() { None } else { Some(id) };
    }
    if let Some(path) = active_model_path {
        *state.active_model_path.lock().unwrap() = if path.is_empty() { None } else { Some(path) };
    }
    update_tray_menu(&app);
    println!("[Tauri] 托盘菜单数据已更新");
    Ok(())
}

#[tauri::command]
fn set_cursor_passthrough(window: tauri::Window, passthrough: bool) -> Result<(), String> {
    window.set_ignore_cursor_events(passthrough).map_err(|e| e.to_string())
}

#[tauri::command]
async fn toggle_lock(
    app: tauri::AppHandle,
    state: tauri::State<'_, AppState>,
) -> Result<bool, String> {
    let new_state = {
        let mut locked = state.is_passthrough.lock().unwrap();
        *locked = !*locked;
        *locked
    };
    let window = app.get_webview_window("main").unwrap();
    window.set_ignore_cursor_events(new_state).map_err(|e| e.to_string())?;
    let _ = window.emit("passthrough-changed", new_state);
    update_tray_menu(&app);
    println!("[Tauri] 锁定状态切换: {}", new_state);
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

#[tauri::command]
fn open_devtools(app: tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        window.open_devtools();
        println!("[Tauri] DevTools 已打开");
    }
}

// ── 主入口 ────────────────────────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    println!("[Tauri] ⏱ run() 开始");

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(move |app| {
            println!("[Tauri] ⏱ setup() 开始");

            // ── 初始化全局状态 ────────────────────────────────────
            app.manage(AppState {
                is_passthrough: Mutex::new(false),
                is_muted: Mutex::new(false),
                characters: Mutex::new(Vec::new()),
                models: Mutex::new(Vec::new()),
                active_character_id: Mutex::new(None),
                active_model_path: Mutex::new(None),
            });

            // ── 构建托盘 ──────────────────────────────────────────
            TrayIconBuilder::with_id("main-tray")
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("Reverie Link")
                .on_menu_event(move |app, event| {
                    let id_str = event.id.as_ref();

                    // 动态角色切换：立即更新 Rust 侧 active，再通知前端
                    if let Some(char_id) = id_str.strip_prefix("char_") {
                        {
                            let state = app.state::<AppState>();
                            *state.active_character_id.lock().unwrap() = Some(char_id.to_string());
                        }
                        update_tray_menu(app); // 勾选立即生效
                        if let Some(win) = app.get_webview_window("main") {
                            let _ = win.emit("tray-switch-character", char_id);
                            println!("[Tauri] 托盘切换角色: {}", char_id);
                        }
                        return;
                    }

                    // 动态模型切换：立即更新 Rust 侧 active，再通知前端
                    if let Some(model_path) = id_str.strip_prefix("model_") {
                        {
                            let state = app.state::<AppState>();
                            *state.active_model_path.lock().unwrap() = Some(model_path.to_string());
                        }
                        update_tray_menu(app); // 勾选立即生效
                        if let Some(win) = app.get_webview_window("main") {
                            let _ = win.emit("tray-switch-model", model_path);
                            println!("[Tauri] 托盘切换模型: {}", model_path);
                        }
                        return;
                    }

                    // 固定菜单项
                    match id_str {
                        "toggle_passthrough" => {
                            let state = app.state::<AppState>();
                            let new_state = {
                                let mut locked = state.is_passthrough.lock().unwrap();
                                *locked = !*locked;
                                *locked
                            };
                            if let Some(win) = app.get_webview_window("main") {
                                let _ = win.set_ignore_cursor_events(new_state);
                                let _ = win.emit("passthrough-changed", new_state);
                            }
                            update_tray_menu(app);
                            println!("[Tauri] 穿透切换: {}", new_state);
                        }

                        "toggle_visibility" => {
                            if let Some(win) = app.get_webview_window("main") {
                                let is_visible = win.is_visible().unwrap_or(true);
                                if is_visible {
                                    let _ = win.hide();
                                    println!("[Tauri] 桌宠已隐藏");
                                } else {
                                    let _ = win.show();
                                    let _ = win.set_focus();
                                    println!("[Tauri] 桌宠已显示");
                                }
                                update_tray_menu(app);
                            }
                        }

                        "toggle_mute" => {
                            let state = app.state::<AppState>();
                            let new_muted = {
                                let mut muted = state.is_muted.lock().unwrap();
                                *muted = !*muted;
                                *muted
                            };
                            if let Some(win) = app.get_webview_window("main") {
                                let _ = win.emit("toggle-mute", new_muted);
                            }
                            update_tray_menu(app);
                            println!("[Tauri] 静音状态: {}", new_muted);
                        }

                        "reset_position" => {
                            if let Some(win) = app.get_webview_window("main") {
                                let _ = win.center();
                                let _ = win.show();
                                let _ = win.emit("reset-position", ());
                                println!("[Tauri] 窗口位置已重置到屏幕中央");
                            }
                            update_tray_menu(app);
                        }

                        "reload_window" => {
                            if let Some(win) = app.get_webview_window("main") {
                                let _ = win.eval("window.location.reload()");
                                println!("[Tauri] 前端已触发重载");
                            }
                        }

                        "open_settings" => {
                            let app_clone = app.clone();
                            tauri::async_runtime::spawn(async move {
                                let _ = open_settings(app_clone).await;
                            });
                        }

                        "quit" => {
                            println!("[Tauri] 退出");
                            app.exit(0);
                        }

                        _ => {}
                    }
                })
                .build(app)?;

            // 首次渲染托盘（角色/模型为空，待前端同步后更新）
            update_tray_menu(app.handle());

            // ── 桌宠窗口截屏排除 ─────────────────────────────────
            #[cfg(target_os = "windows")]
            {
                if let Some(window) = app.get_webview_window("main") {
                    if let Ok(hwnd) = window.hwnd() {
                        use windows_sys::Win32::UI::WindowsAndMessaging::SetWindowDisplayAffinity;
                        const WDA_EXCLUDEFROMCAPTURE: u32 = 0x00000011;
                        let result = unsafe {
                            SetWindowDisplayAffinity(hwnd.0, WDA_EXCLUDEFROMCAPTURE)
                        };
                        if result != 0 {
                            println!("[Tauri] ✅ 桌宠窗口已设置为截屏排除");
                        } else {
                            eprintln!("[Tauri] ⚠️ SetWindowDisplayAffinity 失败");
                        }
                    }
                }
            }

            // ── 鼠标悬停检测线程 ─────────────────────────────────
            let app_handle = app.handle().clone();
            thread::spawn(move || {
                let enigo = Enigo::new(&Settings::default()).unwrap();
                let mut hover_frames = 0u32;
                let mut was_hovering = false;

                loop {
                    thread::sleep(Duration::from_millis(100));

                    let locked = {
                        let state = app_handle.state::<AppState>();
                        let val = *state.is_passthrough.lock().unwrap();
                        val
                    };

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
                            } else {
                                false
                            }
                        } else {
                            false
                        };

                        if in_range {
                            hover_frames += 1;
                            if hover_frames == 15 && !was_hovering {
                                was_hovering = true;
                                if let Some(win) = app_handle.get_webview_window("main") {
                                    let _ = win.set_ignore_cursor_events(false);
                                    let _ = win.emit("mascot-hover", true);
                                }
                            }
                        } else {
                            hover_frames = 0;
                            if was_hovering {
                                was_hovering = false;
                                if let Some(win) = app_handle.get_webview_window("main") {
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
        .invoke_handler(tauri::generate_handler![
            set_cursor_passthrough,
            toggle_lock,
            open_settings,
            open_history,
            update_menu_data,
            open_devtools,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}