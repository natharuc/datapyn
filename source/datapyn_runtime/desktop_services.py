"""Desktop services that run outside session kernels and the protocol reader."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from importlib import metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import uuid


def data_directory() -> Path:
    override = os.environ.get("DATAPYN_RUNTIME_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "DataPynTauri"


def package_site() -> Path:
    root = data_directory() / "packages/venv"
    return root / "Lib/site-packages" if sys.platform == "win32" else root / f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"


def enable_user_packages():
    """Expose installed extensions to this kernel, including frozen Python."""
    path = package_site()
    if path.exists() and str(path) not in sys.path:
        import site
        site.addsitedir(str(path))


def _atomic(path: Path, document: object):
    from .workspace import write_document
    write_document(str(path), document)


class PackageService:
    def __init__(self, emit):
        self.emit = emit
        self.lock = threading.RLock()
        self.root = data_directory() / "packages"
        self.venv = self.root / "venv"
        self.python = self.venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        self.config = self.root / "sources.json"
        self.closed = threading.Event()
        self.process_lock = threading.Lock()
        self.processes = set()

    def _uv(self):
        bundled = Path(getattr(sys, "_MEIPASS", "")) / ("uv.exe" if sys.platform == "win32" else "uv")
        executable = str(bundled) if bundled.is_file() else shutil.which("uv")
        if not executable:
            raise RuntimeError("uv is unavailable. Install uv or use the packaged DataPyn runtime.")
        return executable

    def environment(self):
        return {"path": str(self.venv), "python": str(self.python), "ready": self.python.is_file()}

    def _env(self):
        return {**os.environ, "UV_PYTHON_INSTALL_DIR": str(self.root / "python"), "UV_CACHE_DIR": str(self.root / "cache"), "UV_NO_PROGRESS": "1"}

    def _run(self, args, timeout=100):
        from .process_group import own_process_group
        if self.closed.is_set(): raise RuntimeError("Package service is closing")
        response = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), start_new_session=sys.platform != "win32", env=self._env())
        group = own_process_group(response.pid)
        with self.process_lock:
            self.processes.add(group)
            if self.closed.is_set(): group.close()
        try:
            stdout, stderr = response.communicate(timeout=timeout)
        finally:
            with self.process_lock: self.processes.discard(group)
            group.close()
            if response.poll() is None:
                response.kill(); response.wait(timeout=3)
        if response.returncode:
            # Credentials passed to an index must never enter error messages or events.
            message = re.sub(r"(https?://)[^/\s@]+@", r"\1***@", stderr or stdout)
            raise RuntimeError(message[-32_000:] or f"Package command exited with {response.returncode}")
        return stdout

    def _ensure_env(self):
        if not self.python.is_file():
            self.root.mkdir(parents=True, exist_ok=True)
            self._run([self._uv(), "venv", "--managed-python", "--python", f"{sys.version_info.major}.{sys.version_info.minor}", str(self.venv)])

    def sources(self, params=None):
        with self.lock:
            sources = json.loads(self.config.read_text("utf-8")) if self.config.exists() else []
            if isinstance(sources, dict): sources = sources.get("sources", [])
            if params is not None:
                if not isinstance(params, list):
                    raise ValueError("sources must be an array")
                cleaned = []
                import keyring
                for item in params:
                    url = str(item.get("url", "")).strip()
                    if urllib.parse.urlsplit(url).scheme not in {"https", "http"}:
                        raise ValueError("Package source URL must use http or https")
                    identifier = str(item.get("id") or uuid.uuid4().hex)
                    if item.get("save_password") and item.get("password") is not None:
                        keyring.set_password("DataPynTauri.packages", identifier, str(item["password"]))
                    old = next((entry for entry in sources if entry["id"] == identifier), {})
                    cleaned.append({"id": identifier, "url": url, "username": str(item.get("username", "")),
                        "has_password": bool(item.get("save_password") and item.get("password")) or old.get("has_password", False)})
                self.root.mkdir(parents=True, exist_ok=True)
                # workspace writer validates an object envelope; keep this file in that format.
                _atomic(self.config, {"sources": cleaned})
                sources = cleaned
            if isinstance(sources, dict):
                sources = sources.get("sources", [])
            return sources

    def list(self):
        packages = {}
        for distribution in metadata.distributions():
            name = distribution.metadata.get("Name")
            if name:
                packages[name.lower()] = {"name": name, "version": distribution.version,
                    "summary": distribution.metadata.get("Summary", ""), "latest_version": "", "installed": True, "has_update": False}
        if package_site().exists():
            for distribution in metadata.distributions(path=[str(package_site())]):
                name = distribution.metadata.get("Name")
                if name:
                    packages[name.lower()] = {"name": name, "version": distribution.version,
                        "summary": distribution.metadata.get("Summary", ""), "latest_version": "", "installed": True, "has_update": False}
        return {"packages": sorted(packages.values(), key=lambda item: item["name"].lower()), "environment": self.environment(), "sources": self.sources()}

    def search(self, query):
        name = self._name(query)
        request = urllib.request.Request(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json", headers={"Accept": "application/json", "User-Agent": "DataPynTauri"})
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read(4 * 1024 * 1024))
        info = data["info"]
        installed = next((p for p in self.list()["packages"] if re.sub(r"[-_.]+", "-", p["name"]).lower() == re.sub(r"[-_.]+", "-", name).lower()), None)
        return {"packages": [{"name": info["name"], "version": installed["version"] if installed else "", "latest_version": info["version"],
            "summary": info.get("summary", ""), "installed": bool(installed), "has_update": bool(installed and installed["version"] != info["version"])}]}

    @staticmethod
    def _name(value):
        value = str(value).strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
            raise ValueError("Enter a package name, such as pandas or scikit-learn")
        return value

    def mutate(self, method, params):
        name = self._name(params.get("name", ""))
        version = str(params.get("version", "")).strip()
        if version and not re.fullmatch(r"[A-Za-z0-9_.+!-]+", version):
            raise ValueError("Invalid package version")
        operation = method.rsplit(".", 1)[1]
        result = {"success": False, "package_name": name, "operation": operation, "message": "", "error": ""}
        try:
            with self.lock:
                self._ensure_env()
                args = [self._uv(), "pip", "uninstall" if operation == "uninstall" else "install", "--python", str(self.python)]
                if operation == "update":
                    args.append("--upgrade")
                if operation != "uninstall":
                    import keyring
                    for source in self.sources():
                        url = source["url"]
                        if source.get("username"):
                            secret = keyring.get_password("DataPynTauri.packages", source["id"]) or ""
                            parsed = urllib.parse.urlsplit(url)
                            authority = f"{urllib.parse.quote(source['username'], safe='')}:{urllib.parse.quote(secret, safe='')}@{parsed.netloc}"
                            url = urllib.parse.urlunsplit((parsed.scheme, authority, parsed.path, parsed.query, parsed.fragment))
                        args.extend(["--extra-index-url", url])
                args.append(f"{name}=={version}" if version else name)
                self._run(args)
                result.update(success=True, message=f"{name}: {operation} completed. New imports are available in running sessions.")
        except Exception as exc:
            result["error"] = str(exc)
        self.emit({"event": "packages.changed", "payload": result})
        return result

    def dispatch(self, method, params):
        if method == "packages.list": return self.list()
        if method == "packages.search": return self.search(params.get("query", ""))
        if method == "packages.sources": return {"sources": self.sources(params.get("sources"))}
        return self.mutate(method, params)

    def close(self):
        self.closed.set()
        with self.process_lock:
            for process in list(self.processes): process.close()


class DesktopServices:
    def __init__(self, emit):
        self.emit = emit
        self.packages = PackageService(emit)
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="desktop-service")
        self.closed = threading.Event()
        self.slots = threading.BoundedSemaphore(16)
        self._pending = 0
        self._pending_lock = threading.Lock()

    @property
    def busy(self):
        with self._pending_lock: return self._pending > 0

    def submit(self, request_id, method, params):
        if not self.slots.acquire(blocking=False): raise ValueError("Desktop service queue is full")
        with self._pending_lock: self._pending += 1
        try:
            future = self.executor.submit(self.packages.dispatch, method, params)
        except BaseException:
            with self._pending_lock: self._pending -= 1
            self.slots.release()
            raise
        def done(future):
            try:
                result = {"result": future.result()}
            except Exception as exc:
                result = {"error": {"code": "service_failed", "message": f"{type(exc).__name__}: {exc}"}}
            finally:
                self.slots.release()
                with self._pending_lock: self._pending -= 1
            if not self.closed.is_set(): self.emit({"id": request_id, **result})
        future.add_done_callback(done)

    def close(self):
        self.closed.set()
        self.packages.close()
        self.executor.shutdown(wait=False, cancel_futures=True)
