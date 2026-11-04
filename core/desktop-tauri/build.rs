fn main() {
    // pages served by the local core aren't bundled with the app, so their one command is declared here
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(tauri_build::AppManifest::new().commands(&["native"]))).expect("the build")
}
