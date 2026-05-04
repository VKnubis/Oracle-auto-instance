import contextlib
import io
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from loop import is_capacity_error, launch_instance, load_config, load_dotenv  # noqa: E402


ENV_PATH = APP_DIR / "settings.env"
TASK_NAME = "OracleAutoInstanceGUI"
DEFAULTS = {
    "OCI_COMPARTMENT_ID": "",
    "OCI_SUBNET_ID": "",
    "OCI_IMAGE_ID": "",
    "OCI_IMAGE_OS": "Canonical Ubuntu",
    "OCI_IMAGE_OS_VERSION": "24.04",
    "OCI_AVAILABILITY_DOMAIN": "",
    "OCI_SHAPE": "VM.Standard.A1.Flex",
    "OCI_OCPUS": "1",
    "OCI_MEMORY_GB": "6",
    "OCI_CONFIG_FILE": str(Path.home() / ".oci" / "config"),
    "OCI_PROFILE": "DEFAULT",
    "INSTANCE_NAME_PREFIX": "auto-instance",
    "ASSIGN_PUBLIC_IP": "true",
    "SSH_PUBLIC_KEY": "",
    "DELETE_FAILED_INSTANCE": "true",
    "INSTANCE_WAIT_SECONDS": "900",
    "CAPACITY_RETRY_SUCCESS_EXIT": "true",
}

SHAPE_PRESETS = {
    "Custom": None,
    "Ubuntu A1.Flex": {
        "OCI_IMAGE_OS": "Canonical Ubuntu",
        "OCI_IMAGE_OS_VERSION": "24.04",
        "OCI_SHAPE": "VM.Standard.A1.Flex",
        "OCI_OCPUS": "1",
        "OCI_MEMORY_GB": "6",
        "CAPACITY_RETRY_SUCCESS_EXIT": "true",
    },
    "Ubuntu E2 Micro": {
        "OCI_IMAGE_OS": "Canonical Ubuntu",
        "OCI_IMAGE_OS_VERSION": "24.04",
        "OCI_SHAPE": "VM.Standard.E2.1.Micro",
        "OCI_OCPUS": "1",
        "OCI_MEMORY_GB": "1",
        "CAPACITY_RETRY_SUCCESS_EXIT": "false",
    },
    "Oracle Linux A1.Flex": {
        "OCI_IMAGE_OS": "Oracle Linux",
        "OCI_IMAGE_OS_VERSION": "9",
        "OCI_SHAPE": "VM.Standard.A1.Flex",
        "OCI_OCPUS": "1",
        "OCI_MEMORY_GB": "6",
        "CAPACITY_RETRY_SUCCESS_EXIT": "true",
    },
    "Oracle Linux E2 Micro": {
        "OCI_IMAGE_OS": "Oracle Linux",
        "OCI_IMAGE_OS_VERSION": "8",
        "OCI_SHAPE": "VM.Standard.E2.1.Micro",
        "OCI_OCPUS": "1",
        "OCI_MEMORY_GB": "1",
        "CAPACITY_RETRY_SUCCESS_EXIT": "false",
    },
}


def parse_env(path: Path) -> dict[str, str]:
    values = dict(DEFAULTS)
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in values:
            values[key] = value.strip()
    return values


