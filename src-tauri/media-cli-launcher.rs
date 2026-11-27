use std::env;
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::Command;

fn backend_path() -> Result<PathBuf, String> {
    if let Some(path) = env::var_os("OFFICEKIT_BACKEND_EXECUTABLE") {
        return Ok(PathBuf::from(path));
    }
    let executable = env::current_exe().map_err(|error| error.to_string())?;
    let directory = executable
        .parent()
        .ok_or_else(|| "Could not locate the OfficeKit app resources".to_string())?;
    let development_root = directory.parent().and_then(|path| path.parent()).unwrap_or(directory);
    let development_executable = development_root
        .join(".build")
        .join("backend-sidecar")
        .join("dist")
        .join("officekit-backend")
        .join("officekit-backend");
    if development_executable.is_file() {
        return Ok(development_executable);
    }
    let app_resources = directory.parent().unwrap_or(directory);
    Ok(app_resources
        .join("resources")
        .join("officekit-backend")
        .join("officekit-backend"))
}

fn main() {
    let executable = match backend_path() {
        Ok(path) => path,
        Err(error) => {
            eprintln!("OfficeKit media CLI path error: {error}");
            std::process::exit(1);
        }
    };
    let mut arguments = env::args_os().skip(1);
    let first = arguments.next();
    // `--agent-mcp` and `--agent-cli` select the general agent tools (PDF, image, calculators);
    // `--mcp-server` and bare arguments keep their Media Toolkit meaning.
    let agent_flag = ["--agent-mcp", "--agent-cli"]
        .into_iter()
        .find(|flag| first.as_deref() == Some(std::ffi::OsStr::new(flag)));
    let dispatcher = if let Some(flag) = agent_flag {
        flag
    } else if first.as_deref() == Some(std::ffi::OsStr::new("--mcp-server")) {
        "--media-mcp"
    } else {
        "--media-cli"
    };
    let mut command = Command::new(executable);
    command.arg(dispatcher);
    if dispatcher == "--media-cli" {
        if let Some(argument) = first {
            command.arg(argument);
        }
    }
    command.args(arguments).envs(env::vars_os());
    let error = command.exec();
    eprintln!("OfficeKit media CLI launch error: {error}");
    std::process::exit(1);
}
