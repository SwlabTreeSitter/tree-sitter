use std::{env, fs, path::PathBuf};

fn main() {
    let out_dir = PathBuf::from(env::var("OUT_DIR").unwrap());

    #[cfg(feature = "bindgen")]
    generate_bindings(&out_dir);

    fs::copy(
        "src/wasm/stdlib-symbols.txt",
        out_dir.join("stdlib-symbols.txt"),
    )
    .unwrap();

    let mut config = cc::Build::new();

    println!("cargo:rerun-if-env-changed=CARGO_FEATURE_WASM");
    if env::var("CARGO_FEATURE_WASM").is_ok() {
        config
            .define("TREE_SITTER_FEATURE_WASM", "")
            .define("static_assert(...)", "")
            .include(env::var("DEP_WASMTIME_C_API_INCLUDE").unwrap());
    }

    let manifest_path = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let include_path = manifest_path.join("include");
    let src_path = manifest_path.join("src");
    let wasm_path = src_path.join("wasm");
    for entry in fs::read_dir(&src_path).unwrap() {
        let entry = entry.unwrap();
        let path = src_path.join(entry.file_name());
        println!("cargo:rerun-if-changed={}", path.to_str().unwrap());
    }

    config
        .flag_if_supported("-std=c11")
        .flag_if_supported("-fvisibility=hidden")
        .flag_if_supported("-Wshadow")
        .flag_if_supported("-Wno-unused-parameter")
        .flag_if_supported("-Wno-incompatible-pointer-types")
        .include(&src_path)
        .include(&wasm_path)
        .include(&include_path)
        .define("_POSIX_C_SOURCE", "200112L")
        .define("_DEFAULT_SOURCE", None)
        .warnings(false)
        .file(src_path.join("lib.c"))
        .compile("tree-sitter");

    println!("cargo:include={}", include_path.display());

    // MSVC 환경인지 확인
    if std::env::var("CARGO_CFG_TARGET_ENV").unwrap() == "msvc" {
        use std::env;
        use std::fs;
        use std::path::PathBuf;

        // 1. Cargo가 .lib 파일을 생성한 위치 (예: .../out/tree-sitter.lib)
        let out_dir = PathBuf::from(env::var("OUT_DIR").unwrap());
        let lib_path = out_dir.join("tree-sitter.lib");

        // 2. 최종 목적지(target) 폴더 경로를 더 안정적으로 찾기
        // CARGO_TARGET_DIR 환경 변수가 있으면 사용, 없으면 manifest 기준 'target' 폴더
        let target_dir = if let Ok(target_dir) = env::var("CARGO_TARGET_DIR") {
            PathBuf::from(target_dir)
        } else {
            PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap()).join("target")
        };

        // 3. 'debug' 또는 'release' 프로필 경로
        let profile = env::var("PROFILE").unwrap();
        let dest_dir = target_dir.join(profile); // 예: .../target/debug

        // 4. .lib 파일 복사
        if lib_path.exists() {
            // 목적지 폴더가 없으면 생성
            if let Err(e) = fs::create_dir_all(&dest_dir) {
                println!("cargo:warning=Failed to create dest_dir {}: {}", dest_dir.display(), e);
                return;
            }

            let dest_path = dest_dir.join("treesitter.lib");
            match fs::copy(&lib_path, &dest_path) {
                Ok(_) => println!("cargo:warning=Copied treesitter.lib to {}", dest_path.display()),
                Err(e) => println!("cargo:warning=Failed to copy treesitter.lib to {}: {}", dest_path.display(), e),
            }
        } else {
            println!("cargo:warning=treesitter.lib not found in {}, skipping copy.", lib_path.display());
        }
    }
} 

#[cfg(feature = "bindgen")]
fn generate_bindings(out_dir: &std::path::Path) {
    use std::str::FromStr;

    use bindgen::RustTarget;

    const HEADER_PATH: &str = "include/tree_sitter/api.h";

    println!("cargo:rerun-if-changed={HEADER_PATH}");

    let no_copy = [
        "TSInput",
        "TSLanguage",
        "TSLogger",
        "TSLookaheadIterator",
        "TSParser",
        "TSTree",
        "TSQuery",
        "TSQueryCursor",
        "TSQueryCapture",
        "TSQueryMatch",
        "TSQueryPredicateStep",
    ];

    let rust_version = env!("CARGO_PKG_RUST_VERSION");

    let bindings = bindgen::Builder::default()
        .header(HEADER_PATH)
        .layout_tests(false)
        .allowlist_type("^TS.*")
        .allowlist_function("^ts_.*")
        .allowlist_var("^TREE_SITTER.*")
        .no_copy(no_copy.join("|"))
        .prepend_enum_name(false)
        .use_core()
        .clang_arg("-D TREE_SITTER_FEATURE_WASM")
        .rust_target(RustTarget::from_str(rust_version).unwrap())
        .generate()
        .expect("Failed to generate bindings");

    let bindings_rs = out_dir.join("bindings.rs");
    bindings.write_to_file(&bindings_rs).unwrap_or_else(|_| {
        panic!(
            "Failed to write bindings into path: {}",
            bindings_rs.display()
        )
    });
}
