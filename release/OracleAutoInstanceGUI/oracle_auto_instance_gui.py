import contextlib
import io
import os
import queue
import random
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


def normalize_settings(values: dict[str, str]) -> dict[str, str]:
    normalized = dict(values)
    image_id = normalized.get("OCI_IMAGE_ID", "").strip()

    if image_id:
        normalized["OCI_IMAGE_OS"] = ""
        normalized["OCI_IMAGE_OS_VERSION"] = ""

    return normalized


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
    code = getattr(exc, "code", None)
    status = getattr(exc, "status", None)
    if code == "TooManyRequests" or status == 429 or "too many requests" in message:
        return "OCI is rate limiting the tenant right now. Waiting before the next try."
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
        self.auto_mode = False
        self.success_count = 0
        self.failure_count = 0
        self.retry_deadline: float | None = None
        self.auto_deadline: float | None = None
        self.status_var = tk.StringVar(value="Ready - no retry scheduled")
        self.stats_var = tk.StringVar(value="Success: 0 | Failed: 0")
        self.retry_var = tk.StringVar(value="Next try: now")
        self.status_color = "#0b5"
        self.retry_color = "#333"
        self.stats_color = "#333"
        self.layout_mode = "wide"
        self.palette = {
            "bg": "#eef2f7",
            "panel": "#ffffff",
            "panel_soft": "#f7f9fc",
            "border": "#d7dde6",
            "text": "#15202b",
            "muted": "#5f6b7a",
            "accent": "#1d4ed8",
            "accent_soft": "#dbeafe",
            "success": "#0f7a4a",
            "warning": "#b45309",
            "danger": "#b42318",
        }
        root.title("Oracle Auto Instance")
        root.geometry("980x760")
        root.minsize(900, 700)
        root.configure(bg=self.palette["bg"])
        self.configure(style="App.TFrame")
        self.setup_styles()

        self.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self.create_header()
        self.create_status_bar()
        self.create_form()
        self.create_buttons()
        self.create_log()
        self.load_values()
        self.root.bind("<Configure>", self.on_window_resize)
        self.poll_queue()

    def create_header(self) -> None:
        header = tk.Frame(self, bg=self.palette["bg"])
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)

        title_card = tk.Frame(header, bg=self.palette["accent"], padx=18, pady=16)
        title_card.grid(row=0, column=0, sticky="ew")
        title_card.columnconfigure(0, weight=1)

        tk.Label(
            title_card,
            text="Oracle Auto Instance",
            font=("Segoe UI", 20, "bold"),
            bg=self.palette["accent"],
            fg="white",
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            title_card,
            text="Launch OCI instances, watch retry timing, and keep the run history visible.",
            font=("Segoe UI", 10),
            bg=self.palette["accent"],
            fg="#dbeafe",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

    def create_status_bar(self) -> None:
        bar = tk.Frame(self, bd=1, relief="solid", padx=12, pady=10, bg=self.palette["panel"])
        bar.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        bar.columnconfigure(0, weight=1)

        self.live_status_label = tk.Label(bar, text="Live Status", font=("Segoe UI", 9, "bold"), bg=self.palette["panel"], fg=self.palette["muted"])
        self.live_status_label.grid(row=0, column=0, sticky="w")
        self.status_value_label = tk.Label(bar, textvariable=self.status_var, font=("Segoe UI", 12, "bold"), bg=self.palette["panel"], fg=self.status_color)
        self.status_value_label.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.retry_value_label = tk.Label(bar, textvariable=self.retry_var, font=("Segoe UI", 10), bg=self.palette["panel"], fg=self.retry_color)
        self.retry_value_label.grid(row=2, column=0, sticky="w", pady=(2, 0))
        self.stats_value_label = tk.Label(bar, textvariable=self.stats_var, font=("Segoe UI", 10), bg=self.palette["panel"], fg=self.stats_color)
        self.stats_value_label.grid(row=0, column=1, rowspan=3, sticky="e", padx=(12, 0))

    def set_banner_colors(self, status: str, retry: str | None = None, stats: str | None = None) -> None:
        self.status_value_label.configure(fg=status)
        if retry is not None:
            self.retry_value_label.configure(fg=retry)
        if stats is not None:
            self.stats_value_label.configure(fg=stats)

    def create_form(self) -> None:
        self.outer = ttk.Frame(self, style="App.TFrame")
        self.outer.grid(row=2, column=0, sticky="nsew")
        self.outer.columnconfigure(0, weight=1)
        self.outer.columnconfigure(1, weight=1)

        self.left = ttk.LabelFrame(self.outer, text="Oracle target", padding=12, style="Card.TLabelframe")
        self.right = ttk.LabelFrame(self.outer, text="Instance settings", padding=12, style="Card.TLabelframe")
        self.ssh = ttk.LabelFrame(self, text="SSH and cleanup", padding=12, style="Card.TLabelframe")
        self.left.columnconfigure(1, weight=1)
        self.right.columnconfigure(1, weight=1)
        self.ssh.columnconfigure(1, weight=1)

        fields_left = [
            ("Compartment OCID", "OCI_COMPARTMENT_ID"),
            ("Subnet OCID", "OCI_SUBNET_ID"),
            ("Availability domain", "OCI_AVAILABILITY_DOMAIN"),
            ("OCI config file", "OCI_CONFIG_FILE"),
            ("OCI profile", "OCI_PROFILE"),
        ]
        for row, (label, key) in enumerate(fields_left):
            self.add_entry(self.left, row, label, key, browse=(key == "OCI_CONFIG_FILE"))

        self.add_combo(self.right, 0, "Preset", "PRESET", tuple(SHAPE_PRESETS.keys()))
        self.vars["PRESET"].trace_add("write", self.apply_preset)
        self.add_combo(self.right, 1, "Shape", "OCI_SHAPE", (
            "VM.Standard.A1.Flex",
            "VM.Standard.E2.1.Micro",
            "Custom",
        ))
        self.vars["OCI_SHAPE"].trace_add("write", self.on_shape_change)
        self.add_entry(self.right, 2, "Image ID", "OCI_IMAGE_ID")
        self.add_combo(self.right, 3, "Image OS", "OCI_IMAGE_OS", (
            "Canonical Ubuntu",
            "Oracle Linux",
            "Custom",
        ))
        self.add_combo(self.right, 4, "Image OS version", "OCI_IMAGE_OS_VERSION", (
            "24.04",
            "24.04 Minimal",
            "8",
            "9",
            "Custom",
        ))
        self.add_entry(self.right, 5, "Name prefix", "INSTANCE_NAME_PREFIX")

        self.add_entry(self.ssh, 0, "SSH public key", "SSH_PUBLIC_KEY")
        self.add_entry(self.ssh, 1, "Wait seconds", "INSTANCE_WAIT_SECONDS")
        self.add_combo(self.ssh, 2, "Assign public IP", "ASSIGN_PUBLIC_IP", ("true", "false"))
        self.add_combo(self.ssh, 3, "Delete failed instance", "DELETE_FAILED_INSTANCE", ("true", "false"))
        self.add_combo(self.ssh, 4, "Capacity retry exits OK", "CAPACITY_RETRY_SUCCESS_EXIT", ("true", "false"))
        self.apply_layout("wide")

    def add_entry(self, parent: ttk.Frame, row: int, label: str, key: str, browse: bool = False) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        var = self.vars.setdefault(key, tk.StringVar())
        entry = ttk.Entry(parent, textvariable=var, style="App.TEntry")
        entry.grid(row=row, column=1, sticky="ew", pady=4, padx=(8, 0))
        if browse:
            ttk.Button(parent, text="Browse", command=lambda: self.browse_file(key), style="Ghost.TButton").grid(row=row, column=2, padx=(6, 0))

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

    def on_shape_change(self, *_args) -> None:
        return None

    def create_buttons(self) -> None:
        buttons = ttk.Frame(self, style="App.TFrame")
        buttons.grid(row=4, column=0, sticky="ew", pady=(12, 8))
        self.buttons = buttons

        self.save_btn = ttk.Button(buttons, text="Save Settings", command=self.save_values, style="Accent.TButton")
        self.check_btn = ttk.Button(buttons, text="Check OCI Login", command=self.check_login, style="Ghost.TButton")
        self.launch_btn = ttk.Button(buttons, text="Launch Once", command=self.launch_once, style="Ghost.TButton")
        self.start_btn = ttk.Button(buttons, text="Start Auto", command=self.start_auto, style="Ghost.TButton")
        self.stop_btn = ttk.Button(buttons, text="Stop Auto", command=self.stop_auto, style="Ghost.TButton")
        self.apply_button_layout("wide")

    def create_log(self) -> None:
        frame = ttk.LabelFrame(self, text="Activity Log", padding=10, style="Card.TLabelframe")
        frame.grid(row=5, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.rowconfigure(5, weight=1)

        self.log = tk.Text(
            frame,
            height=12,
            wrap="word",
            bg=self.palette["panel_soft"],
            fg=self.palette["text"],
            insertbackground=self.palette["text"],
            relief="flat",
            padx=10,
            pady=8,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=self.palette["border"],
            highlightcolor=self.palette["accent"],
        )
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

    def setup_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("App.TFrame", background=self.palette["bg"])
        style.configure("Card.TLabelframe", background=self.palette["panel"], foreground=self.palette["text"])
        style.configure("Card.TLabelframe.Label", background=self.palette["panel"], foreground=self.palette["muted"], font=("Segoe UI", 9, "bold"))
        style.configure("App.TEntry", padding=6)
        style.configure("Accent.TButton", padding=(12, 8), background=self.palette["accent"], foreground="white", borderwidth=0)
        style.map("Accent.TButton", background=[("active", "#2563eb"), ("pressed", "#1d4ed8")])
        style.configure("Ghost.TButton", padding=(12, 8), background=self.palette["panel_soft"], foreground=self.palette["text"], borderwidth=0)
        style.map("Ghost.TButton", background=[("active", "#e5eefc"), ("pressed", "#dbeafe")])
        style.configure("TLabel", background=self.palette["bg"], foreground=self.palette["text"])
        style.configure("TLabelframe", background=self.palette["panel"], foreground=self.palette["text"])
        style.configure("TLabelframe.Label", background=self.palette["panel"], foreground=self.palette["muted"])
        style.configure("TCombobox", padding=5)

    def apply_layout(self, mode: str) -> None:
        if mode == self.layout_mode:
            return
        self.layout_mode = mode

        for widget in (self.left, self.right, self.ssh):
            widget.grid_forget()

        if mode == "compact":
            self.left.grid(row=0, column=0, sticky="ew", pady=(0, 8))
            self.right.grid(row=1, column=0, sticky="ew", pady=(0, 8))
            self.ssh.grid(row=2, column=0, sticky="ew", pady=(0, 0))
            self.outer.columnconfigure(0, weight=1)
            self.outer.columnconfigure(1, weight=0)
        else:
            self.left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
            self.right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
            self.ssh.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
            self.outer.columnconfigure(0, weight=1)
            self.outer.columnconfigure(1, weight=1)

        self.apply_button_layout(mode)

    def apply_button_layout(self, mode: str) -> None:
        for child in self.buttons.winfo_children():
            child.grid_forget()

        if mode == "compact":
            self.save_btn.grid(row=0, column=0, sticky="ew", pady=(0, 8))
            self.check_btn.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=(0, 8))
            self.launch_btn.grid(row=1, column=0, sticky="ew", pady=(0, 8))
            self.start_btn.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(0, 8))
            self.stop_btn.grid(row=2, column=0, columnspan=2, sticky="ew")
            self.buttons.columnconfigure(0, weight=1)
            self.buttons.columnconfigure(1, weight=1)
            self.buttons.columnconfigure(2, weight=0)
            self.buttons.columnconfigure(3, weight=0)
            self.buttons.columnconfigure(4, weight=0)
        else:
            self.save_btn.grid(row=0, column=0, sticky="w", padx=(0, 8))
            self.check_btn.grid(row=0, column=1, sticky="w", padx=8)
            self.launch_btn.grid(row=0, column=2, sticky="w", padx=8)
            self.stop_btn.grid(row=0, column=4, sticky="e", padx=8)
            self.start_btn.grid(row=0, column=5, sticky="e", padx=8)
            self.buttons.columnconfigure(0, weight=0)
            self.buttons.columnconfigure(1, weight=0)
            self.buttons.columnconfigure(2, weight=0)
            self.buttons.columnconfigure(3, weight=1)
            self.buttons.columnconfigure(4, weight=0)
            self.buttons.columnconfigure(5, weight=0)

    def on_window_resize(self, event: tk.Event) -> None:
        if event.widget is not self.root:
            return
        mode = "compact" if event.width < 1060 else "wide"
        self.apply_layout(mode)

    def browse_file(self, key: str) -> None:
        path = filedialog.askopenfilename(initialdir=str(Path.home()))
        if path:
            self.vars[key].set(path)

    def load_values(self) -> None:
        values = parse_env(ENV_PATH)
        for key, value in values.items():
            self.vars.setdefault(key, tk.StringVar()).set(value)

    def save_values(self) -> None:
        values = normalize_settings({key: var.get().strip() for key, var in self.vars.items()})
        for key, value in values.items():
            self.vars[key].set(value)
        write_env(ENV_PATH, values)
        self.queue.put(f"Saved settings to {ENV_PATH}\n")
        self.status_var.set("Settings saved")

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
                self.queue.put("__SUCCESS__")
            except Exception as exc:
                if is_capacity_error(exc):
                    self.queue.put("__RETRYABLE__")
                    self.queue.put(describe_capacity_error(exc) + "\n")
                else:
                    self.queue.put("__FAILED__")
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
        if self.auto_mode:
            return
        self.auto_mode = True
        self.save_values()
        self.status_var.set("Auto mode active")
        self.schedule_auto_countdown(random.randint(0, 10 * 60))

    def stop_auto(self) -> None:
        self.auto_mode = False
        self.auto_deadline = None
        self.retry_deadline = None
        self.retry_var.set("Next try: now")
        self.status_var.set("Auto mode stopped")
        self.queue.put("Auto mode stopped.\n")

    def update_stats(self) -> None:
        self.stats_var.set(f"Success: {self.success_count} | Failed: {self.failure_count}")

    def schedule_auto_countdown(self, seconds: int) -> None:
        self.auto_deadline = time.monotonic() + max(0, seconds)
        self.retry_deadline = self.auto_deadline
        self.retry_var.set(f"Next try in: {seconds}s")
        self.status_var.set("Auto mode waiting to launch")
        self.set_banner_colors("#a15c00", "#a15c00", "#333")
        self.root.after(1000, self.tick_auto_countdown)

    def set_retry_countdown(self, seconds: int = 120) -> None:
        self.retry_deadline = time.monotonic() + seconds
        self.retry_var.set(f"Next try in: {seconds}s")
        self.set_banner_colors("#a15c00", "#a15c00", "#333")
        self.root.after(1000, self.tick_retry_countdown)

    def tick_retry_countdown(self) -> None:
        if self.retry_deadline is None:
            self.retry_var.set("Next try: now")
            self.set_banner_colors("#0b5", "#333", "#333")
            return
        remaining = int(self.retry_deadline - time.monotonic())
        if remaining <= 0:
            self.retry_deadline = None
            self.retry_var.set("Next try: now")
            self.status_var.set("Retrying now")
            self.set_banner_colors("#0b5", "#333", "#333")
            self.launch_once()
            return
        self.retry_var.set(f"Next try in: {remaining}s")
        self.root.after(1000, self.tick_retry_countdown)

    def tick_auto_countdown(self) -> None:
        if not self.auto_mode or self.auto_deadline is None:
            self.retry_var.set("Next try: now")
            self.set_banner_colors("#0b5", "#333", "#333")
            return
        remaining = int(self.auto_deadline - time.monotonic())
        if remaining <= 0:
            self.auto_deadline = None
            self.retry_deadline = None
            self.retry_var.set("Next try: now")
            self.status_var.set("Auto mode launching now")
            self.set_banner_colors("#0b5", "#333", "#333")
            self.launch_once()
            return
        self.retry_var.set(f"Next try in: {remaining}s")
        self.root.after(1000, self.tick_auto_countdown)

    def poll_queue(self) -> None:
        while True:
            try:
                text = self.queue.get_nowait()
            except queue.Empty:
                break
            if text == "__IDLE__":
                self.set_busy(False)
                continue
            if text == "__SUCCESS__":
                self.success_count += 1
                self.update_stats()
                self.status_var.set("Launch succeeded")
                self.set_banner_colors("#0b5", "#333", "#0b5")
                if self.auto_mode:
                    self.schedule_auto_countdown(random.randint(0, 10 * 60))
                continue
            if text == "__FAILED__":
                self.failure_count += 1
                self.update_stats()
                self.status_var.set("Launch failed")
                self.set_banner_colors("#b00", "#333", "#b00")
                if self.auto_mode:
                    self.schedule_auto_countdown(random.randint(0, 10 * 60))
                continue
            if text == "__RETRYABLE__":
                self.failure_count += 1
                self.update_stats()
                self.status_var.set("Retryable OCI error - waiting to retry")
                self.set_banner_colors("#a15c00", "#a15c00", "#333")
                if self.auto_mode:
                    self.schedule_auto_countdown(120)
                else:
                    self.set_retry_countdown()
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
