"""Start Ho-chan once when the Codex desktop app opens (Windows, no extra packages)."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import subprocess
import time

from codex_bridge import atomic_json

ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'state'
SETTINGS = STATE / 'codex-autostart.json'
HEARTBEAT = STATE / 'codex-autostart-heartbeat.json'
INTERVAL = 3
kernel = ctypes.WinDLL('kernel32', use_last_error=True)


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
                ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG),
                ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR * 260)]


kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel.OpenProcess.restype = wintypes.HANDLE
kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel.CreateMutexW.restype = wintypes.HANDLE
kernel.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel.OpenMutexW.restype = wintypes.HANDLE
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
kernel.GetCurrentProcess.restype = wintypes.HANDLE
kernel.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]


def process_in_job(pid=None, job=None):
    handle = kernel.OpenProcess(0x1000, False, pid) if pid else kernel.GetCurrentProcess()
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        result = wintypes.BOOL()
        if not kernel.IsProcessInJob(handle, job, ctypes.byref(result)):
            raise ctypes.WinError(ctypes.get_last_error())
        return bool(result.value)
    finally:
        if pid:
            kernel.CloseHandle(handle)


def is_codex_desktop(image_path: str) -> bool:
    """Distinguish the packaged GUI from ChatGPT and the bundled Codex CLI."""
    path = PureWindowsPath(image_path)
    parts = [part.lower() for part in path.parts]
    name = path.name.lower()
    if name not in {'chatgpt.exe', 'codex.exe'}:
        return False
    if any(part.startswith('openai.codex_') for part in parts):
        return True
    # Standalone GUI distributions use Codex.exe; bin/<version>/codex.exe is CLI.
    return name == 'codex.exe' and len(parts) >= 2 and parts[-2] == 'codex'


def desktop_roots(parents: dict[int, int]) -> set[int]:
    # Renderer/GPU children come and go while the same application stays open.
    return {pid for pid, parent in parents.items() if parent not in parents}


def desktop_processes() -> set[int]:
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    parents = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            if entry.szExeFile.lower() in {'chatgpt.exe', 'codex.exe'}:
                handle = kernel.OpenProcess(0x1000, False, entry.th32ProcessID)
                if handle:
                    try:
                        buffer = ctypes.create_unicode_buffer(32768)
                        size = wintypes.DWORD(len(buffer))
                        if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)) and is_codex_desktop(buffer.value):
                            parents[entry.th32ProcessID] = entry.th32ParentProcessID
                    finally:
                        kernel.CloseHandle(handle)
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return desktop_roots(parents)


def mutex_name(status_path: Path) -> str:
    return 'Local\\HoChanDesktopPet-' + hashlib.sha256(str(status_path.resolve()).encode()).hexdigest()[:12]


def pet_running() -> bool:
    handle = kernel.OpenMutexW(0x100000, False, mutex_name(STATE / 'codex-status.json'))
    if not handle:
        return False
    kernel.CloseHandle(handle)
    return True


def launch_pet():
    pythonw = ROOT / '.venv/Scripts/pythonw.exe'
    if not pythonw.is_file():
        raise FileNotFoundError('Run setup.ps1 before enabling Codex autostart.')
    subprocess.Popen([str(pythonw), str(ROOT / 'hochan_pet.py')], cwd=ROOT,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NO_WINDOW)


class LaunchPolicy:
    """Remember each app opening, allowing a user to close the pet for this run."""
    def __init__(self):
        self.handled = set()
        self.retry_at = 0

    def update(self, processes, running, launch, now):
        self.handled.intersection_update(processes)
        if not processes - self.handled or now < self.retry_at:
            return None
        if running():
            self.handled.update(processes)
            return 'pet-already-running'
        try:
            launch()
        except Exception:
            self.retry_at = now + 30
            raise
        self.handled.update(processes)
        return 'pet-launched'


def enabled() -> bool:
    try:
        return json.loads(SETTINGS.read_text(encoding='utf-8-sig')).get('enabled') is True
    except (OSError, ValueError, AttributeError):
        return False


def log(message):
    STATE.mkdir(parents=True, exist_ok=True)
    path = STATE / 'codex-autostart.log'
    if path.exists() and path.stat().st_size > 256_000:
        path.replace(path.with_suffix('.log.1'))
    with path.open('a', encoding='utf-8') as stream:
        stream.write(time.strftime('%Y-%m-%d %H:%M:%S ') + message + '\n')


def main():
    if not enabled():
        return
    key = hashlib.sha256(str(ROOT).lower().encode()).hexdigest()[:12]
    mutex = kernel.CreateMutexW(None, False, 'Local\\HoChanCodexAutostart-' + key)
    duplicate = ctypes.get_last_error() == 183
    if not mutex:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if duplicate:
            return
        policy = LaunchPolicy()
        last_action, last_heartbeat = 'watching', 0
        in_job = process_in_job()
        # The venv redirector puts its Python child in a private job. What must
        # be independent is the outer launcher, rather than every private job.
        launcher_pid = os.getppid()
        launcher_in_job = process_in_job(launcher_pid)
        log('Watcher started; launcher_in_job=' + str(launcher_in_job))
        while enabled():
            processes = set()
            try:
                processes = desktop_processes()
                action = policy.update(processes, pet_running, launch_pet, time.monotonic())
                if action:
                    last_action = action
                    log(action + ': Codex PID(s) ' + ','.join(map(str, sorted(processes))))
            except Exception as error:
                log(type(error).__name__ + ': ' + str(error))
            now = time.time()
            if now - last_heartbeat >= 10:
                atomic_json(HEARTBEAT, dict(pid=os.getpid(), updated_at=now,
                            codex_pids=sorted(processes), last_action=last_action, in_job=in_job,
                            launcher_pid=launcher_pid, launcher_in_job=launcher_in_job))
                last_heartbeat = now
            time.sleep(INTERVAL)
        log('Watcher disabled; exiting')
    finally:
        kernel.CloseHandle(mutex)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        log(type(error).__name__ + ': ' + str(error))
        raise
