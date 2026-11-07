"""退出清场：点「退出」就把本软件及其拉起的全部进程一次性杀干净。

三层保险（Windows）：
1) Job Object + JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
   启动时把本进程放进 Job，之后所有子进程自动归入同一个 Job；
   进程句柄一关，内核把 Job 里剩下的进程全部终止，不依赖 Python/Qt 优雅退出。
2) 进程树强杀
   退出前遍历 ToolHelp32 快照，收集本进程所有后代，逐个 TerminateProcess。
3) 相关实例强杀
   同名 exe（含 PyInstaller onefile 的父 bootloader / 上次残留的僵尸实例）、
   命令行或映像路径带本项目标记的 python / 播放器后端，一并清掉。

刻意不关闭 Job 句柄：进程结束时由内核关闭，从而触发 KILL_ON_JOB_CLOSE。
不碰 explorer.exe 等系统 shell，避免把用户桌面一起干掉。
"""

import ctypes
import os
import struct
import sys
from ctypes import wintypes

IS_WIN = os.name == 'nt'

_JOB_HANDLE = None
_ARMED = False

# ---- 常量 ----
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ProcessCommandLineInformation = 60
MAX_PATH = 260

APP_EXE_NAMES = {
    'senaicastreceiver.exe',
    '森投屏接收端.exe',
    'sencast.exe',
    '森投屏接收端.msix',
}
# 命令行 / 映像路径命中这些标记，就认定跟本软件有关
PROJECT_MARKERS = (
    'cast-receiver', 'sencast', 'senai-cast', '森投屏',
    'sensen.3730939450514', 'senaicastreceiver',
)
# 系统 shell 与宿主，无论如何都不杀
SAFE_NAMES = {
    'explorer.exe', 'dwm.exe', 'winlogon.exe', 'csrss.exe', 'smss.exe',
    'services.exe', 'lsass.exe', 'svchost.exe', 'powershell.exe',
    'pwsh.exe', 'cmd.exe', 'conhost.exe', 'runtimebroker.exe',
    'applicationframehost.exe', 'systemsettings.exe', 'sihost.exe',
    'shellhost.exe', 'searchhost.exe', 'startmenuexperiencehost.exe',
    'workbuddy.exe', 'code.exe', 'devenv.exe',
}

if IS_WIN:
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    try:
        ntdll = ctypes.WinDLL('ntdll', use_last_error=True)
    except Exception:
        ntdll = None
else:
    k32 = None
    ntdll = None


# ---- Job Object 结构体 ----
class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ('ReadOperationCount', ctypes.c_ulonglong),
        ('WriteOperationCount', ctypes.c_ulonglong),
        ('OtherOperationCount', ctypes.c_ulonglong),
        ('ReadTransferCount', ctypes.c_ulonglong),
        ('WriteTransferCount', ctypes.c_ulonglong),
        ('OtherTransferCount', ctypes.c_ulonglong),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('PerProcessUserTimeLimit', ctypes.c_longlong),
        ('PerJobUserTimeLimit', ctypes.c_longlong),
        ('LimitFlags', wintypes.DWORD),
        ('MinimumWorkingSetSize', ctypes.c_size_t),
        ('MaximumWorkingSetSize', ctypes.c_size_t),
        ('ActiveProcessLimit', wintypes.DWORD),
        ('Affinity', ctypes.c_size_t),
        ('PriorityClass', wintypes.DWORD),
        ('SchedulingClass', wintypes.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('BasicLimitInformation', JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ('IoInfo', IO_COUNTERS),
        ('ProcessMemoryLimit', ctypes.c_size_t),
        ('JobMemoryLimit', ctypes.c_size_t),
        ('PeakProcessMemoryUsed', ctypes.c_size_t),
        ('PeakJobMemoryUsed', ctypes.c_size_t),
    ]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ('dwSize', wintypes.DWORD),
        ('cntUsage', wintypes.DWORD),
        ('th32ProcessID', wintypes.DWORD),
        ('th32DefaultHeapID', ctypes.c_void_p),
        ('th32ModuleID', wintypes.DWORD),
        ('cntThreads', wintypes.DWORD),
        ('th32ParentProcessID', wintypes.DWORD),
        ('pcPriClassBase', ctypes.c_long),
        ('dwFlags', wintypes.DWORD),
        ('szExeFile', wintypes.WCHAR * MAX_PATH),
    ]


