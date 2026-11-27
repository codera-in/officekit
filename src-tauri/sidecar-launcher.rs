use std::env;
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::Command;

enum LaunchTarget {
    Binary(PathBuf),
    Python { python: PathBuf, script: PathBuf },
}

fn which_binary(name: &str) -> Option<PathBuf> {
    if let Some(paths) = env::var_os("PATH") {
        for path in env::split_paths(&paths) {
            let candidate = path.join(name);
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }
    None
}

fn resolve_launch_target() -> Result<LaunchTarget, String> {
    // 1. Explicit override via environment variable if the file actually exists
    if let Some(path) = env::var_os("OFFICEKIT_BACKEND_EXECUTABLE") {
        let candidate = PathBuf::from(path);
        if candidate.is_file() {
            return Ok(LaunchTarget::Binary(candidate));
        }
    }

    let executable = env::current_exe().map_err(|error| error.to_string())?;

    // 2. Check bundled resources (installed app: Contents/Resources/resources/officekit-backend/officekit-backend)
    if let Some(macos_dir) = executable.parent() {
        if let Some(contents) = macos_dir.parent() {
            let bundle_executable = contents
                .join("Resources")
                .join("resources")
                .join("officekit-backend")
                .join("officekit-backend");
            if bundle_executable.is_file() {
                return Ok(LaunchTarget::Binary(bundle_executable));
            }
            let direct_bundle_executable = contents
                .join("Resources")
                .join("officekit-backend")
                .join("officekit-backend");
            if direct_bundle_executable.is_file() {
                return Ok(LaunchTarget::Binary(direct_bundle_executable));
            }
        }
    }

    // 3. Search upwards from executable directory for PyInstaller dist or backend_main.py
    let mut search_dir = executable.parent();
    while let Some(dir) = search_dir {
        let dist_binary = dir
            .join(".build")
            .join("backend-sidecar")
            .join("dist")
            .join("officekit-backend")
            .join("officekit-backend");
        if dist_binary.is_file() {
            return Ok(LaunchTarget::Binary(dist_binary));
        }

        let script = dir.join("backend_main.py");
        if script.is_file() {
            let venv_python = dir.join(".venv").join("bin").join("python");
            let python = if venv_python.is_file() {
                venv_python
            } else if let Some(py) = which_binary("python3") {
                py
            } else if let Some(py) = which_binary("python") {
                py
            } else {
                PathBuf::from("python3")
            };
            return Ok(LaunchTarget::Python { python, script });
        }
        search_dir = dir.parent();
    }

    // 4. Fallback: check current working directory for backend_main.py
    if let Ok(cwd) = env::current_dir() {
        let script = cwd.join("backend_main.py");
        if script.is_file() {
            let venv_python = cwd.join(".venv").join("bin").join("python");
            let python = if venv_python.is_file() {
                venv_python
            } else if let Some(py) = which_binary("python3") {
                py
            } else {
                PathBuf::from("python3")
            };
            return Ok(LaunchTarget::Python { python, script });
        }
    }

    Err("Could not locate the OfficeKit backend executable or Python runtime".to_string())
}

fn main() {
    let target = match resolve_launch_target() {
        Ok(target) => target,
        Err(error) => {
            eprintln!("OfficeKit backend path error: {error}");
            std::process::exit(1);
        }
    };

    let error = match target {
        LaunchTarget::Binary(path) => Command::new(path)
            .args(env::args_os().skip(1))
            .envs(env::vars_os())
            .exec(),
        LaunchTarget::Python { python, script } => Command::new(python)
            .arg(script)
            .args(env::args_os().skip(1))
            .envs(env::vars_os())
            .exec(),
    };
    eprintln!("OfficeKit backend launch error: {error}");
    std::process::exit(1);
}

