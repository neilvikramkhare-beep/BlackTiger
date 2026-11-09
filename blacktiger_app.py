from __future__ import annotations

import ipaddress
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime, timezone
import argparse
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Sequence
from urllib.parse import urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parent
NETWORK_ROOT = ROOT / "BlackTiger" / "network_dashboard"
ENTERPRISE_ROOT = ROOT / "BlackTiger" / "enterprise_audit"
SPIDERFOOT_ROOT = ROOT / "spiderfoot"
BRAMHASTRA_ROOT = ROOT / "Bramhastra"
BRAMHASTRA_EXE = BRAMHASTRA_ROOT / "Bramhastra_App.exe"
BRAMHASTRA_EH = BRAMHASTRA_ROOT / "BramhastraApp.eh"
BRAMHASTRA_APP_PY = BRAMHASTRA_ROOT / "bramhastra_app.py"
BRAMHASTRA_CLI = BRAMHASTRA_ROOT / "bramhastra.py"
OSINT_ROOT = ROOT / "osint-analyser"
JOHN_ROOT = ROOT / "john"
METASPLOITABLE_ROOT = ROOT / "BlackTiger" / "MyTool"
BLACKMAMBA_ROOT = ROOT / "BlackMamba"
SCOPE_FILE = ROOT / "authorized_scope.json"
REPORTS_ROOT = ROOT / "reports"
JOHN_HASH_FORMATS = ("Auto", "Raw-MD5", "NT", "bcrypt", "sha256crypt", "sha512crypt")
LOCAL_URLS = {
    "SpiderFoot": ("127.0.0.1", 5001, "http://127.0.0.1:5001/"),
    "Audit API": ("127.0.0.1", 8443, "http://127.0.0.1:8443/docs"),
}
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def get_subprocess_flags() -> dict[str, Any]:
    flags: dict[str, Any] = {}
    if sys.platform == "win32" and CREATE_NO_WINDOW:
        flags["creationflags"] = CREATE_NO_WINDOW
    return flags


def open_path_cross_platform(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    if hasattr(os, "startfile"):
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        if shutil.which("xdg-open"):
            subprocess.Popen(["xdg-open", str(path)])
        else:
            pass


def find_spiderfoot_python(root: Path = ROOT) -> str:
    venv = root / "spiderfoot" / ".venv"
    if sys.platform == "win32":
        candidates = [
            venv / "Scripts" / "python.exe",
            venv / "Scripts" / "python",
            venv / "bin" / "python3",
            venv / "bin" / "python",
        ]
    else:
        candidates = [
            venv / "bin" / "python3",
            venv / "bin" / "python",
            venv / "Scripts" / "python.exe",
            venv / "Scripts" / "python",
        ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def resolve_bramhastra_launcher(root: Path = ROOT) -> tuple[list[str], Path]:
    bramhastra_dir = root / "Bramhastra"
    earth_cmd = shutil.which("earth")
    if not earth_cmd and sys.platform == "win32":
        local_earth = Path(os.environ.get("LOCALAPPDATA", "")) / "EarthLang" / "earth.exe"
        if local_earth.is_file():
            earth_cmd = str(local_earth)

    eh_file = bramhastra_dir / "BramhastraApp.eh"
    if earth_cmd and eh_file.is_file():
        return [earth_cmd, str(eh_file)], bramhastra_dir

    exe_file = bramhastra_dir / "Bramhastra_App.exe"
    if sys.platform == "win32" and exe_file.is_file():
        return [str(exe_file)], bramhastra_dir

    py_gui = bramhastra_dir / "bramhastra_app.py"
    if py_gui.is_file():
        return [project_python(bramhastra_dir), str(py_gui)], bramhastra_dir

    py_cli = bramhastra_dir / "bramhastra.py"
    if py_cli.is_file():
        return [project_python(bramhastra_dir), str(py_cli)], bramhastra_dir

    raise FileNotFoundError("Bramhastra application could not be found.")


def check_blackmamba(root: Path = ROOT) -> dict[str, Any]:
    blackmamba_dir = root / "BlackMamba"
    has_source = (blackmamba_dir / "mamba_model.py").is_file()
    status: dict[str, Any] = {
        "installed": has_source,
        "source_dir": str(blackmamba_dir),
        "pytorch_available": False,
        "cuda_available": False,
        "details": "",
    }
    if not has_source:
        status["details"] = "BlackMamba source files not found."
        return status

    try:
        import torch  # type: ignore
        status["pytorch_available"] = True
        status["torch_version"] = torch.__version__
        status["cuda_available"] = torch.cuda.is_available()
        if status["cuda_available"]:
            status["cuda_device_name"] = torch.cuda.get_device_name(0)
            status["details"] = f"PyTorch {torch.__version__} with CUDA ({status['cuda_device_name']})"
        else:
            status["details"] = f"PyTorch {torch.__version__} (CPU mode; GPU recommended for inference)"
    except ImportError:
        status["details"] = "PyTorch not installed in this environment. Install torch to run inference."

    return status


def test_blackmamba(root: Path = ROOT) -> tuple[bool, str]:
    mamba_dir = root / "BlackMamba"
    if not (mamba_dir / "mamba_model.py").is_file():
        return False, "BlackMamba source files not found."
    try:
        if str(mamba_dir) not in sys.path:
            sys.path.insert(0, str(mamba_dir))
        import torch  # type: ignore
        from mamba_config import MambaConfig  # type: ignore
        from mamba_model import MambaModel  # type: ignore

        cfg = MambaConfig(
            num_layers=2,
            hidden_size=64,
            state_size=16,
            conv_dimension=4,
            vocab_size=100,
            expansion_factor=2,
            mamba_moe_layers=[1],
            ffn_hidden_size=128,
        )
        model = MambaModel(config=cfg, max_sequence_length=32)
        model.eval()
        test_input = torch.tensor([[1, 2, 3]], dtype=torch.long)
        with torch.no_grad():
            out = model(test_input)
        return True, f"BlackMamba test forward pass successful! Output tensor shape: {list(out.shape)}"
    except Exception as exc:
        return False, f"BlackMamba forward pass test: {exc}"


def build_john_test_command(executable: Path) -> list[str]:
    if not executable.is_file():
        raise ValueError("John the Ripper executable is not installed.")
    return [str(executable), "--test"]


def build_spiderfoot_scan_command(
    python: str,
    target: str,
    modules: str = "",
) -> list[str]:
    if not target.strip():
        raise ValueError("SpiderFoot scan requires a target domain, IP, or hostname.")
    cmd = [python, "sf.py", "-s", target.strip(), "-u", "cli"]
    if modules.strip():
        cmd.extend(["-m", modules.strip()])
    return cmd


def read_threat_model(root: Path = ROOT) -> dict[str, Any]:
    threat_file = root / "BlackTiger" / "enterprise_audit" / "gov_threat_model.json"
    if not threat_file.is_file():
        raise FileNotFoundError(f"Threat model file not found: {threat_file}")
    return json.loads(threat_file.read_text(encoding="utf-8"))


def build_network_command(
    tool: str,
    target: str,
    ports: str = "22,80,443,8080",
    wordlist: str = "",
    python: str = sys.executable,
    output: str = "audit_report",
    min_length: int = 8,
    require_complex: bool = False,
) -> list[str]:
    """Build an argv list for a network-dashboard tool without invoking a shell."""
    if not target.strip():
        raise ValueError("Enter a host, URL, or other input for the selected tool.")

    script = str(NETWORK_ROOT / "main.py")
    commands = {
        "ping": [python, script, "ping", target.strip()],
        "scanner": [python, script, "scanner", target.strip(), "--ports", ports],
        "portscan": [python, script, "portscan", target.strip(), "--ports", ports],
    }
    if tool == "webaudit":
        if not wordlist:
            raise ValueError("Choose a local endpoint wordlist file for web audits.")
        return [python, script, "webaudit", target.strip(), wordlist]
    if tool == "policyaudit":
        cmd = [python, script, "policyaudit", target.strip(), "--min-length", str(min_length)]
        if wordlist:
            cmd.extend(["--wordlist", wordlist])
        if require_complex:
            cmd.append("--require-complex")
        return cmd
    if tool == "reporter":
        return [python, script, "reporter", target.strip(), "--output", output]
    try:
        return commands[tool]
    except KeyError as exc:
        raise ValueError(f"Unsupported network tool: {tool}") from exc


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return values
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def normalize_scope_target(value: str) -> str:
    """Normalize a single IPv4 address/CIDR or exact hostname/URL for scope checks."""
    candidate = value.strip()
    if not candidate or "," in candidate or "*" in candidate:
        raise ValueError("Enter one exact hostname, URL, IPv4 address, or IPv4 CIDR.")
    try:
        network = ipaddress.ip_network(candidate, strict=False)
    except ValueError:
        parsed = urlsplit(candidate if "://" in candidate else f"//{candidate}")
        try:
            host = parsed.hostname
            parsed.port
        except ValueError as exc:
            raise ValueError("The target URL or port is not valid.") from exc
        if not host or parsed.username is not None or parsed.password is not None:
            raise ValueError("Enter one exact hostname, URL, IPv4 address, or IPv4 CIDR.")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            try:
                host = host.encode("idna").decode("ascii").lower().rstrip(".")
            except UnicodeError as exc:
                raise ValueError("The target hostname is not valid.") from exc
            labels = host.split(".")
            if len(host) > 253 or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in labels
            ):
                raise ValueError("The target hostname is not valid.")
            return host
        if address.version != 4:
            raise ValueError("Only IPv4 targets are supported by the current network scanners.")
        return str(address)

    if network.version != 4:
        raise ValueError("Only IPv4 targets are supported by the current network scanners.")
    if network.num_addresses > 256:
        raise ValueError("Authorized IPv4 ranges are limited to 256 addresses.")
    return str(network) if "/" in candidate else str(network.network_address)


def target_is_in_scope(target: str, allowed_scope: Sequence[str]) -> bool:
    normalized_target = normalize_scope_target(target)
    try:
        requested_network = ipaddress.ip_network(normalized_target, strict=False)
    except ValueError:
        return normalized_target in allowed_scope

    for entry in allowed_scope:
        try:
            allowed_network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            continue
        if requested_network.subnet_of(allowed_network):
            return True
    return False


def _is_ipv4_range(target: str) -> bool:
    normalized_target = normalize_scope_target(target)
    try:
        network = ipaddress.ip_network(normalized_target, strict=False)
    except ValueError:
        return False
    return network.prefixlen < 32


def sanitize_report_target(target: str) -> str:
    """Omit URL credentials, query strings, and fragments from saved evidence."""
    parsed = urlsplit(target if "://" in target else f"//{target}")
    if not parsed.hostname:
        return target
    host = parsed.hostname
    if ":" in host:
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is not None:
        host = f"{host}:{port}"
    if parsed.scheme:
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    return f"{host}{parsed.path}"


def sanitize_report_output(lines: Sequence[str]) -> list[str]:
    url_pattern = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)

    def redact(match: re.Match[str]) -> str:
        value = match.group(0)
        url = value.rstrip(".,;:)]}")
        suffix = value[len(url):]
        return sanitize_report_target(url) + suffix

    return [url_pattern.sub(redact, line) for line in lines]