def arm():
    """启动时调用：把本进程扔进「关闭即杀光」的 Job。失败不影响运行，有兜底。"""
    global _JOB_HANDLE, _ARMED
    if not IS_WIN or _ARMED:
        return _ARMED
    _ARMED = True
    try:
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.GetCurrentProcess.restype = wintypes.HANDLE

        h = k32.CreateJobObjectW(None, None)
        if not h:
            return False
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = k32.SetInformationJobObject(
            h, JobObjectExtendedLimitInformation,
            ctypes.byref(info), ctypes.sizeof(info))
        if not ok:
            k32.CloseHandle(h)
            return False
        # 已处于别的 Job 时会返回失败（ERROR_ACCESS_DENIED），此时靠进程树兜底
        if not k32.AssignProcessToJobObject(h, k32.GetCurrentProcess()):
            k32.CloseHandle(h)
            return False
        _JOB_HANDLE = h  # 故意不 CloseHandle
        return True
    except Exception:
        return False


# ---- 进程枚举 ----
def _snapshot():
    """返回 {pid: (ppid, name)}。"""
    result = {}
    if not IS_WIN:
        return result
    try:
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snap or snap == wintypes.HANDLE(-1).value:
            return result
        try:
            ent = PROCESSENTRY32W()
            ent.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            more = k32.Process32FirstW(snap, ctypes.byref(ent))
            while more:
                result[int(ent.th32ProcessID)] = (
                    int(ent.th32ParentProcessID), ent.szExeFile)
                more = k32.Process32NextW(snap, ctypes.byref(ent))
        finally:
            k32.CloseHandle(snap)
    except Exception:
        pass
    return result


def _exepath(pid):
    if not IS_WIN:
        return ''
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ''
    try:
        k32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD)]
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
    except Exception:
        pass
    finally:
        k32.CloseHandle(h)
    return ''