def write_env(path: Path, values: dict[str, str]) -> None:
    lines = [
        "# Oracle Auto Instance GUI settings",
        "# Keep this file private.",
        "",
    ]
    for key in DEFAULTS:
        lines.append(f"{key}={values.get(key, '')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def describe_exception(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    status = getattr(exc, "status", None)
    message = getattr(exc, "message", str(exc))

    parts = []
    if code:
        parts.append(f"{code}")
    if status:
        parts.append(f"HTTP {status}")
    if parts:
        prefix = "OCI error (" + ", ".join(parts) + ")"
    else:
        prefix = "Error"
    return f"{prefix}: {message}"


def describe_capacity_error(exc: Exception) -> str:
    message = getattr(exc, "message", str(exc)).lower()
    if "out of host capacity" in message:
        return "OCI reported out of host capacity. The target shape is full right now, so Auto mode can retry later."
    return "OCI reported capacity exhaustion. The target server pool is full right now, so Auto mode can retry later."


class TextLogger:
    def __init__(self, output: queue.Queue[str]) -> None:
        self.output = output

    def write(self, text: str) -> int:
        if text:
            self.output.put(text)
        return len(text)

    def flush(self) -> None:
        return None


class App(ttk.Frame):
    def __init__(self, root: tk.Tk) -> None:
        super().__init__(root, padding=14)
        self.root = root
        self.queue: queue.Queue[str] = queue.Queue()
        self.vars: dict[str, tk.StringVar] = {}
        self.running = False

        root.title("Oracle Auto Instance")
        root.geometry("920x720")
        root.minsize(820, 620)

        self.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self.create_header()
        self.create_form()
        self.create_buttons()
        self.create_log()
        self.load_values()
        self.poll_queue()

    def create_header(self) -> None:
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="Oracle Auto Instance", font=("Segoe UI", 18, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Pick a preset or choose a shape and image family from the dropdowns.").grid(row=1, column=0, sticky="w")

    def create_form(self) -> None:
        outer = ttk.Frame(self)
        outer.grid(row=1, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.columnconfigure(1, weight=1)

        left = ttk.LabelFrame(outer, text="Oracle target", padding=10)
        right = ttk.LabelFrame(outer, text="Instance settings", padding=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        left.columnconfigure(1, weight=1)
        right.columnconfigure(1, weight=1)

        fields_left = [
            ("Compartment OCID", "OCI_COMPARTMENT_ID"),
            ("Subnet OCID", "OCI_SUBNET_ID"),
            ("Availability domain", "OCI_AVAILABILITY_DOMAIN"),
            ("OCI config file", "OCI_CONFIG_FILE"),
            ("OCI profile", "OCI_PROFILE"),
        ]
        for row, (label, key) in enumerate(fields_left):
            self.add_entry(left, row, label, key, browse=(key == "OCI_CONFIG_FILE"))

        self.add_combo(right, 0, "Preset", "PRESET", tuple(SHAPE_PRESETS.keys()))
        self.vars["PRESET"].trace_add("write", self.apply_preset)
        self.add_combo(right, 1, "Shape", "OCI_SHAPE", (
            "VM.Standard.A1.Flex",
            "VM.Standard.E2.1.Micro",
            "Custom",
        ))
        self.add_combo(right, 2, "OCPUs", "OCI_OCPUS", (
            "1",
            "2",
            "4",
            "Custom",
        ))
        self.add_combo(right, 3, "Memory GB", "OCI_MEMORY_GB", (
            "1",
            "6",
            "12",
            "Custom",
        ))
        self.add_entry(right, 4, "Image ID", "OCI_IMAGE_ID")
        self.add_combo(right, 5, "Image OS", "OCI_IMAGE_OS", (
            "Canonical Ubuntu",
            "Oracle Linux",
            "Custom",
        ))
        self.add_combo(right, 6, "Image OS version", "OCI_IMAGE_OS_VERSION", (
            "24.04",
            "24.04 Minimal",
            "8",
            "9",
            "Custom",
        ))
        self.add_entry(right, 7, "Name prefix", "INSTANCE_NAME_PREFIX")

        ssh = ttk.LabelFrame(self, text="SSH and cleanup", padding=10)
        ssh.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        ssh.columnconfigure(1, weight=1)
        self.add_entry(ssh, 0, "SSH public key", "SSH_PUBLIC_KEY")
        self.add_entry(ssh, 1, "Wait seconds", "INSTANCE_WAIT_SECONDS")
        self.add_combo(ssh, 2, "Assign public IP", "ASSIGN_PUBLIC_IP", ("true", "false"))
        self.add_combo(ssh, 3, "Delete failed instance", "DELETE_FAILED_INSTANCE", ("true", "false"))
        self.add_combo(ssh, 4, "Capacity retry exits OK", "CAPACITY_RETRY_SUCCESS_EXIT", ("true", "false"))

    def add_entry(self, parent: ttk.Frame, row: int, label: str, key: str, browse: bool = False) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        var = self.vars.setdefault(key, tk.StringVar())
        entry = ttk.Entry(parent, textvariable=var)
        entry.grid(row=row, column=1, sticky="ew", pady=4, padx=(8, 0))
        if browse:
            ttk.Button(parent, text="Browse", command=lambda: self.browse_file(key)).grid(row=row, column=2, padx=(6, 0))

    def add_combo(self, parent: ttk.Frame, row: int, label: str, key: str, values: tuple[str, ...]) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        var = self.vars.setdefault(key, tk.StringVar())
        box = ttk.Combobox(parent, textvariable=var, values=values, state="normal", width=18)
        box.grid(row=row, column=1, sticky="w", pady=4, padx=(8, 0))

    def apply_preset(self, *_args) -> None:
        preset_name = self.vars["PRESET"].get()
        preset = SHAPE_PRESETS.get(preset_name)
        if not preset:
            return
        for key, value in preset.items():
            self.vars[key].set(value)

    def create_buttons(self) -> None:
        buttons = ttk.Frame(self)
        buttons.grid(row=3, column=0, sticky="ew", pady=(12, 8))

        ttk.Button(buttons, text="Save Settings", command=self.save_values).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Check OCI Login", command=self.check_login).pack(side="left", padx=8)
        ttk.Button(buttons, text="Launch Once", command=self.launch_once).pack(side="left", padx=8)
        ttk.Button(buttons, text="Use A1.Flex", command=self.use_a1).pack(side="left", padx=8)
        ttk.Button(buttons, text="Use E2 Micro", command=self.use_e2).pack(side="left", padx=8)
        ttk.Button(buttons, text="Start Auto", command=self.start_auto).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Stop Auto", command=self.stop_auto).pack(side="right", padx=8)

    def create_log(self) -> None:
        frame = ttk.LabelFrame(self, text="Log", padding=8)
        frame.grid(row=4, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        self.log = tk.Text(frame, height=12, wrap="word")
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

    def browse_file(self, key: str) -> None:
        path = filedialog.askopenfilename(initialdir=str(Path.home()))
        if path:
            self.vars[key].set(path)

    def load_values(self) -> None:
        values = parse_env(ENV_PATH)
        for key, value in values.items():
            self.vars.setdefault(key, tk.StringVar()).set(value)

    def save_values(self) -> None:
        values = {key: var.get().strip() for key, var in self.vars.items()}
        write_env(ENV_PATH, values)
        self.queue.put(f"Saved settings to {ENV_PATH}\n")

    def set_busy(self, value: bool) -> None:
        self.running = value
        self.root.config(cursor="watch" if value else "")

    def run_worker(self, title: str, target) -> None:
        if self.running:
            messagebox.showinfo("Busy", "Another action is already running.")
            return
        self.save_values()
        self.set_busy(True)
        self.queue.put(f"\n== {title} ==\n")

        def worker() -> None:
            try:
                with contextlib.redirect_stdout(TextLogger(self.queue)), contextlib.redirect_stderr(TextLogger(self.queue)):
                    target()
            except Exception as exc:
                if is_capacity_error(exc):
                    self.queue.put(describe_capacity_error(exc) + "\n")
                else:
                    self.queue.put(describe_exception(exc) + "\n")
            finally:
                self.queue.put("Done.\n")
                self.queue.put("__IDLE__")

        threading.Thread(target=worker, daemon=True).start()

    def with_env(self):
        values = parse_env(ENV_PATH)
        for key, value in values.items():
            os.environ[key] = value

    def check_login(self) -> None:
        def task() -> None:
            self.with_env()
            import oci

            config = oci.config.from_file(os.environ["OCI_CONFIG_FILE"], os.environ.get("OCI_PROFILE", "DEFAULT"))
            oci.config.validate_config(config)
            identity = oci.identity.IdentityClient(config)
            user = identity.get_user(config["user"]).data
            print(f"OCI login works. User: {user.name}")

        self.run_worker("Checking OCI login", task)

    def launch_once(self) -> None:
        def task() -> None:
            self.with_env()
            instance_id = launch_instance(load_config())
            print(f"Launched instance: {instance_id}")

        self.run_worker("Launching instance", task)

    def start_auto(self) -> None:
        self.save_values()
        script = APP_DIR / "start_auto_gui.bat"
        subprocess.Popen(["cmd", "/c", str(script)], cwd=str(APP_DIR))
        self.queue.put("Starting Windows scheduled task.\n")

    def stop_auto(self) -> None:
        self.save_values()
        script = APP_DIR / "stop_auto_gui.bat"
        subprocess.Popen(["cmd", "/c", str(script)], cwd=str(APP_DIR))
        self.queue.put("Stopping Windows scheduled task.\n")

    def use_a1(self) -> None:
        self.vars["OCI_SHAPE"].set("VM.Standard.A1.Flex")
        self.vars["OCI_OCPUS"].set("1")
        self.vars["OCI_MEMORY_GB"].set("6")
        self.vars["INSTANCE_NAME_PREFIX"].set("auto-instance")
        self.vars["CAPACITY_RETRY_SUCCESS_EXIT"].set("true")

    def use_e2(self) -> None:
        self.vars["OCI_SHAPE"].set("VM.Standard.E2.1.Micro")
        self.vars["OCI_OCPUS"].set("1")
        self.vars["OCI_MEMORY_GB"].set("1")
        self.vars["INSTANCE_NAME_PREFIX"].set("e2micro-test")
        self.vars["CAPACITY_RETRY_SUCCESS_EXIT"].set("false")

    def poll_queue(self) -> None:
        while True:
            try:
                text = self.queue.get_nowait()
            except queue.Empty:
                break
            if text == "__IDLE__":
                self.set_busy(False)
                continue
            self.log.insert("end", text)
            self.log.see("end")
        self.root.after(100, self.poll_queue)


def main() -> None:
    if not ENV_PATH.exists():
        write_env(ENV_PATH, DEFAULTS)
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