def load_scope(path: Path = SCOPE_FILE) -> list[str]:
    if not path.exists():
        return []
    content = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(content, list) or any(not isinstance(item, str) for item in content):
        raise ValueError("Authorized scope must be a JSON list of target strings.")
    return sorted({normalize_scope_target(item) for item in content})


def save_scope(path: Path, scope: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(sorted(set(scope)), indent=2) + "\n", encoding="utf-8")
    os.replace(temporary_path, path)


def write_evidence_report(
    reports_dir: Path,
    tool: str,
    target: str,
    allowed_scope: Sequence[str],
    started_at: str,
    finished_at: str,
    exit_code: int,
    output_lines: Sequence[str],
) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc)
    report_path = reports_dir / (
        f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-{tool.lower().replace(' ', '-')}.json"
    )
    report = {
        "schema_version": 1,
        "tool": tool,
        "target": sanitize_report_target(target),
        "authorized_scope": sorted(allowed_scope),
        "started_at": started_at,
        "finished_at": finished_at,
        "exit_code": exit_code,
        "output": sanitize_report_output(output_lines),
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report_path


def compose_command() -> list[str]:
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    if shutil.which("docker"):
        return ["docker", "compose"]
    raise FileNotFoundError("Install Docker Desktop with Docker Compose to run OSINT services.")


def find_john(root: Path = ROOT) -> Path | None:
    bundled_win = root / "john" / ".deps" / "windows-x64-1.9.1-ce" / "JtR" / "run" / "john.exe"
    bundled_posix = root / "john" / "run" / "john"
    bundled_posix_exe = root / "john" / "run" / "john.exe"
    external = shutil.which("john")
    candidates = [
        bundled_win,
        bundled_posix,
        bundled_posix_exe,
        Path(external) if external else None,
        Path("/usr/bin/john"),
        Path("/usr/sbin/john"),
        Path("/usr/local/bin/john"),
    ]
    return next((path for path in candidates if path is not None and path.is_file()), None)


def john_pot_file(root: Path = ROOT) -> Path:
    return root / "reports" / "john.pot"


def john_format_arguments(hash_format: str) -> list[str]:
    if hash_format not in JOHN_HASH_FORMATS:
        raise ValueError("Choose a supported local hash format.")
    return [] if hash_format == "Auto" else [f"--format={hash_format}"]


def build_john_command(
    executable: Path,
    hashes_file: str,
    wordlist_file: str,
    pot_file: Path,
    hash_format: str = "Auto",
) -> list[str]:
    hashes = Path(hashes_file)
    wordlist = Path(wordlist_file)
    if not executable.is_file():
        raise ValueError("John the Ripper executable is not installed.")
    if not hashes.is_file() or hashes.stat().st_size == 0:
        raise ValueError("Choose a non-empty local hash file.")
    if not wordlist.is_file() or wordlist.stat().st_size == 0:
        raise ValueError("Choose a non-empty local wordlist file.")
    pot_file.parent.mkdir(parents=True, exist_ok=True)
    return [
        str(executable),
        *john_format_arguments(hash_format),
        f"--pot={pot_file}",
        f"--wordlist={wordlist}",
        str(hashes),
    ]


def build_john_show_command(
    executable: Path, hashes_file: str, pot_file: Path, hash_format: str = "Auto"
) -> list[str]:
    hashes = Path(hashes_file)
    if not executable.is_file():
        raise ValueError("John the Ripper executable is not installed.")
    if not hashes.is_file() or hashes.stat().st_size == 0:
        raise ValueError("Choose a non-empty local hash file.")
    return [
        str(executable),
        *john_format_arguments(hash_format),
        f"--pot={pot_file}",
        "--show",
        str(hashes),
    ]


def project_python(project_root: Path) -> str:
    """Use the project's isolated Python environment when it is installed."""
    venv = project_root / ".venv"
    if sys.platform == "win32":
        candidates = [
            venv / "Scripts" / "python.exe",
            venv / "Scripts" / "python",
            venv / "bin" / "python3",
            venv / "bin" / "python",
        ]
    else:
        candidates = [
            venv / "bin" / "python3",
            venv / "bin" / "python",
            venv / "Scripts" / "python.exe",
            venv / "Scripts" / "python",
        ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def find_nmap(root: Path = ROOT) -> Path | None:
    candidates = [
        Path(shutil.which("nmap")) if shutil.which("nmap") else None,
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Nmap" / "nmap.exe",
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Nmap" / "nmap.exe",
        root / "nmap" / "nmap.exe",
        root / "nmap" / "nmap",
        Path("/usr/bin/nmap"),
        Path("/usr/local/bin/nmap"),
    ]
    return next((path for path in candidates if path is not None and path.is_file()), None)


def build_nmap_command(
    executable: Path,
    target: str,
    ports: str = "",
    scan_type: str = "connect",
) -> list[str]:
    if not executable.is_file():
        raise ValueError("Nmap is not installed.")
    if not target.strip() or target.startswith("-"):
        raise ValueError("Enter a single authorized Nmap target.")
    if _is_ipv4_range(target):
        try:
            network = ipaddress.ip_network(normalize_scope_target(target), strict=False)
        except ValueError as exc:
            raise ValueError("Nmap must receive a valid authorized target.") from exc
        if network.num_addresses > 256:
            raise ValueError("Nmap targets are limited to 256 IPv4 addresses at a time.")

    type_flags = {
        "connect": ["-sT"],
        "syn": ["-sS"],
        "fast": ["-F"],
        "version": ["-sV"],
        "ping": ["-sn"],
    }
    scan_flags = type_flags.get(scan_type, ["-sT"])
    cmd = [str(executable), "-n", "-Pn", *scan_flags, "-T3"]
    if ports.strip() and scan_type != "fast":
        cmd.extend(["-p", ports.strip()])
    cmd.append(target)
    return cmd


def lab_requirements(root: Path = ROOT, free_bytes: int | None = None) -> list[str]:
    """Describe external requirements without provisioning an intentionally vulnerable VM."""
    if free_bytes is None:
        free_bytes = shutil.disk_usage(root).free
    missing = []
    if free_bytes < 65 * 1024**3:
        missing.append(f"at least 65 GB free disk space (currently {free_bytes / 1024**3:.1f} GB)")
    if not shutil.which("vagrant"):
        missing.append("Vagrant")
    if not (
        shutil.which("VBoxManage")
        or Path("C:/Program Files/Oracle/VirtualBox/VBoxManage.exe").is_file()
        or Path("/usr/bin/VBoxManage").is_file()
        or Path("/usr/local/bin/VBoxManage").is_file()
    ):
        missing.append("VirtualBox")
    return missing


class BlackTigerApp:
    def __init__(self, root: tk.Tk | None = None):
        self.root = root or tk.Tk()
        self.root.title("BlackTiger Security Toolkit")
        self.root.geometry("1050x770")
        self.root.minsize(820, 620)

        self.target = tk.StringVar()
        self.ports = tk.StringVar(value="22,80,443,8080")
        self.tool = tk.StringVar(value="scanner")
        self.wordlist = tk.StringVar()
        self.policy_min_length = tk.StringVar(value="8")
        self.policy_require_complex = tk.BooleanVar(value=False)
        self.report_output = tk.StringVar(value="audit_report")
        self.selected_hash_file = tk.StringVar()
        self.selected_wordlist = tk.StringVar()
        self.john_format = tk.StringVar(value="Auto")
        self.nmap_scan_type = tk.StringVar(value="connect")
        self.output_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.services: dict[str, subprocess.Popen[str]] = {}
        self.jobs: dict[str, subprocess.Popen[str]] = {}
        self.enterprise_audit_pending = False
        self.scope_error: str | None = None
        try:
            self.scope_targets = set(load_scope())
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self.scope_targets = set()
            self.scope_error = str(exc)

        self._build_ui()
        if self.scope_error:
            self._log(f"Could not load saved authorized scope: {self.scope_error}")
        self._refresh_status()
        self.root.after(100, self._drain_output)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        style.configure("Title.TLabel", font=("Segoe UI", 23, "bold"))
        style.configure("Subtitle.TLabel", foreground="#596579")
        style.configure("Section.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("Accent.TButton", padding=(12, 7))
        style.configure("TNotebook.Tab", padding=(14, 9))

        self.root.geometry("1240x900")
        self.root.minsize(980, 720)
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 12))
        heading = ttk.Frame(header)
        heading.pack(side="left", fill="x", expand=True)
        ttk.Label(heading, text="BlackTiger", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            heading,
            text="Local security, intelligence, and file-protection workspace",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 0))
        ttk.Label(
            header,
            text="LOCAL WORKSPACE",
            padding=(10, 6),
            relief="groove",
        ).pack(side="right", anchor="n")

        target_frame = ttk.LabelFrame(outer, text="Authorization & target", padding=10)
        target_frame.pack(fill="x", pady=(0, 10))
        target_frame.columnconfigure(0, weight=1)
        target_row = ttk.Frame(target_frame)
        target_row.grid(row=0, column=0, sticky="ew")
        target_row.columnconfigure(0, weight=1)
        ttk.Label(target_row, text="Shared target for authorized tools").grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        ttk.Entry(target_row, textvariable=self.target).grid(
            row=1, column=0, sticky="ew", padx=(0, 10)
        )
        ttk.Label(
            target_row,
            text="Use only systems and data you own or are explicitly authorized to assess.",
            foreground="#9c291b",
        ).grid(row=2, column=0, sticky="w", pady=(5, 0))
        ttk.Label(target_row, text="Authorized scope").grid(
            row=0, column=1, sticky="w", pady=(0, 4)
        )
        self.scope_list = tk.Listbox(
            target_row,
            height=2,
            width=35,
            selectmode="extended",
            exportselection=False,
            relief="solid",
            borderwidth=1,
        )
        self.scope_list.grid(row=1, column=1, rowspan=2, sticky="nsew")
        scope_actions = ttk.Frame(target_row)
        scope_actions.grid(row=1, column=2, rowspan=2, sticky="ns", padx=(8, 0))
        ttk.Button(
            scope_actions,
            text="Add target",
            command=self.add_target_to_scope,
        ).pack(fill="x")
        ttk.Button(
            scope_actions,
            text="Remove selected",
            command=self.remove_scope_targets,
        ).pack(fill="x", pady=(6, 0))
        self._refresh_scope_display()

        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True, pady=(0, 10))

        overview = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(overview, text="Overview")
        ttk.Label(overview, text="Workspace status", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            overview,
            text="Availability of local services, installed tools, and the active scope.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 10))
        self.status_text = tk.StringVar()
        ttk.Label(
            overview,
            textvariable=self.status_text,
            justify="left",
            wraplength=1080,
            padding=12,
            relief="groove",
        ).pack(fill="x")
        overview_actions = ttk.Frame(overview)
        overview_actions.pack(fill="x", pady=(12, 0))
        ttk.Button(
            overview_actions,
            text="Refresh status",
            command=self._refresh_status,
        ).pack(side="left")
        ttk.Button(
            overview_actions,
            text="Open reports",
            command=self.open_reports,
        ).pack(side="left", padx=(8, 0))
        ttk.Label(
            overview,
            text="Network actions remain limited to the exact targets or IPv4 ranges in your local authorized scope.",
            style="Subtitle.TLabel",
            wraplength=1080,
        ).pack(anchor="w", pady=(18, 0))

        network = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(network, text="Network")
        network_card = ttk.LabelFrame(network, text="Network Dashboard", padding=12)
        network_card.pack(fill="x", pady=(0, 12))
        ttk.Label(
            network_card,
            text="Choose one diagnostic. Inputs are passed directly to the local tool without a shell.",
            style="Subtitle.TLabel",
            wraplength=1050,
        ).pack(anchor="w", pady=(0, 10))
        selection_row = ttk.Frame(network_card)
        selection_row.pack(fill="x", pady=(0, 8))
        ttk.Label(selection_row, text="Tool").pack(side="left")
        self.network_tool_combo = ttk.Combobox(
            selection_row,
            textvariable=self.tool,
            values=("scanner", "portscan", "ping", "webaudit", "policyaudit", "reporter"),
            state="readonly",
            width=18,
        )
        self.network_tool_combo.pack(side="left", padx=(8, 0))
        self.network_tool_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._update_network_options()
        )

        self.network_option_rows: dict[str, ttk.Frame] = {}
        self.network_option_rows["ports"] = ttk.Frame(network_card)
        ttk.Label(self.network_option_rows["ports"], text="Ports").pack(side="left")
        ttk.Entry(
            self.network_option_rows["ports"],
            textvariable=self.ports,
            width=34,
        ).pack(side="left", padx=(12, 0))

        self.network_option_rows["wordlist"] = ttk.Frame(network_card)
        ttk.Label(self.network_option_rows["wordlist"], text="Local wordlist").pack(side="left")
        ttk.Button(
            self.network_option_rows["wordlist"],
            text="Choose file...",
            command=self._select_wordlist,
        ).pack(side="left", padx=(12, 8))
        ttk.Label(
            self.network_option_rows["wordlist"],
            textvariable=self.wordlist,
            wraplength=780,
        ).pack(side="left", fill="x", expand=True)

        self.network_option_rows["policy"] = ttk.Frame(network_card)
        ttk.Label(self.network_option_rows["policy"], text="Minimum length").pack(side="left")
        ttk.Entry(
            self.network_option_rows["policy"],
            textvariable=self.policy_min_length,
            width=8,
        ).pack(side="left", padx=(8, 16))
        ttk.Checkbutton(
            self.network_option_rows["policy"],
            text="Require character complexity",
            variable=self.policy_require_complex,
        ).pack(side="left")

        self.network_option_rows["report"] = ttk.Frame(network_card)
        ttk.Label(self.network_option_rows["report"], text="Report name").pack(side="left")
        ttk.Entry(
            self.network_option_rows["report"],
            textvariable=self.report_output,
            width=34,
        ).pack(side="left", padx=(12, 0))
        self._update_network_options()
        ttk.Button(
            network_card,
            text="Run network diagnostic",
            style="Accent.TButton",
            command=self.run_network_tool,
        ).pack(anchor="e", pady=(10, 0))

        nmap_card = ttk.LabelFrame(network, text="Nmap", padding=12)
        nmap_card.pack(fill="x")
        ttk.Label(
            nmap_card,
            text="Nmap uses the selected shared target and port list. A confirmation and exact scope check are required.",
            style="Subtitle.TLabel",
            wraplength=1050,
        ).pack(anchor="w", pady=(0, 8))
        row = ttk.Frame(nmap_card)
        row.pack(fill="x")
        ttk.Label(row, text="Scan profile").pack(side="left")
        ttk.Combobox(
            row,
            textvariable=self.nmap_scan_type,
            values=("connect", "fast", "ping", "version", "syn"),
            state="readonly",
            width=14,
        ).pack(side="left", padx=(8, 12))
        ttk.Button(row, text="Run Nmap", command=self.run_nmap).pack(side="left")
        ttk.Button(
            row,
            text="Open Nmap folder",
            command=lambda: self._open_path(ROOT / "nmap"),
        ).pack(side="left", padx=8)

        intelligence = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(intelligence, text="Intelligence & Audit")
        spiderfoot_card = ttk.LabelFrame(intelligence, text="SpiderFoot", padding=12)
        spiderfoot_card.pack(fill="x", pady=(0, 12))
        ttk.Label(
            spiderfoot_card,
            text="Open its local web interface or run a target scan after the scope check.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        row = ttk.Frame(spiderfoot_card)
        row.pack(fill="x")
        ttk.Button(
            row,
            text="Start / open web interface",
            command=self.start_spiderfoot,
        ).pack(side="left")
        ttk.Button(
            row,
            text="Run authorized CLI scan",
            command=self.run_spiderfoot_cli_scan,
        ).pack(side="left", padx=8)

        audit_card = ttk.LabelFrame(intelligence, text="Enterprise Security Audit", padding=12)
        audit_card.pack(fill="x")
        ttk.Label(
            audit_card,
            text="Run scoped checks, inspect the included threat-model baseline, or triage local SIEM logs.",
            style="Subtitle.TLabel",
            wraplength=1050,
        ).pack(anchor="w", pady=(0, 8))
        row = ttk.Frame(audit_card)
        row.pack(fill="x")
        ttk.Button(
            row,
            text="Run authorized audit",
            style="Accent.TButton",
            command=self.run_enterprise_audit,
        ).pack(side="left")
        ttk.Button(row, text="Start Audit API", command=self.start_audit_api).pack(
            side="left", padx=8
        )
        ttk.Button(row, text="Threat model", command=self.show_threat_model).pack(
            side="left"
        )
        ttk.Button(row, text="Parse SIEM logs", command=self.triage_siem_logs).pack(
            side="left", padx=8
        )

        files = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(files, text="Passwords & Files")
        john_card = ttk.LabelFrame(files, text="John the Ripper - local password audit", padding=12)
        john_card.pack(fill="x", pady=(0, 12))
        ttk.Label(
            john_card,
            text="Select local files only. Recovered credentials are sensitive and remain in reports\\john.pot.",
            style="Subtitle.TLabel",
            wraplength=1050,
        ).pack(anchor="w", pady=(0, 10))
        row = ttk.Frame(john_card)
        row.pack(fill="x", pady=3)
        ttk.Button(row, text="Choose hash file...", command=self._select_hash_file).pack(side="left")
        ttk.Label(row, textvariable=self.selected_hash_file, wraplength=780).pack(
            side="left", fill="x", expand=True, padx=8
        )
        row = ttk.Frame(john_card)
        row.pack(fill="x", pady=3)
        ttk.Button(row, text="Choose wordlist...", command=self._select_john_wordlist).pack(
            side="left"
        )
        ttk.Label(row, textvariable=self.selected_wordlist, wraplength=780).pack(
            side="left", fill="x", expand=True, padx=8
        )
        row = ttk.Frame(john_card)
        row.pack(fill="x", pady=(8, 3))
        ttk.Label(row, text="Hash format").pack(side="left")
        ttk.Combobox(
            row,
            textvariable=self.john_format,
            values=JOHN_HASH_FORMATS,
            state="readonly",
            width=18,
        ).pack(side="left", padx=8)
        ttk.Button(row, text="Run local audit", command=self.run_john).pack(side="left")
        ttk.Button(row, text="Stop", command=lambda: self.stop_job("john")).pack(
            side="left", padx=6
        )
        ttk.Button(row, text="Show results", command=self.show_john_results).pack(
            side="left"
        )
        ttk.Button(row, text="Benchmark", command=self.run_john_benchmark).pack(
            side="left", padx=6
        )

        bramhastra_card = ttk.LabelFrame(files, text="Bramhastra file protection", padding=12)
        bramhastra_card.pack(fill="x")
        ttk.Label(
            bramhastra_card,
            text="Open the installed Bramhastra interface for local file encryption and decryption.",
            style="Subtitle.TLabel",
            wraplength=1050,
        ).pack(anchor="w", pady=(0, 8))
        ttk.Button(
            bramhastra_card,
            text="Open Bramhastra",
            command=self.open_bramhastra,
        ).pack(anchor="w")

        pipeline = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(pipeline, text="OSINT Pipeline")
        pipeline_card = ttk.LabelFrame(pipeline, text="Docker services", padding=12)
        pipeline_card.pack(fill="x")
        ttk.Label(
            pipeline_card,
            text="Configure osint-analyser/.env before starting services. The collector also requires your own Telegram API credentials.",
            style="Subtitle.TLabel",
            wraplength=1050,
        ).pack(anchor="w", pady=(0, 10))
        row = ttk.Frame(pipeline_card)
        row.pack(fill="x", pady=3)
        ttk.Button(row, text="Start backend", command=self.start_osint).pack(side="left")
        ttk.Button(row, text="Start collector", command=self.start_osint_collector).pack(
            side="left", padx=8
        )
        ttk.Button(row, text="Stop services", command=self.stop_osint).pack(side="left")
        ttk.Button(row, text="Service status", command=self.status_osint).pack(
            side="left", padx=8
        )
        row = ttk.Frame(pipeline_card)
        row.pack(fill="x", pady=(8, 3))
        ttk.Button(row, text="RabbitMQ management", command=self.open_rabbitmq).pack(
            side="left"
        )
        ttk.Button(row, text="Open .env", command=self.open_osint_env).pack(
            side="left", padx=8
        )
        ttk.Button(row, text="Open reports", command=self.open_reports).pack(side="left")
        ttk.Label(
            pipeline,
            text="Starting or stopping these services affects the local Docker Compose project only.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(12, 0))

        ai_lab = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(ai_lab, text="AI & Lab")
        ai_card = ttk.LabelFrame(ai_lab, text="BlackMamba AI", padding=12)
        ai_card.pack(fill="x", pady=(0, 12))
        ttk.Label(
            ai_card,
            text="Check the local PyTorch/CUDA environment or run the included small forward-pass self-test.",
            style="Subtitle.TLabel",
            wraplength=1050,
        ).pack(anchor="w", pady=(0, 8))
        row = ttk.Frame(ai_card)
        row.pack(fill="x")
        ttk.Button(row, text="Environment details", command=self.show_blackmamba_info).pack(
            side="left"
        )
        ttk.Button(row, text="Run self-test", command=self.run_blackmamba_test).pack(
            side="left", padx=8
        )

        lab_card = ttk.LabelFrame(ai_lab, text="Metasploitable3 isolated lab", padding=12)
        lab_card.pack(fill="x")
        ttk.Label(
            lab_card,
            text="This tab only checks prerequisites and opens documentation. The intentionally vulnerable VM is not provisioned or started by BlackTiger.",
            style="Subtitle.TLabel",
            wraplength=1050,
        ).pack(anchor="w", pady=(0, 8))
        ttk.Button(lab_card, text="Prerequisites & documentation", command=self.open_lab_docs).pack(
            side="left"
        )

        log_frame = ttk.LabelFrame(outer, text="Activity", padding=6)
        log_frame.pack(fill="x")
        self.log = tk.Text(
            log_frame,
            height=7,
            wrap="word",
            state="disabled",
            borderwidth=0,
            padx=8,
            pady=6,
        )
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._log("Ready. Background services started by this window are stopped when it closes.")

    def _update_network_options(self) -> None:
        for row in self.network_option_rows.values():
            row.pack_forget()

        tool = self.tool.get()
        if tool in ("scanner", "portscan"):
            self.network_option_rows["ports"].pack(fill="x", pady=4)
        if tool in ("webaudit", "policyaudit"):
            self.network_option_rows["wordlist"].pack(fill="x", pady=4)
        if tool == "policyaudit":
            self.network_option_rows["policy"].pack(fill="x", pady=4)
        if tool == "reporter":
            self.network_option_rows["report"].pack(fill="x", pady=4)

    def _log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _post(self, kind: str, message: str) -> None:
        self.output_queue.put((kind, message))

    def _drain_output(self) -> None:
        while True:
            try:
                kind, message = self.output_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "open":
                webbrowser.open_new_tab(message)
            elif kind == "status":
                self._refresh_status()
            elif kind == "dialog":
                messagebox.showerror("BlackTiger", message, parent=self.root)
            else:
                self._log(message)
        self.root.after(100, self._drain_output)

    def _refresh_status(self) -> None:
        statuses = []
        for name, (host, port, url) in LOCAL_URLS.items():
            active = self._port_open(host, port)
            statuses.append(f"{name}: {'running' if active else 'stopped'} ({url})")

        john = find_john()
        statuses.append(f"John the Ripper: {'ready' if john else 'not installed'}")
        statuses.append(
            f"Authorized scope: {len(self.scope_targets)} target(s); local evidence reports: {REPORTS_ROOT}"
        )
        nmap = find_nmap()
        statuses.append(
            f"Nmap: {'ready' if nmap else 'not installed (source is included; install Nmap separately)'}"
        )
        missing = lab_requirements()
        statuses.append(
            "Metasploitable3 lab: "
            + ("ready to review" if not missing else "not runnable here; needs " + ", ".join(missing))
        )
        mamba = check_blackmamba()
        statuses.append(f"BlackMamba AI: {mamba['details']}")
        self.status_text.set("\n".join(statuses))

    @staticmethod
    def _port_open(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=0.4):
                return True
        except OSError:
            return False

    def _select_wordlist(self) -> None:
        path = filedialog.askopenfilename(title="Select local web endpoint wordlist")
        if path:
            self.wordlist.set(path)

    def _select_hash_file(self) -> None:
        path = filedialog.askopenfilename(title="Select an authorized local hash file")
        if path:
            self.selected_hash_file.set(path)

    def _select_john_wordlist(self) -> None:
        path = filedialog.askopenfilename(title="Select a local password wordlist")
        if path:
            self.selected_wordlist.set(path)

    def _refresh_scope_display(self) -> None:
        self.scope_list.delete(0, "end")
        for target in sorted(self.scope_targets):
            self.scope_list.insert("end", target)

    def add_target_to_scope(self) -> None:
        try:
            target = normalize_scope_target(self.target.get())
        except ValueError as exc:
            messagebox.showerror("Invalid scope target", str(exc), parent=self.root)
            return
        if target in self.scope_targets:
            self._log(f"{target} is already in the authorized scope.")
            return
        if not messagebox.askyesno(
            "Authorize testing scope",
            f"Add {target} to the locally saved allowlist for authorized security testing?",
            parent=self.root,
        ):
            return
        updated_scope = {*self.scope_targets, target}
        try:
            save_scope(SCOPE_FILE, updated_scope)
        except OSError as exc:
            messagebox.showerror("Scope not saved", str(exc), parent=self.root)
            return
        self.scope_targets = updated_scope
        self._refresh_scope_display()
        self._log(f"Added {target} to the local authorized scope.")

    def remove_scope_targets(self) -> None:
        selected = self.scope_list.curselection()
        if not selected:
            messagebox.showinfo("Authorized scope", "Select one or more scope entries to remove.", parent=self.root)
            return
        remaining = set(self.scope_targets)
        for index in selected:
            remaining.discard(self.scope_list.get(index))
        try:
            save_scope(SCOPE_FILE, remaining)
        except OSError as exc:
            messagebox.showerror("Scope not saved", str(exc), parent=self.root)
            return
        self.scope_targets = remaining
        self._refresh_scope_display()
        self._log("Removed the selected entries from the local authorized scope.")

    def _ensure_target_in_scope(self, target: str) -> bool:
        try:
            authorized = target_is_in_scope(target, self.scope_targets)
        except ValueError as exc:
            messagebox.showerror("Invalid target", str(exc), parent=self.root)
            return False
        if authorized:
            return True
        messagebox.showerror(
            "Target outside authorized scope",
            "Add this exact host or containing IPv4 range to Authorized scope before testing it.",
            parent=self.root,
        )
        return False

    def _run_command(
        self,
        label: str,
        command: Sequence[str],
        cwd: Path,
        job_key: str | None = None,
        evidence: tuple[str, str] | None = None,
    ) -> None:
        if job_key and job_key in self.jobs and self.jobs[job_key].poll() is None:
            messagebox.showinfo("BlackTiger", f"{label} is already running.", parent=self.root)
            return
        self._log(f"Starting {label}…")
        try:
            process = subprocess.Popen(
                list(command),
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **get_subprocess_flags(),
            )
        except OSError as exc:
            self._log(f"{label} could not start: {exc}")
            return
        if job_key:
            self.jobs[job_key] = process
        started_at = datetime.now(timezone.utc).isoformat()
        evidence_scope = tuple(sorted(self.scope_targets)) if evidence else ()

        def collect() -> None:
            assert process.stdout is not None
            output_lines = []
            for line in process.stdout:
                line = line.rstrip()
                output_lines.append(line)
                self._post("log", f"[{label}] {line}")
            exit_code = process.wait()
            if evidence:
                try:
                    report_path = write_evidence_report(
                        REPORTS_ROOT,
                        evidence[0],
                        evidence[1],
                        evidence_scope,
                        started_at,
                        datetime.now(timezone.utc).isoformat(),
                        exit_code,
                        output_lines,
                    )
                    self._post("log", f"Local evidence report saved to {report_path}")
                except OSError as exc:
                    self._post("log", f"Could not save the local evidence report: {exc}")
            self._post(
                "log",
                f"{label} finished with exit code {exit_code}."
                if exit_code == 0
                else f"{label} exited with code {exit_code}. Check its output above.",
            )
            if job_key:
                self._post("status", "")

        threading.Thread(target=collect, name=f"blacktiger-{job_key or label}", daemon=True).start()

    def _start_service(self, name: str, command: Sequence[str], cwd: Path, port: int) -> None:
        current = self.services.get(name)
        if current and current.poll() is None:
            self._log(f"{name} is already running in this window.")
            return
        if self._port_open("127.0.0.1", port):
            self._log(f"{name} is already available at {LOCAL_URLS[name][2]}.")
            self._post("open", LOCAL_URLS[name][2])
            return
        try:
            process = subprocess.Popen(
                list(command),
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
                **get_subprocess_flags(),
            )
        except OSError as exc:
            self._log(f"{name} could not start: {exc}")
            return
        self.services[name] = process
        threading.Thread(
            target=self._watch_service,
            args=(name, process),
            name=f"blacktiger-{name.lower().replace(' ', '-')}",
            daemon=True,
        ).start()
        self._log(f"Starting {name}…")
        threading.Thread(
            target=self._wait_for_service,
            args=(name, port, process),
            daemon=True,
        ).start()

    def _watch_service(self, name: str, process: subprocess.Popen[str]) -> None:
        if process.stdout is not None:
            for line in process.stdout:
                self._post("log", f"[{name}] {line.rstrip()}")
        exit_code = process.wait()
        self._post("log", f"{name} stopped (exit code {exit_code}).")
        self._post("status", "")

    def _wait_for_service(self, name: str, port: int, process: subprocess.Popen[str]) -> None:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and process.poll() is None:
            if self._port_open("127.0.0.1", port):
                url = LOCAL_URLS[name][2]
                self._post("log", f"{name} is ready at {url}")
                self._post("open", url)
                self._post("status", "")
                return
            time.sleep(0.5)
        if process.poll() is None:
            self._post("log", f"{name} has not opened port {port} yet; see the startup output above.")

    def start_spiderfoot(self) -> None:
        python = find_spiderfoot_python(ROOT)
        sf_script = SPIDERFOOT_ROOT / "sf.py"
        if not sf_script.is_file():
            messagebox.showerror(
                "SpiderFoot missing",
                "sf.py was not found in the spiderfoot directory.",
                parent=self.root,
            )
            return
        self._start_service(
            "SpiderFoot",
            [python, "sf.py", "-l", "127.0.0.1:5001"],
            SPIDERFOOT_ROOT,
            5001,
        )

    def start_audit_api(self) -> None:
        self._start_service(
            "Audit API",
            [project_python(ENTERPRISE_ROOT), "aggregator_server.py"],
            ENTERPRISE_ROOT,
            8443,
        )

    def run_enterprise_audit(self) -> None:
        target = self.target.get().strip()
        if not target:
            messagebox.showerror("Target required", "Enter an authorized host or URL.", parent=self.root)
            return
        if not self._ensure_target_in_scope(target):
            return
        if _is_ipv4_range(target):
            messagebox.showerror(
                "Single host required",
                "Enterprise audit plugins accept one hostname or URL, not an IP range.",
                parent=self.root,
            )
            return
        if not messagebox.askyesno(
            "Authorized security testing",
            f"Run the enabled enterprise audit checks against {target}?\n\n"
            "Only continue for systems you own or have explicit written permission to test.",
            parent=self.root,
        ):
            return
        existing = self.jobs.get("enterprise-audit")
        if self.enterprise_audit_pending or (existing and existing.poll() is None):
            self._log("Enterprise Audit is already starting or running.")
            return
        if self._port_open("127.0.0.1", 8443):
            self._launch_enterprise_audit(target)
            return

        self.enterprise_audit_pending = True
        self.start_audit_api()
        if not self._port_open("127.0.0.1", 8443) and "Audit API" not in self.services:
            self.enterprise_audit_pending = False
            self._log("Audit API could not be started; run setup-blacktiger.ps1 and check the activity log.")
            return
        self._log("Waiting for the Audit API to become ready before starting the audit…")
        threading.Thread(
            target=self._wait_for_audit_api,
            args=(target,),
            name="blacktiger-audit-api-readiness",
            daemon=True,
        ).start()

    def _wait_for_audit_api(self, target: str) -> None:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            process = self.services.get("Audit API")
            if self._port_open("127.0.0.1", 8443):
                self.root.after(0, lambda: self._launch_enterprise_audit(target))
                return
            if process is not None and process.poll() is not None:
                break
            time.sleep(0.25)
        self.root.after(0, self._audit_api_not_ready)

    def _audit_api_not_ready(self) -> None:
        self.enterprise_audit_pending = False
        self._log("Audit API did not become ready; the enterprise audit was not started.")

    def _launch_enterprise_audit(self, target: str) -> None:
        self.enterprise_audit_pending = False
        self._run_command(
            "Enterprise Audit",
            [project_python(ENTERPRISE_ROOT), "main.py", target],
            ENTERPRISE_ROOT,
            "enterprise-audit",
            ("Enterprise Audit", target),
        )

    def show_threat_model(self) -> None:
        try:
            tm = read_threat_model(ROOT)
            records = tm.get("record_count", "N/A")
            threat_mean = tm.get("threat_mean", 0.0)
            signatures = tm.get("anomaly_signatures", [])
            lines = [
                "Statistical Threat Model (gov_threat_model.json)",
                f"Trained Baseline Records: {records:,}" if isinstance(records, int) else f"Trained Baseline Records: {records}",
                f"Average Threat Score: {threat_mean:.4f}" if isinstance(threat_mean, float) else f"Average Threat Score: {threat_mean}",
                f"High-Risk Anomaly Signatures: {len(signatures)} tracked IPs/ports",
            ]
            if signatures:
                lines.append("\nTop Detected Signatures:")
                for sig in signatures[:5]:
                    lines.append(f"  - {sig.get('ip')}:{sig.get('port')} (Threat: {sig.get('threat')})")
            summary = "\n".join(lines)
            self._log(f"[Threat Model] Baseline of {records} records loaded; {len(signatures)} signatures.")
            messagebox.showinfo("Government Threat Model", summary, parent=self.root)
        except Exception as exc:
            self._log(f"Could not load threat model: {exc}")
            messagebox.showerror("Threat Model Error", str(exc), parent=self.root)

    def triage_siem_logs(self) -> None:
        parser_script = ENTERPRISE_ROOT / "alert_parser.py"
        if not parser_script.is_file():
            messagebox.showerror("Parser missing", "alert_parser.py not found in enterprise_audit.", parent=self.root)
            return
        log_file = ENTERPRISE_ROOT / "central_audit_log.jsonl"
        cmd = [project_python(ENTERPRISE_ROOT), "alert_parser.py"]
        if log_file.is_file():
            cmd.append("central_audit_log.jsonl")
        self._run_command("SIEM Triage", cmd, ENTERPRISE_ROOT, "siem-triage")

    def open_bramhastra(self) -> None:
        try:
            cmd, cwd = resolve_bramhastra_launcher(ROOT)
        except FileNotFoundError as exc:
            messagebox.showerror("Bramhastra unavailable", str(exc), parent=self.root)
            return
        try:
            subprocess.Popen(cmd, cwd=str(cwd), **get_subprocess_flags())
            self._log(f"Opened Bramhastra using {cmd[0]}. Select a file in its window to encrypt or decrypt.")
        except OSError as exc:
            self._log(f"Bramhastra could not start: {exc}")

    def run_network_tool(self) -> None:
        target = self.target.get().strip()
        if not target:
            messagebox.showerror("Target required", "Enter an authorized target.", parent=self.root)
            return
        if not self._ensure_target_in_scope(target):
            return
        if self.tool.get() in {"ping", "portscan"} and _is_ipv4_range(target):
            messagebox.showerror(
                "Single host required",
                "Ping and portscan accept one host. Use the scanner tool for an authorized CIDR range.",
                parent=self.root,
            )
            return
        if not messagebox.askyesno(
            "Authorized security testing",
            f"Run {self.tool.get()} against {target}?\n\n"
            "Only scan hosts and web services you own or have explicit written permission to test.",
            parent=self.root,
        ):
            return
        try:
            policy_min_length = 8
            if self.tool.get() == "policyaudit":
                try:
                    policy_min_length = int(self.policy_min_length.get())
                except ValueError as exc:
                    raise ValueError("Minimum password length must be a whole number.") from exc
                if not 1 <= policy_min_length <= 256:
                    raise ValueError("Minimum password length must be between 1 and 256.")
            command = build_network_command(
                self.tool.get(),
                target,
                self.ports.get().strip(),
                self.wordlist.get().strip(),
                project_python(NETWORK_ROOT),
                output=self.report_output.get().strip() or "audit_report",
                min_length=policy_min_length,
                require_complex=self.policy_require_complex.get(),
            )
        except ValueError as exc:
            messagebox.showerror("Invalid input", str(exc), parent=self.root)
            return
        self._run_command(
            "Network " + self.tool.get(),
            command,
            NETWORK_ROOT,
            evidence=("Network " + self.tool.get(), target),
        )

    def run_john(self) -> None:
        executable = find_john()
        hashes = self.selected_hash_file.get().strip()
        wordlist = self.selected_wordlist.get().strip()
        if not executable:
            messagebox.showerror("John unavailable", "Install the John the Ripper Windows build first.", parent=self.root)
            return
        try:
            command = build_john_command(
                executable, hashes, wordlist, john_pot_file(), self.john_format.get()
            )
        except ValueError as exc:
            messagebox.showerror("Local password audit", str(exc), parent=self.root)
            return
        if not messagebox.askyesno(
            "Local password recovery",
            "Run dictionary-based recovery only against the selected local hash and wordlist files?\n\n"
            "Recovered passwords are stored locally in reports\\john.pot. Treat them as sensitive.",
            parent=self.root,
        ):
            return
        self._run_command("John", command, executable.parent, "john")

    def show_john_results(self) -> None:
        executable = find_john()
        hashes = self.selected_hash_file.get().strip()
        if not executable or not hashes or not Path(hashes).is_file():
            messagebox.showerror("Hash file required", "Choose a valid local hash file first.", parent=self.root)
            return
        process = self.jobs.get("john")
        if process and process.poll() is None:
            messagebox.showinfo("John is running", "Wait for John to finish or stop it before showing results.", parent=self.root)
            return
        self._run_command(
            "John results",
            build_john_show_command(
                executable, hashes, john_pot_file(), self.john_format.get()
            ),
            executable.parent,
        )

    def run_john_benchmark(self) -> None:
        executable = find_john()
        if not executable:
            messagebox.showerror("John unavailable", "Install John the Ripper first.", parent=self.root)
            return
        try:
            cmd = build_john_test_command(executable)
        except ValueError as exc:
            messagebox.showerror("John benchmark error", str(exc), parent=self.root)
            return
        self._run_command("John Benchmark", cmd, executable.parent, "john")

    def stop_job(self, job_key: str) -> None:
        process = self.jobs.get(job_key)
        if process is None or process.poll() is not None:
            self._log(f"No {job_key} job is currently running.")
            return
        process.terminate()
        self._log(f"Stop requested for {job_key}.")

    def run_nmap(self) -> None:
        target = self.target.get().strip()
        executable = find_nmap()
        scan_type = self.nmap_scan_type.get()
        ports = self.ports.get().strip()
        if not target:
            messagebox.showerror("Target required", "Enter an authorized host or IP address.", parent=self.root)
            return
        if not self._ensure_target_in_scope(target):
            return
        if executable is None:
            messagebox.showerror(
                "Nmap not installed",
                "This project includes Nmap source code, not a pre-built binary. "
                "Install Nmap on your system (e.g. via apt install nmap or the official installer) before scanning.",
                parent=self.root,
            )
            return
        if not messagebox.askyesno(
            "Authorized network scan",
            f"Run Nmap ({scan_type} scan) against {target}" + (f" on ports {ports}" if ports and scan_type != 'fast' else "") + "?\n\n"
            "Only scan systems you own or have explicit written permission to test.",
            parent=self.root,
        ):
            return
        try:
            command = build_nmap_command(executable, target, ports=ports, scan_type=scan_type)
        except ValueError as exc:
            messagebox.showerror("Invalid Nmap target", str(exc), parent=self.root)
            return
        self._run_command(
            f"Nmap {scan_type}",
            command,
            executable.parent,
            "nmap",
            ("Nmap " + scan_type, target),
        )

    def run_spiderfoot_cli_scan(self) -> None:
        target = self.target.get().strip()
        if not target:
            messagebox.showerror("Target required", "Enter an authorized target for SpiderFoot CLI scan.", parent=self.root)
            return
        if not self._ensure_target_in_scope(target):
            return
        if not messagebox.askyesno(
            "Authorized OSINT scan",
            f"Run SpiderFoot CLI footprinting scan against {target}?\n\n"
            "Only scan domains, hosts, or addresses you own or have explicit permission to assess.",
            parent=self.root,
        ):
            return
        python = find_spiderfoot_python(ROOT)
        try:
            cmd = build_spiderfoot_scan_command(python, target)
        except ValueError as exc:
            messagebox.showerror("SpiderFoot scan error", str(exc), parent=self.root)
            return
        self._run_command("SpiderFoot CLI", cmd, SPIDERFOOT_ROOT, "spiderfoot-cli", ("SpiderFoot CLI", target))

    def _run_compose(self, args: Sequence[str], label: str) -> None:
        try:
            command = compose_command() + list(args)
        except FileNotFoundError as exc:
            self._log(str(exc))
            return
        self._run_command(label, command, OSINT_ROOT, "osint-compose")

    def start_osint(self) -> None:
        env = read_env_file(OSINT_ROOT / ".env")
        required = ("MYSQL_ROOT_PASSWORD", "MYSQL_DATABASE", "MYSQL_USER", "MYSQL_PASSWORD",
                    "RABBITMQ_DEFAULT_USER", "RABBITMQ_DEFAULT_PASS", "CELERY_BROKER_URL")
        missing = [key for key in required if not env.get(key)]
        if missing:
            messagebox.showerror(
                "OSINT setup required",
                "Set the required database and RabbitMQ values in osint-analyser\\.env "
                "(copy .env.example first).",
                parent=self.root,
            )
            return
        if not shutil.which("docker") and not shutil.which("docker-compose"):
            messagebox.showerror("Docker unavailable", "Install and start Docker Desktop first.", parent=self.root)
            return
        self._run_compose(
            ["up", "--build", "-d", "database", "rabbitmq", "translation-worker", "analysis-worker"],
            "OSINT database, broker, and workers",
        )

    def start_osint_collector(self) -> None:
        env = read_env_file(OSINT_ROOT / ".env")
        if not env.get("TELEGRAM_API_ID") or not env.get("TELEGRAM_API_HASH"):
            messagebox.showerror(
                "Telegram credentials required",
                "Set TELEGRAM_API_ID and TELEGRAM_API_HASH in osint-analyser\\.env first.",
                parent=self.root,
            )
            return
        if not env.get("OPENAI_API_KEY"):
            messagebox.showerror(
                "OpenAI API key required",
                "Set OPENAI_API_KEY in osint-analyser\\.env to enable the translation/analysis pipeline.",
                parent=self.root,
            )
            return
        self._run_compose(["up", "--build", "-d"], "OSINT collector and services")

    def stop_osint(self) -> None:
        self._run_compose(["down"], "Stop OSINT services")

    def status_osint(self) -> None:
        self._run_compose(["ps"], "OSINT services status")

    def open_rabbitmq(self) -> None:
        webbrowser.open_new_tab("http://127.0.0.1:15672")

    def open_reports(self) -> None:
        REPORTS_ROOT.mkdir(parents=True, exist_ok=True)
        self._open_path(REPORTS_ROOT)

    def open_osint_env(self) -> None:
        path = OSINT_ROOT / ".env"
        if not path.is_file():
            template = OSINT_ROOT / ".env.example"
            if not template.is_file():
                messagebox.showerror("OSINT setup missing", "The .env.example template is missing.", parent=self.root)
                return
            shutil.copyfile(template, path)
            self._log("Created osint-analyser\\.env from the template. Set unique passwords before starting services.")
        self._open_path(path)

    def open_lab_docs(self) -> None:
        self._open_path(METASPLOITABLE_ROOT / "README.md")
        missing = lab_requirements()
        if missing:
            messagebox.showinfo(
                "Metasploitable3 lab prerequisites",
                "The intentionally vulnerable VM is not started automatically.\n\nMissing: "
                + ", ".join(missing)
                + "\n\nUse an isolated, host-only lab network after installing the prerequisites.",
                parent=self.root,
            )

    def _open_path(self, path: Path) -> None:
        if not path.exists():
            messagebox.showerror("Path not found", str(path), parent=self.root)
            return
        try:
            open_path_cross_platform(path)
        except (AttributeError, OSError) as exc:
            self._log(f"Could not open {path}: {exc}")

    def show_blackmamba_info(self) -> None:
        info = check_blackmamba(ROOT)
        msg = (
            f"BlackMamba: State-Space MoE AI Engine\n"
            f"Location: {info['source_dir']}\n"
            f"Status: {info['details']}\n\n"
            "Pretrained models on HuggingFace:\n"
            "- Zyphra/BlackMamba-1.5B (340M active / 1.5B total params)\n"
            "- Zyphra/BlackMamba-2.8B (630M active / 2.8B total params)\n\n"
            "Combines Mamba State-Space Models with Switch Transformer Mixture of Experts for O(N) linear inference."
        )
        self._log(f"[BlackMamba] {info['details']}")
        messagebox.showinfo("BlackMamba AI Engine", msg, parent=self.root)

    def run_blackmamba_test(self) -> None:
        self._run_command(
            "BlackMamba self-test",
            [sys.executable, str(ROOT / "blacktiger_app.py"), "blackmamba", "test"],
            ROOT,
            "blackmamba-test",
        )

    def _on_close(self) -> None:
        running = [name for name, process in self.services.items() if process.poll() is None]
        if running and not messagebox.askyesno(
            "Stop local services?",
            "Stop the services started by this window before closing?\n\n" + ", ".join(running),
            parent=self.root,
        ):
            return
        for process in [*self.services.values(), *self.jobs.values()]:
            if process.poll() is None:
                process.terminate()
        self.root.destroy()


def cli_main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="blacktiger",
        description="BlackTiger Unified Security & AI Toolkit (Windows PowerShell & Ubuntu)",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # status
    subparsers.add_parser("status", help="Show status of all tools and services")

    # scope
    scope_parser = subparsers.add_parser("scope", help="Manage authorized testing scope")
    scope_sub = scope_parser.add_subparsers(dest="scope_action")
    scope_sub.add_parser("list", help="List all authorized targets")
    add_scope = scope_sub.add_parser("add", help="Add a target to authorized scope")
    add_scope.add_argument("target", help="Exact hostname, URL, or IPv4 CIDR")
    rem_scope = scope_sub.add_parser("remove", help="Remove a target from authorized scope")
    rem_scope.add_argument("target", help="Exact target to remove")

    # network
    net_parser = subparsers.add_parser("network", help="Run Network Dashboard diagnostic tools")
    net_parser.add_argument("tool", choices=["ping", "scanner", "portscan", "webaudit", "policyaudit", "reporter"], help="Network tool to run")
    net_parser.add_argument("target", help="Authorized IP, CIDR, or host")
    net_parser.add_argument("--ports", default="22,80,443,8080", help="Comma-separated port list")
    net_parser.add_argument("--wordlist", default="", help="Wordlist file for webaudit or policyaudit")
    net_parser.add_argument("--output", default="audit_report", help="Output report filename for reporter")
    net_parser.add_argument("--min-length", type=int, default=8, help="Minimum password length for policyaudit")
    net_parser.add_argument("--require-complex", action="store_true", help="Require complexity for policyaudit")

    # audit
    audit_parser = subparsers.add_parser("audit", help="Enterprise Security Audit tools")
    audit_sub = audit_parser.add_subparsers(dest="audit_action")
    audit_scan = audit_sub.add_parser("scan", help="Run Enterprise Security Audit against target")
    audit_scan.add_argument("target", help="Authorized host or URL to audit")
    audit_sub.add_parser("threat-model", help="Inspect Government Threat Model")
    audit_parse = audit_sub.add_parser("parse", help="Parse and triage SIEM central audit logs")
    audit_parse.add_argument("--file", default="central_audit_log.jsonl", help="Path to audit log file")
    audit_sub.add_parser("api", help="Start Audit API aggregator server")

    # audit-api
    subparsers.add_parser("audit-api", help="Start the Audit API aggregator server")

    # spiderfoot
    sf_parser = subparsers.add_parser("spiderfoot", help="SpiderFoot OSINT reconnaissance")
    sf_sub = sf_parser.add_subparsers(dest="sf_action")
    sf_server = sf_sub.add_parser("server", help="Start SpiderFoot web server on 127.0.0.1:5001")
    sf_server.add_argument("--port", type=int, default=5001, help="Port to listen on")
    sf_scan = sf_sub.add_parser("scan", help="Run SpiderFoot CLI footprinting scan")
    sf_scan.add_argument("target", help="Authorized domain, IP, or hostname")
    sf_scan.add_argument("--modules", default="", help="Comma-separated modules to execute")

    # john
    john_parser = subparsers.add_parser("john", help="John the Ripper password audit")
    john_sub = john_parser.add_subparsers(dest="john_action")
    john_run = john_sub.add_parser("run", help="Audit local hash file using dictionary wordlist")
    john_run.add_argument("hashes", help="Path to local hash file")
    john_run.add_argument("wordlist", help="Path to local wordlist file")
    john_run.add_argument("--format", default="Auto", choices=JOHN_HASH_FORMATS, help="Hash format")
    john_show = john_sub.add_parser("show", help="Show recovered passwords")
    john_show.add_argument("hashes", help="Path to local hash file")
    john_show.add_argument("--format", default="Auto", choices=JOHN_HASH_FORMATS, help="Hash format")
    john_sub.add_parser("test", help="Run John the Ripper benchmark / self-test")
    john_sub.add_parser("benchmark", help="Run John the Ripper benchmark / self-test")

    # nmap
    nmap_parser = subparsers.add_parser("nmap", help="Run Nmap network scan against authorized target")
    nmap_parser.add_argument("target", help="Authorized target host or IPv4 address")
    nmap_parser.add_argument("--ports", default="", help="Comma-separated port list or range")
    nmap_parser.add_argument("--type", dest="scan_type", default="connect", choices=["connect", "syn", "fast", "version", "ping"], help="Nmap scan type")

    # bramhastra
    bram_parser = subparsers.add_parser("bramhastra", help="Bramhastra military-grade encryption tool")
    bram_sub = bram_parser.add_subparsers(dest="bram_action")
    bram_enc = bram_sub.add_parser("encrypt", help="Encrypt a file with AES-256-GCM + Scrypt")
    bram_enc.add_argument("input", help="Input file path")
    bram_enc.add_argument("output", help="Output encrypted file path")
    bram_enc.add_argument("password", help="Password for encryption")
    bram_dec = bram_sub.add_parser("decrypt", help="Decrypt an encrypted file")
    bram_dec.add_argument("input", help="Input encrypted file path")
    bram_dec.add_argument("output", help="Output decrypted file path")
    bram_dec.add_argument("password", help="Password for decryption")
    bram_sub.add_parser("open", help="Launch the Bramhastra GUI")

    # osint
    osint_parser = subparsers.add_parser("osint", help="OSINT analyser Docker services")
    osint_sub = osint_parser.add_subparsers(dest="osint_action")
    osint_sub.add_parser("start", help="Start OSINT database, broker, and workers")
    osint_sub.add_parser("collector", help="Start OSINT collector with Telegram integration")
    osint_sub.add_parser("stop", help="Stop OSINT Docker services")
    osint_sub.add_parser("status", help="Show status of OSINT Docker containers")
    osint_sub.add_parser("logs", help="View OSINT Docker container logs")

    # blackmamba
    mamba_parser = subparsers.add_parser("blackmamba", help="BlackMamba State-Space MoE AI engine")
    mamba_sub = mamba_parser.add_subparsers(dest="mamba_action")
    mamba_sub.add_parser("status", help="Check PyTorch, CUDA, and BlackMamba environment status")
    mamba_sub.add_parser("info", help="Show architecture specifications and pretrained models")
    mamba_sub.add_parser("test", help="Run BlackMamba forward pass verification")

    # lab
    lab_parser = subparsers.add_parser("lab", help="Metasploitable3 isolated lab inspection")
    lab_sub = lab_parser.add_subparsers(dest="lab_action")
    lab_sub.add_parser("check", help="Check disk space and hypervisor requirements")
    lab_sub.add_parser("docs", help="Display lab documentation and setup guidance")

    # extract
    ext_parser = subparsers.add_parser("extract", help="High-precision deterministic data extraction engine")
    ext_parser.add_argument("--text", "-t", help="Raw input text to extract data from")
    ext_parser.add_argument("--file", "-f", help="Path to file containing raw input text")
    ext_parser.add_argument("--schema", "-s", help="Target schema (JSON, dictionary, or field list)")
    ext_parser.add_argument("--schema-file", help="Path to JSON schema file")
    ext_parser.add_argument("--format", "-o", choices=["json", "csv", "markdown"], default="json", help="Output format: json (default), csv, or markdown")
    ext_parser.add_argument("--llm", action="store_true", help="Enable optional LLM extraction backend")

    # gui
    subparsers.add_parser("gui", help="Launch the BlackTiger graphical desktop application")

    args_list = list(argv)
    if args_list and args_list[0] == "audit":
        if len(args_list) > 1 and args_list[1] not in ("scan", "threat-model", "parse", "api", "-h", "--help"):
            args_list.insert(1, "scan")
        elif len(args_list) == 1:
            args_list.append("-h")
    elif args_list and args_list[0] == "spiderfoot":
        if len(args_list) == 1:
            args_list.append("server")
    elif args_list and args_list[0] == "lab":
        if len(args_list) == 1:
            args_list.append("check")

    parsed = parser.parse_args(args_list)

    if not parsed.subcommand:
        parser.print_help()
        return 0

    if parsed.subcommand == "status":
        print("=== BlackTiger Toolkit Status ===")
        for name, (host, port, url) in LOCAL_URLS.items():
            active = BlackTigerApp._port_open(host, port)
            print(f"[{'RUNNING' if active else 'STOPPED'}] {name}: {url}")
        john = find_john()
        print(f"[{'READY' if john else 'NOT INSTALLED'}] John the Ripper: {john or 'install via apt or package'}")
        nmap = find_nmap()
        print(f"[{'READY' if nmap else 'NOT INSTALLED'}] Nmap: {nmap or 'install via apt or official installer'}")
        bram = resolve_bramhastra_launcher()
        print(f"[READY] Bramhastra: {bram[0][0]}")
        mamba = check_blackmamba()
        print(f"[{'READY' if mamba['pytorch_available'] else 'STANDBY'}] BlackMamba AI: {mamba['details']}")
        scope = load_scope()
        print(f"[SCOPE] Authorized targets ({len(scope)}): {', '.join(scope) if scope else 'None configured'}")
        print(f"[REPORTS] Local evidence reports directory: {REPORTS_ROOT}")
        missing = lab_requirements()
        print(f"[{'READY' if not missing else 'PREREQS NEEDED'}] Metasploitable3 lab: {', '.join(missing) if missing else 'Ready'}")
        return 0

    if parsed.subcommand == "scope":
        scope = set(load_scope())
        if parsed.scope_action == "list" or not parsed.scope_action:
            print(f"Authorized Scope ({len(scope)} targets):")
            for t in sorted(scope):
                print(f"  - {t}")
            return 0
        if parsed.scope_action == "add":
            target = normalize_scope_target(parsed.target)
            if target in scope:
                print(f"{target} is already in the authorized scope.")
                return 0
            scope.add(target)
            save_scope(SCOPE_FILE, scope)
            print(f"Added {target} to authorized scope.")
            return 0
        if parsed.scope_action == "remove":
            target = normalize_scope_target(parsed.target)
            if target in scope:
                scope.remove(target)
                save_scope(SCOPE_FILE, scope)
                print(f"Removed {target} from authorized scope.")
            else:
                print(f"{target} was not found in authorized scope.")
            return 0

    if parsed.subcommand == "network":
        target = parsed.target.strip()
        scope = load_scope()
        if not target_is_in_scope(target, scope):
            print(f"Error: Target '{target}' is not in the authorized scope.")
            print("Add it with: blacktiger scope add <target>")
            return 1
        cmd = build_network_command(
            parsed.tool,
            target,
            ports=parsed.ports,
            wordlist=parsed.wordlist,
            python=project_python(NETWORK_ROOT),
            output=parsed.output,
            min_length=parsed.min_length,
            require_complex=parsed.require_complex,
        )
        print(f"Executing: {' '.join(cmd)}")
        started = datetime.now(timezone.utc).isoformat()
        res = subprocess.run(cmd, cwd=str(NETWORK_ROOT), text=True, capture_output=True)
        print(res.stdout)
        if res.stderr:
            print(res.stderr, file=sys.stderr)
        output_lines = (res.stdout + res.stderr).splitlines()
        report_path = write_evidence_report(
            REPORTS_ROOT, f"Network {parsed.tool}", target, scope, started, datetime.now(timezone.utc).isoformat(), res.returncode, output_lines
        )
        print(f"Evidence report saved to: {report_path}")
        return res.returncode

    if parsed.subcommand == "audit":
        if parsed.audit_action == "scan":
            target = parsed.target.strip()
            scope = load_scope()
            if not target_is_in_scope(target, scope):
                print(f"Error: Target '{target}' is not in authorized scope.")
                return 1
            cmd = [project_python(ENTERPRISE_ROOT), "main.py", target]
            print(f"Running Enterprise Audit against {target}...")
            started = datetime.now(timezone.utc).isoformat()
            res = subprocess.run(cmd, cwd=str(ENTERPRISE_ROOT), text=True, capture_output=True)
            print(res.stdout)
            if res.stderr:
                print(res.stderr, file=sys.stderr)
            output_lines = (res.stdout + res.stderr).splitlines()
            report_path = write_evidence_report(
                REPORTS_ROOT, "Enterprise Audit", target, scope, started, datetime.now(timezone.utc).isoformat(), res.returncode, output_lines
            )
            print(f"Evidence report saved to: {report_path}")
            return res.returncode

        if parsed.audit_action == "threat-model":
            try:
                tm = read_threat_model(ROOT)
                records = tm.get("record_count", "N/A")
                threat_mean = tm.get("threat_mean", 0.0)
                signatures = tm.get("anomaly_signatures", [])
                print("=== Government Threat Model Summary ===")
                print(f"Baseline Records: {records:,}" if isinstance(records, int) else f"Baseline Records: {records}")
                print(f"Mean Threat Score: {threat_mean:.4f}" if isinstance(threat_mean, float) else f"Mean Threat Score: {threat_mean}")
                print(f"Anomaly Signatures Tracked: {len(signatures)}")
                if signatures:
                    print("Top High-Risk Signatures:")
                    for sig in signatures[:8]:
                        print(f"  - {sig.get('ip')}:{sig.get('port')} (threat: {sig.get('threat')})")
                return 0
            except Exception as exc:
                print(f"Error reading threat model: {exc}", file=sys.stderr)
                return 1

        if parsed.audit_action == "parse":
            log_file = ENTERPRISE_ROOT / parsed.file
            cmd = [project_python(ENTERPRISE_ROOT), "alert_parser.py"]
            if log_file.is_file():
                cmd.append(str(log_file))
            print(f"Parsing SIEM logs with {cmd[0]}...")
            return subprocess.run(cmd, cwd=str(ENTERPRISE_ROOT)).returncode

        if parsed.audit_action == "api":
            cmd = [project_python(ENTERPRISE_ROOT), "aggregator_server.py"]
            print("Starting Audit API on 127.0.0.1:8443...")
            return subprocess.run(cmd, cwd=str(ENTERPRISE_ROOT)).returncode

        audit_parser.print_help()
        return 0

    if parsed.subcommand == "audit-api":
        cmd = [project_python(ENTERPRISE_ROOT), "aggregator_server.py"]
        print("Starting Audit API on 127.0.0.1:8443...")
        return subprocess.run(cmd, cwd=str(ENTERPRISE_ROOT)).returncode

    if parsed.subcommand == "spiderfoot":
        python_exec = find_spiderfoot_python(ROOT)
        if parsed.sf_action == "server" or not parsed.sf_action:
            port = getattr(parsed, "port", 5001)
            cmd = [python_exec, "sf.py", "-l", f"127.0.0.1:{port}"]
            print(f"Starting SpiderFoot on http://127.0.0.1:{port}...")
            return subprocess.run(cmd, cwd=str(SPIDERFOOT_ROOT)).returncode

        if parsed.sf_action == "scan":
            target = parsed.target.strip()
            scope = load_scope()
            if not target_is_in_scope(target, scope):
                print(f"Error: Target '{target}' is not in authorized scope.")
                return 1
            cmd = build_spiderfoot_scan_command(python_exec, target, modules=parsed.modules)
            print(f"Running SpiderFoot scan: {' '.join(cmd)}")
            started = datetime.now(timezone.utc).isoformat()
            res = subprocess.run(cmd, cwd=str(SPIDERFOOT_ROOT), text=True, capture_output=True)
            print(res.stdout)
            if res.stderr:
                print(res.stderr, file=sys.stderr)
            output_lines = (res.stdout + res.stderr).splitlines()
            report_path = write_evidence_report(
                REPORTS_ROOT, "SpiderFoot CLI", target, scope, started, datetime.now(timezone.utc).isoformat(), res.returncode, output_lines
            )
            print(f"Evidence report saved to: {report_path}")
            return res.returncode

    if parsed.subcommand == "john":
        executable = find_john()
        if not executable:
            print("Error: John the Ripper executable not found. Install John or place it in the PATH.")
            return 1
        if parsed.john_action == "run":
            cmd = build_john_command(executable, parsed.hashes, parsed.wordlist, john_pot_file(), parsed.format)
            print(f"Running: {' '.join(cmd)}")
            return subprocess.run(cmd, cwd=str(executable.parent)).returncode
        if parsed.john_action == "show":
            cmd = build_john_show_command(executable, parsed.hashes, john_pot_file(), parsed.format)
            print(f"Running: {' '.join(cmd)}")
            return subprocess.run(cmd, cwd=str(executable.parent)).returncode
        if parsed.john_action in ("test", "benchmark"):
            cmd = build_john_test_command(executable)
            print(f"Running John benchmark: {' '.join(cmd)}")
            return subprocess.run(cmd, cwd=str(executable.parent)).returncode
        john_parser.print_help()
        return 0

    if parsed.subcommand == "nmap":
        executable = find_nmap()
        if not executable:
            print("Error: Nmap is not installed. Install Nmap on your system first.")
            return 1
        target = parsed.target.strip()
        scope = load_scope()
        if not target_is_in_scope(target, scope):
            print(f"Error: Target '{target}' is not in authorized scope.")
            return 1
        cmd = build_nmap_command(executable, target, ports=parsed.ports, scan_type=parsed.scan_type)
        print(f"Running: {' '.join(cmd)}")
        started = datetime.now(timezone.utc).isoformat()
        res = subprocess.run(cmd, cwd=str(executable.parent), text=True, capture_output=True)
        print(res.stdout)
        if res.stderr:
            print(res.stderr, file=sys.stderr)
        output_lines = (res.stdout + res.stderr).splitlines()
        report_path = write_evidence_report(
            REPORTS_ROOT, f"Nmap {parsed.scan_type}", target, scope, started, datetime.now(timezone.utc).isoformat(), res.returncode, output_lines
        )
        print(f"Evidence report saved to: {report_path}")
        return res.returncode

    if parsed.subcommand == "bramhastra":
        if parsed.bram_action == "encrypt":
            cmd = [project_python(BRAMHASTRA_ROOT), str(BRAMHASTRA_CLI), "encrypt", parsed.input, parsed.output, parsed.password]
            return subprocess.run(cmd, cwd=str(BRAMHASTRA_ROOT)).returncode
        if parsed.bram_action == "decrypt":
            cmd = [project_python(BRAMHASTRA_ROOT), str(BRAMHASTRA_CLI), "decrypt", parsed.input, parsed.output, parsed.password]
            return subprocess.run(cmd, cwd=str(BRAMHASTRA_ROOT)).returncode
        if parsed.bram_action == "open":
            launcher_cmd, cwd = resolve_bramhastra_launcher(ROOT)
            print(f"Launching Bramhastra: {' '.join(launcher_cmd)}")
            return subprocess.run(launcher_cmd, cwd=str(cwd)).returncode
        bram_parser.print_help()
        return 0

    if parsed.subcommand == "osint":
        try:
            compose = compose_command()
        except FileNotFoundError as exc:
            print(f"Error: {exc}")
            return 1
        if parsed.osint_action == "start":
            cmd = compose + ["up", "--build", "-d", "database", "rabbitmq", "translation-worker", "analysis-worker"]
            return subprocess.run(cmd, cwd=str(OSINT_ROOT)).returncode
        if parsed.osint_action == "collector":
            cmd = compose + ["up", "--build", "-d"]
            return subprocess.run(cmd, cwd=str(OSINT_ROOT)).returncode
        if parsed.osint_action == "stop":
            cmd = compose + ["down"]
            return subprocess.run(cmd, cwd=str(OSINT_ROOT)).returncode
        if parsed.osint_action == "status":
            cmd = compose + ["ps"]
            return subprocess.run(cmd, cwd=str(OSINT_ROOT)).returncode
        if parsed.osint_action == "logs":
            cmd = compose + ["logs", "--tail=100"]
            return subprocess.run(cmd, cwd=str(OSINT_ROOT)).returncode
        osint_parser.print_help()
        return 0

    if parsed.subcommand == "blackmamba":
        info = check_blackmamba(ROOT)
        if parsed.mamba_action == "status" or not parsed.mamba_action:
            print("=== BlackMamba AI Engine Status ===")
            print(f"Source Directory: {info['source_dir']}")
            print(f"PyTorch Available: {info['pytorch_available']}")
            if info['pytorch_available']:
                print(f"PyTorch Version: {info.get('torch_version', 'N/A')}")
                print(f"CUDA Available: {info['cuda_available']}")
                if info['cuda_available']:
                    print(f"CUDA Device: {info.get('cuda_device_name', 'N/A')}")
            print(f"Details: {info['details']}")
            return 0
        if parsed.mamba_action == "info":
            print("=== BlackMamba Architecture Overview ===")
            print("Architecture: State-Space Models (SSM) + Mixture of Experts (MoE)")
            print("Base SSM Block: Mamba SSM (linear sequence complexity O(N))")
            print("Base MoE Block: Switch Transformer MLP routing")
            print("Pretrained Models on HuggingFace:")
            print("  - Zyphra/BlackMamba-1.5B (340M active / 1.5B total params)")
            print("  - Zyphra/BlackMamba-2.8B (630M active / 2.8B total params)")
            print(f"Location: {info['source_dir']}")
            print(f"Status: {info['details']}")
            return 0
        if parsed.mamba_action == "test":
            print("Running BlackMamba forward pass verification...")
            success, msg = test_blackmamba(ROOT)
            print(f"[{'PASS' if success else 'FAIL'}] {msg}")
            return 0 if success else 1

    if parsed.subcommand == "lab":
        missing = lab_requirements()
        if parsed.lab_action == "check" or not parsed.lab_action:
            print("=== Metasploitable3 Lab Prerequisites ===")
            if not missing:
                print("[READY] All lab virtualization prerequisites met.")
            else:
                print(f"[PREREQUISITES NEEDED] Missing: {', '.join(missing)}")
                print("\nTo build the lab VM:")
                print("  1. Install Vagrant and Oracle VirtualBox")
                print("  2. Ensure >= 65 GB free disk space")
                print("  3. Run build.sh or build.ps1 inside an isolated, host-only network.")
            return 0
        if parsed.lab_action == "docs":
            readme = METASPLOITABLE_ROOT / "README.md"
            print(f"Metasploitable3 Documentation: {readme}")
            if readme.is_file():
                lines = readme.read_text(encoding="utf-8", errors="replace").splitlines()[:30]
                print("\n".join(lines))
            return 0

    if parsed.subcommand == "extract":
        from data_extractor import DataExtractionEngine
        source_text = None
        if parsed.text:
            source_text = parsed.text
        elif parsed.file:
            try:
                with open(parsed.file, "r", encoding="utf-8") as fh:
                    source_text = fh.read()
            except OSError as err:
                print(f"Error reading file '{parsed.file}': {err}", file=sys.stderr)
                return 1
        elif not sys.stdin.isatty():
            source_text = sys.stdin.read()

        schema_spec = None
        if parsed.schema:
            schema_spec = parsed.schema
        elif parsed.schema_file:
            try:
                with open(parsed.schema_file, "r", encoding="utf-8") as fh:
                    schema_spec = json.load(fh)
            except Exception as err:
                print(f"Error reading schema file '{parsed.schema_file}': {err}", file=sys.stderr)
                return 1

        engine = DataExtractionEngine(use_llm=parsed.llm)
        output = engine.extract(source_text, schema_spec, output_format=parsed.format)
        sys.stdout.write(output + "\n")
        sys.stdout.flush()
        return 0

    if parsed.subcommand == "gui":
        BlackTigerApp()
        tk.mainloop()
        return 0

    parser.print_help()
    return 0


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] != "--gui":
        sys.exit(cli_main(sys.argv[1:]))

    try:
        BlackTigerApp()
        tk.mainloop()
    except Exception as exc:
        msg = str(exc).lower()
        if "no display name" in msg or "display" in msg or isinstance(exc, (tk.TclError, AttributeError)):
            print("\n[!] No graphical display detected. Falling back to BlackTiger CLI mode.\n")
            sys.exit(cli_main(["status"]))
        raise


if __name__ == "__main__":
    main()
