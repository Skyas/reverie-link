use std::sync::{Arc, Mutex};
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Manager,
};

/// 供前端调用：主动设置穿透状态（Phase 2 的悬浮把手会用到）
#[tauri::command]
fn set_cursor_passthrough(window: tauri::Window, passthrough: bool) -> Result<(), String> {
    window
        .set_ignore_cursor_events(passthrough)
        .map_err(|e| e.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            // 穿透状态：false = 未锁定，true = 已锁定
            let is_passthrough = Arc::new(Mutex::new(false));

            let toggle_item = MenuItem::with_id(
                app,
                "toggle_passthrough",
                "🔓 点击锁定",
                true,
                None::<&str>,
            )?;
            let quit_item =
                MenuItem::with_id(app, "quit", "退出 Reverie Link", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&toggle_item, &quit_item])?;

            TrayIconBuilder::with_id("main-tray")
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("Reverie Link")
                .menu(&menu)
                .on_menu_event(move |app, event| match event.id.as_ref() {
                    "toggle_passthrough" => {
                        let window = app.get_webview_window("main").unwrap();
                        let mut state = is_passthrough.lock().unwrap();
                        *state = !*state;
                        let _ = window.set_ignore_cursor_events(*state);

                        // 同步更新托盘菜单文字，反映当前状态
                        let label = if *state {
                            "🔒 点击解锁"
                        } else {
                            "🔓 点击锁定"
                        };
                        if let Some(tray) = app.tray_by_id("main-tray") {
                            let new_toggle = MenuItem::with_id(
                                app,
                                "toggle_passthrough",
                                label,
                                true,
                                None::<&str>,
                            )
                            .unwrap();
                            let new_quit = MenuItem::with_id(
                                app,
                                "quit",
                                "退出 Reverie Link",
                                true,
                                None::<&str>,
                            )
                            .unwrap();
                            let new_menu =
                                Menu::with_items(app, &[&new_toggle, &new_quit]).unwrap();
                            let _ = tray.set_menu(Some(new_menu));
                        }
                    }
                    "quit" => {
                        app.exit(0);
                    }
                    _ => {}
                })
                .build(app)?;

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![set_cursor_passthrough])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}