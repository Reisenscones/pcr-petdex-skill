"""Restart the installed watcher/pet and test survival after the launcher's job dies.

Uses a temporary Windows job containing only this test's installer process.
Does not close Codex. Restores the desktop pet's previous screen position.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import codex_autostart as watcher

k = watcher.kernel
user = ctypes.WinDLL('user32', use_last_error=True)


class BasicLimits(ctypes.Structure):
    _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                ('flags', w.DWORD), ('min_working', ctypes.c_size_t), ('max_working', ctypes.c_size_t),
                ('active', w.DWORD), ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [('basic', BasicLimits), ('io', ctypes.c_uint64 * 6),
                ('memory', ctypes.c_size_t * 4)]


class StartupInfo(ctypes.Structure):
    _fields_ = [('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR), ('title', w.LPWSTR),
                ('x', w.DWORD), ('y', w.DWORD), ('width', w.DWORD), ('height', w.DWORD),
                ('columns', w.DWORD), ('rows', w.DWORD), ('fill', w.DWORD), ('flags', w.DWORD),
                ('show', w.WORD), ('reserved_size', w.WORD), ('reserved_bytes', ctypes.c_void_p),
                ('stdin', w.HANDLE), ('stdout', w.HANDLE), ('stderr', w.HANDLE)]


class ProcessInfo(ctypes.Structure):
    _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]


k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
k.CreateJobObjectW.restype = w.HANDLE
k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
k.CreateProcessW.argtypes = [w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                            w.BOOL, w.DWORD, ctypes.c_void_p, w.LPCWSTR,
                            ctypes.POINTER(StartupInfo), ctypes.POINTER(ProcessInfo)]
k.ResumeThread.argtypes = [w.HANDLE]
k.ResumeThread.restype = w.DWORD
k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
k.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
user.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
user.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
user.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.UINT]


def require(result):
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    return result


def wait_for(test, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            value = test()
            if value:
                return value
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(.1)
    raise AssertionError('Timed out waiting for independent process')


def read(name):
    return json.loads((ROOT / 'state' / name).read_text(encoding='utf-8'))


def alive(pid):
    handle = k.OpenProcess(0x100000, False, pid)
    if not handle:
        return False
    try:
        return k.WaitForSingleObject(handle, 0) == 258
    finally:
        k.CloseHandle(handle)


def main():
    assert watcher.desktop_processes(), 'Open Codex Desktop before this verification'
    user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    old = read('pcr-heartbeat.json')
    assert old['app'] == 'Ho-chan Desktop Pet' and old['status_path'] == str(ROOT / 'state/codex-status.json')
    rect, owner = w.RECT(), w.DWORD()
    user.GetWindowThreadProcessId(old['hwnd'], ctypes.byref(owner))
    require(user.GetWindowRect(old['hwnd'], ctypes.byref(rect)))
    assert owner.value == old['pid']
    origin = (rect.left, rect.top)
    old_monitor = read('codex-autostart-heartbeat.json')['pid']
    ps = str(Path('C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'))
    args = [ps, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'install-codex-autostart.ps1')]
    subprocess.run(args + ['-Remove'], check=True, stdout=subprocess.DEVNULL, timeout=15)
    wait_for(lambda: not alive(old_monitor), 8)
    require(user.PostMessageW(old['hwnd'], 0x10, 0, 0))
    wait_for(lambda: not watcher.pet_running(), 8)

    job = require(k.CreateJobObjectW(None, None))
    info = ProcessInfo()
    try:
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # Only this test job is killed on close.
        require(k.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
        startup = StartupInfo()
        startup.cb = ctypes.sizeof(startup)
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline(args))
        require(k.CreateProcessW(ps, command, None, None, False, 0x4 | 0x08000000,
                                 None, str(ROOT), ctypes.byref(startup), ctypes.byref(info)))
        require(k.AssignProcessToJobObject(job, info.process))
        assert k.ResumeThread(info.thread) != 0xFFFFFFFF
        assert k.WaitForSingleObject(info.process, 15000) == 0
        code = w.DWORD()
        require(k.GetExitCodeProcess(info.process, ctypes.byref(code)))
        assert code.value == 0, f'Installer failed: {code.value}'
        monitor = wait_for(lambda: (p if (p := read('codex-autostart-heartbeat.json'))['pid'] != old_monitor and alive(p['pid']) else None))
        pet = wait_for(lambda: (p if (p := read('pcr-heartbeat.json'))['pid'] != old['pid'] and
                                p['window_visible'] and p['dpi_scale'] == old['dpi_scale'] and alive(p['pid']) else None))
        assert not watcher.process_in_job(monitor['pid'], job), 'Watcher still belongs to the installer job'
        assert not watcher.process_in_job(pet['pid'], job), 'Pet still belongs to the installer job'
        assert not monitor['launcher_in_job'], 'Outer launcher still belongs to a job'
        closed_at = time.time()
        k.CloseHandle(job)
        job = None
        # Confirm fresh heartbeats after the kill-on-close job has been destroyed.
        monitor = wait_for(lambda: (p if (p := read('codex-autostart-heartbeat.json'))['updated_at'] > closed_at else None), 15)
        pet = wait_for(lambda: (p if datetime.fromisoformat((p := read('pcr-heartbeat.json'))['updated_at']).timestamp() > closed_at else None))
        assert alive(monitor['pid']) and alive(pet['pid'])
        require(user.SetWindowPos(pet['hwnd'], None, *origin, 0, 0, 0x1 | 0x4 | 0x10))
        report = dict(status='passed', checked_at=datetime.now(timezone.utc).isoformat(),
                      launcher_pid=info.pid, launcher_job_destroyed=True, watcher_pid=monitor['pid'],
                      pet_pid=pet['pid'], watcher_in_launcher_job=False, pet_in_launcher_job=False,
                      outer_launcher_in_job=monitor['launcher_in_job'], restored_origin=origin,
                      checks=['Installer launched in a kill-on-close Windows job',
                              'WMI starts watcher outside both caller and WMI provider jobs',
                              'Watcher automatically starts pet when Codex is open',
                              'Watcher and pet keep updating after launcher job destruction'])
        (ROOT / 'build/autostart-lifetime-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        if job:
            k.CloseHandle(job)
        for handle in (info.thread, info.process):
            if handle:
                k.CloseHandle(handle)


if __name__ == '__main__':
    main()
