import ctypes
import os
import sys
import time
from ctypes import wintypes

MUTEX_NAME = 'Local\\SenCastReceiver.SingleInstance'
WINDOW_TITLE = '森投屏接收端'
ERROR_ALREADY_EXISTS = 183
SW_SHOW = 5
SW_RESTORE = 9
STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001

_handle = None
_LOCK_DIR = os.path.join(os.environ.get('LOCALAPPDATA')
                         or os.path.expanduser('~'), 'SenCastReceiver')
_LOCK_FILE = os.path.join(_LOCK_DIR, 'instance.lock')

_k32 = None


def _kernel32():
    global _k32
    if _k32 is None:
        _k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        _k32.OpenProcess.restype = wintypes.HANDLE
        _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        _k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE,
                                            ctypes.POINTER(wintypes.DWORD)]
        _k32.CloseHandle.argtypes = [wintypes.HANDLE]
        _k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    return _k32


def _pid_alive(pid):
    if not pid or int(pid) <= 0:
        return False
    if os.name != 'nt':
        try:
            os.kill(int(pid), 0)
            return True
        except Exception:
            return False
    try:
        k32 = _kernel32()
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    except Exception:
        return False


def _kill_pid(pid):
    try:
        k32 = _kernel32()
        h = k32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
        if not h:
            return False
        try:
            return bool(k32.TerminateProcess(h, 1))
        finally:
            k32.CloseHandle(h)
    except Exception:
        return False


def _read_pid():
    try:
        with open(_LOCK_FILE, 'r', encoding='utf-8') as f:
            return int((f.read() or '').strip() or 0)
    except Exception:
        return 0


def _write_pid():
    try:
        os.makedirs(_LOCK_DIR, exist_ok=True)
        with open(_LOCK_FILE, 'w', encoding='utf-8') as f:
            f.write(str(os.getpid()))
    except Exception:
        pass


def acquire():
    """返回 True 表示本进程获得启动权；False 表示已有存活实例。"""
    global _handle
    old = _read_pid()
    if old and old != os.getpid() and _pid_alive(old):
        return False
    # 旧 pid 已死（上次崩溃/强杀留下的僵尸）→ 直接接管
    if os.name == 'nt':
        try:
            k32 = _kernel32()
            k32.CreateMutexW.restype = wintypes.HANDLE
            k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL,
                                         wintypes.LPCWSTR]
            h = k32.CreateMutexW(None, False, MUTEX_NAME)
            if h:
                _handle = h
        except Exception:
            pass
    _write_pid()
    return True


def force_cleanup_stale():
    """旧实例存活但窗口找不到（卡死）时，强制结束它并清理锁。"""
    old = _read_pid()
    if not old or old == os.getpid():
        return True
    if _pid_alive(old):
        ok = _kill_pid(old)
        if not ok:
            return False
        for _ in range(20):
            if not _pid_alive(old):
                break
            time.sleep(0.1)
    try:
        os.remove(_LOCK_FILE)
    except Exception:
        pass
    return True


def release():
    global _handle
    try:
        if _handle is not None:
            _kernel32().CloseHandle(_handle)
    except Exception:
        pass
    _handle = None
    try:
        if _read_pid() == os.getpid():
            os.remove(_LOCK_FILE)
    except Exception:
        pass


def _enum_top_windows(u32):
    try:
        EnumWindows = u32.EnumWindows
        GetWindowTextW = u32.GetWindowTextW
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                         wintypes.LPARAM)
        found = []

        def cb(hwnd, lparam):
            buf = ctypes.create_unicode_buffer(512)
            GetWindowTextW(hwnd, buf, 512)
            if '森投屏' in (buf.value or ''):
                found.append(hwnd)
                return False
            return True

        EnumWindows(WNDENUMPROC(cb), 0)
        return found
    except Exception:
        return []


def activate_existing(title=WINDOW_TITLE):
    if os.name != 'nt':
        return False
    try:
        u32 = ctypes.WinDLL('user32', use_last_error=True)
        u32.FindWindowW.restype = wintypes.HWND
        u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u32.SetForegroundWindow.argtypes = [wintypes.HWND]
        u32.IsIconic.argtypes = [wintypes.HWND]
        hwnd = u32.FindWindowW(None, title)
        if not hwnd:
            wins = _enum_top_windows(u32)
            hwnd = wins[0] if wins else 0
        if not hwnd:
            return False
        u32.ShowWindow(hwnd, SW_RESTORE if u32.IsIconic(hwnd) else SW_SHOW)
        u32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False
