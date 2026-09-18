"""Interactive root-only VM credential setup or explicit atomic key rotation."""

import argparse
import getpass
import os
import stat
import tempfile
import warnings
from pathlib import Path


DIRECTORY = Path("/etc/voltpilot")
DEFAULTS = {
    "LLM_BASE_URL": "https://gen.pollinations.ai/v1",
    "LLM_MODEL": "google/gemini-3.8-flash",
    "LLM_API_KEY": "",
    "LLM_TIMEOUT_SECONDS": "10",
    "REQUEST_DEADLINE_SECONDS": "25",
    "MAX_CONCURRENT_REQUESTS": "2",
    "MAX_PENDING_REQUESTS": "6",
    "CORS_ORIGINS": "",
    "PORT": "8080",
}


def validate_key(key: str) -> None:
    if not key or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in key):
        raise ValueError("Invalid key format")


def check_owner(path: Path, mode: int, directory: bool = False) -> None:
    metadata = path.lstat()
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if (not expected_type(metadata.st_mode) or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != mode):
        raise ValueError("Unsafe configuration ownership or permissions")


def save_environment(directory: Path, key: str, rotate: bool = False) -> None:
    validate_key(key)
    directory.mkdir(mode=0o700, exist_ok=True)
    check_owner(directory, 0o700, directory=True)
    target = directory / "voltpilot.env"
    values = DEFAULTS.copy()
    if os.path.lexists(target):
        if not rotate:
            raise FileExistsError("Configuration exists")
        check_owner(target, 0o600)
        for line in target.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            name, separator, value = line.partition("=")
            if not separator or name not in values:
                raise ValueError("Unexpected runtime variable")
            values[name] = value
    elif rotate:
        raise FileNotFoundError("No configuration to rotate")
    values["LLM_API_KEY"] = key
    content = "".join(f"{name}={value}\n" for name, value in values.items())
    descriptor, temporary = tempfile.mkstemp(prefix=".voltpilot-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if rotate:
            os.replace(temporary, target)
        else:
            # Atomic, no overwrite if another setup process wrote the target.
            os.link(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rotate", action="store_true", help="Replace only the key, preserving other existing settings")
    args = parser.parse_args()
    if not hasattr(os, "geteuid") or os.geteuid() != 0 or not os.isatty(0):
        print("Run with sudo in an interactive VM terminal. Piped credentials are refused.")
        return 1
    print("Private Pollinations credential setup. Prefer a fresh restricted key with a hard spending limit.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            key = getpass.getpass("Pollinations API key (hidden): ")
        save_environment(DIRECTORY, key, rotate=args.rotate)
    except (OSError, ValueError, getpass.GetPassWarning, EOFError, KeyboardInterrupt):
        print("Setup failed safely. Check permissions or use --rotate for an existing file; do not share the key.")
        return 1
    finally:
        key = None
    print("Saved /etc/voltpilot/voltpilot.env with root-only permissions. No inference request sent.")
    print("Recreate the VoltPilot container with deploy/start.sh --replace to load the new key.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())