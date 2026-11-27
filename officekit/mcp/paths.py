"""Folder policy for agent-supplied paths: reads stay inside allowed folders, writes never overwrite."""

import os
import re
from pathlib import Path

ALLOWED_DIRS_ENV = "OFFICEKIT_MCP_ALLOWED_DIRS"
OUTPUT_DIR_ENV = "OFFICEKIT_MCP_OUTPUT_DIR"
MAX_INPUT_BYTES = 256 * 1024 * 1024


class PathPolicyError(ValueError):
    pass


class PathPolicy:
    def __init__(self, environment=None, cwd=None, home=None):
        env = os.environ if environment is None else environment
        home_dir = Path(home or Path.home())
        self.output_dir = Path(env.get(OUTPUT_DIR_ENV) or home_dir / "OfficeKit Output").expanduser().resolve()
        configured = env.get(ALLOWED_DIRS_ENV)
        if configured:
            roots = [Path(part).expanduser() for part in configured.split(os.pathsep) if part.strip()]
        else:
            roots = [Path(cwd or Path.cwd()), *(home_dir / name for name in ("Documents", "Downloads", "Desktop"))]
        self.roots = tuple(dict.fromkeys([*(root.resolve() for root in roots), self.output_dir]))

    def read_file(self, value) -> tuple[str, bytes]:
        if not isinstance(value, str) or not value or "\0" in value:
            raise PathPolicyError("file must be a non-empty path string")
        path = Path(value).expanduser().resolve()
        root = self._root_of(path)
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            raise PathPolicyError("Hidden files and folders are not readable.")
        if not path.is_file():
            raise PathPolicyError(f"Not a file: {path.name}")
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise PathPolicyError("File is larger than the 256 MB limit.")
        return path.name, path.read_bytes()

    def write_file(self, name: str, content: bytes, fallback: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._ -]", "_", os.path.basename(name or "")).strip(" .") or fallback
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stem, suffix = os.path.splitext(safe)
        for counter in range(1, 10_000):
            target = self.output_dir / (safe if counter == 1 else f"{stem}-{counter}{suffix}")
            try:
                with open(target, "xb") as handle:
                    handle.write(content)
                return target
            except FileExistsError:
                continue
        raise PathPolicyError("Could not choose a free output file name.")

    def _root_of(self, path: Path) -> Path:
        for root in self.roots:
            if path == root or root in path.parents:
                return root
        raise PathPolicyError(
            f"{path.name} is outside the allowed folders. Set {ALLOWED_DIRS_ENV} to permit more."
        )