def _cmdline(pid):
    """读目标进程命令行（NtQueryInformationProcess + ReadProcessMemory）。"""
    if not IS_WIN or ntdll is None:
        return ''
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ''
    try:
        size = 8192
        buf = ctypes.create_string_buffer(size)
        ret = wintypes.ULONG(0)
        ntdll.NtQueryInformationProcess.argtypes = [
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID,
            wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
        if ntdll.NtQueryInformationProcess(h, ProcessCommandLineInformation,
                                           buf, size, ctypes.byref(ret)) != 0:
            return ''
        raw = buf.raw
        length = struct.unpack_from('<H', raw, 0)[0]
        if not length or length > 65534:
            return ''
        # Win10+ 会把 UNICODE_STRING 的字符串直接追加在返回缓冲区头部之后
        off = 16 if ctypes.sizeof(ctypes.c_void_p) == 8 else 8
        inline = raw[off:off + length]
        try:
            text = inline.decode('utf-16-le', 'ignore').split('\x00')[0]
            if text:
                return text
        except Exception:
            pass
        # 老版本/特殊情况：指针指向目标进程内存，读出来
        ptr = struct.unpack_from('<Q', raw, 8)[0] if off == 16 \
            else struct.unpack_from('<I', raw, 4)[0]
        if not ptr:
            return ''
        out = ctypes.create_unicode_buffer(length // 2 + 2)
        read = ctypes.c_size_t(0)
        k32.ReadProcessMemory.argtypes = [
            wintypes.HANDLE, wintypes.LPCVOID, wintypes.LPVOID,
            ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        if not k32.ReadProcessMemory(h, ctypes.c_void_p(ptr), out,
                                     length, ctypes.byref(read)):
            return ''
        return out.value
    except Exception:
        return ''
    finally:
        k32.CloseHandle(h)


def _marked(text):
    t = (text or '').lower()
    return any(m in t for m in PROJECT_MARKERS)


def related_pids(snap=None, self_pid=None, root_pid=None):
    """列出所有跟本软件有关的 pid（不含自身）。

    root_pid 不为空时，额外把该 pid 及其整棵后代树列进来（用于清理上次卡死实例）。
    """
    snap = snap if snap is not None else _snapshot()
    me = self_pid if self_pid is not None else os.getpid()
    root = root_pid if root_pid else me

    kids = {}
    for pid, (ppid, _name) in snap.items():
        kids.setdefault(ppid, []).append(pid)

    # 1) 本进程（或指定根）所有后代
    desc = set()
    stack = list(kids.get(root, []))
    if root != me:
        stack.append(root)
    while stack:
        p = stack.pop()
        if p in desc or p == me:
            continue
        desc.add(p)
        stack.extend(kids.get(p, []))

    result = set()
    for pid in desc:
        name = (snap.get(pid) or (0, ''))[1].lower()
        if name not in SAFE_NAMES and pid != me:
            result.add(pid)

    # 2) 同名 exe / 项目标记的进程（含上次残留、PyInstaller 父进程）
    for pid, (_ppid, name) in snap.items():
        if pid == me or not name:
            continue
        low = name.lower()
        if low in SAFE_NAMES:
            continue
        if low in APP_EXE_NAMES:
            result.add(pid)
            continue
        path = _exepath(pid)
        if path and _marked(path):
            result.add(pid)
            continue
        if low in ('python.exe', 'pythonw.exe', 'ffmpeg.exe', 'vlc.exe',
                   'mpv.exe', 'scrcpy.exe', 'adb.exe', 'ffprobe.exe'):
            if _marked(_cmdline(pid)) or _marked(path):
                result.add(pid)
    result.discard(me)
    return result, desc


def _terminate(pid):
    if not IS_WIN:
        return False
    h = k32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not h:
        return False
    try:
        return bool(k32.TerminateProcess(h, 1))
    except Exception:
        return False
    finally:
        k32.CloseHandle(h)


def nuke(self_pid=None, root_pid=None):
    """强杀所有相关进程，返回 [(pid, name)]。不杀自身，由调用方 os._exit。"""
    me = self_pid if self_pid is not None else os.getpid()
    snap = _snapshot()
    pids, _desc = related_pids(snap=snap, self_pid=me, root_pid=root_pid)
    # 杀两轮：第一轮结束后可能有进程被父进程重启/拉起，第二轮补刀
    killed = []
    for _ in range(2):
        batch = []
        current = _snapshot()
        for pid in sorted(pids):
            if pid == me or pid not in current:
                continue
            if _terminate(pid):
                batch.append((pid, (snap.get(pid) or current.get(pid) or (0, '?'))[1]))
        killed.extend(batch)
        if not batch:
            break
        # 重新扫一遍，抓新冒出来的相关进程
        snap = _snapshot()
        pids, _ = related_pids(snap=snap, self_pid=me, root_pid=root_pid)
    # 去重返回
    seen = set()
    out = []
    for pid, name in killed:
        if pid not in seen:
            seen.add(pid)
            out.append((pid, name))
    return out


def hard_exit(code=0):
    """点退出就走这里：清锁 → 杀光相关进程 → 立刻 os._exit，不等任何线程。"""
    try:
        from receiver.single import release
        release()
    except Exception:
        pass
    try:
        killed = nuke()
        if killed:
            try:
                sys.stdout.write('[退出] 已清理残留进程: %s\n' % ', '.join(
                    '%s(%s)' % (n, p) for p, n in killed))
            except Exception:
                pass
    except Exception:
        pass
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(code if isinstance(code, int) else 0)
