"""Windows-wide Htek credential shortcuts for the desktop launcher.

A browser page is sandboxed and cannot react to keys while another application
(the phone's web UI) has focus.  When the app runs through ``launcher.py`` the
page pushes its current shortcuts and credentials here, and this module installs
a native Windows low-level keyboard hook.  Pressing a shortcut mirrors the
original desktop tool:

    type username  ->  Tab  ->  type password  ->  Enter

A hook is used instead of ``RegisterHotKey`` on purpose: ``RegisterHotKey``
fails with error 1409 when another program (PowerToys, a vendor utility, ...)
already owns the chord.  The hook observes the keys first and lets external
applications see the chord too, exactly like the original desktop tool.

When the launcher window itself is focused the chord is consumed and the
credentials are put on the Windows clipboard, because another program may
already own the chord and keep the page from ever seeing it.  The page only
shows the toast.

No third-party dependency is used: the Win32 calls are made through ``ctypes``.
"""

from __future__ import annotations

import ctypes
import json
import os
import tempfile
import threading
import time
from ctypes import wintypes
from typing import Callable, Dict, List, Optional

# --------------------------------------------------------------------------- Win32
_IS_WINDOWS = os.name == "nt"

_MOD_ALT = 0x0001
_MOD_CONTROL = 0x0002
_MOD_SHIFT = 0x0004
_MOD_WIN = 0x0008
_MOD_ALL = _MOD_ALT | _MOD_CONTROL | _MOD_SHIFT | _MOD_WIN

_VK_SHIFT = 0x10
_VK_CONTROL = 0x11
_VK_MENU = 0x12
_VK_LWIN = 0x5B
_VK_RWIN = 0x5C

_VK_TAB = 0x09
_VK_RETURN = 0x0D

_WH_KEYBOARD_LL = 13
_WM_KEYDOWN = 0x0100
_WM_KEYUP = 0x0101
_WM_SYSKEYDOWN = 0x0104
_WM_SYSKEYUP = 0x0105
_WM_QUIT = 0x0012
_PM_NOREMOVE = 0x0000

_MODIFIERS = {
    "Ctrl": _MOD_CONTROL,
    "Alt": _MOD_ALT,
    "Shift": _MOD_SHIFT,
    "Meta": _MOD_WIN,
}

_VK_NAMES = {
    "Backspace": 0x08,
    "Tab": 0x09,
    "Enter": 0x0D,
    "Escape": 0x1B,
    "Space": 0x20,
    "PageUp": 0x21,
    "PageDown": 0x22,
    "End": 0x23,
    "Home": 0x24,
    "ArrowLeft": 0x25,
    "ArrowUp": 0x26,
    "ArrowRight": 0x27,
    "ArrowDown": 0x28,
    "Insert": 0x2D,
    "Delete": 0x2E,
    "Meta": 0x5B,
    "ContextMenu": 0x5D,
    "NumpadMultiply": 0x6A,
    "NumpadAdd": 0x6B,
    "NumpadSubtract": 0x6D,
    "NumpadDecimal": 0x6E,
    "NumpadDivide": 0x6F,
}

_PUNCTUATION = {
    "Minus": "-",
    "Equal": "=",
    "Comma": ",",
    "Period": ".",
    "Slash": "/",
    "Semicolon": ";",
    "Quote": "'",
    "BracketLeft": "[",
    "BracketRight": "]",
    "Backslash": "\\",
    "Backquote": "`",
}

_MUTEX_NAME = "Local\\DpAutoWebHtekHotkeys"

if _IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _LRESULT = ctypes.c_ssize_t
    _HHOOK = ctypes.c_void_p
    _LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
        _LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
    )

    _user32.SetWindowsHookExW.argtypes = [
        ctypes.c_int,
        _LowLevelKeyboardProc,
        wintypes.HINSTANCE,
        wintypes.DWORD,
    ]
    _user32.SetWindowsHookExW.restype = _HHOOK
    _user32.CallNextHookEx.argtypes = [
        _HHOOK,
        ctypes.c_int,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    _user32.CallNextHookEx.restype = _LRESULT
    _user32.UnhookWindowsHookEx.argtypes = [_HHOOK]
    _user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    _user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
    ]
    _user32.GetMessageW.restype = ctypes.c_int
    _user32.PeekMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
        wintypes.UINT,
    ]
    _user32.PeekMessageW.restype = wintypes.BOOL
    _user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.PostThreadMessageW.argtypes = [
        wintypes.DWORD,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    _user32.PostThreadMessageW.restype = wintypes.BOOL
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
    _user32.VkKeyScanW.restype = ctypes.c_short
    _user32.SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]
    _user32.SendInput.restype = wintypes.UINT
    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.EmptyClipboard.restype = wintypes.BOOL
    _user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _user32.SetClipboardData.restype = wintypes.HANDLE
    _user32.CloseClipboard.restype = wintypes.BOOL
    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = wintypes.HANDLE
    _kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    _kernel32.GlobalLock.restype = ctypes.c_void_p
    _kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    _kernel32.GlobalUnlock.restype = wintypes.BOOL
    _kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalFree.restype = wintypes.HGLOBAL
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = (
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    )


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    )


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    )


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = (
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    )


class _INPUTUNION(ctypes.Union):
    _fields_ = (("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT))


class _INPUT(ctypes.Structure):
    _fields_ = (("type", wintypes.DWORD), ("u", _INPUTUNION))


_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004

_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002

# The launcher and the backend are separate processes.  A tiny JSON file is the
# most reliable hand-off: pywebview's evaluate_js deadlocks when it is pushed
# from the low-level keyboard-hook thread, so the page polls this instead.
_HOTKEY_EVENT_FILE = os.environ.get("DP_HTEK_EVENT_FILE") or os.path.join(
    tempfile.gettempdir(), "dp_auto_web_htek_hotkey.json"
)


def _publish_copy(index: int, seq: int) -> None:
    """Record the last in-app copy for the page's HTTP poll."""
    try:
        payload = {"seq": int(seq), "index": int(index), "at": time.time()}
        temp_path = f"{_HOTKEY_EVENT_FILE}.tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(temp_path, _HOTKEY_EVENT_FILE)
    except Exception:
        pass  # feedback only; copying already succeeded


def _write_clipboard(text: str) -> bool:
    """Put ``text`` on the Windows clipboard (works while WebView2 is focused)."""
    if not _IS_WINDOWS:
        return False
    data = ctypes.create_unicode_buffer(text)
    for _ in range(5):
        handle = _kernel32.GlobalAlloc(_GMEM_MOVEABLE, ctypes.sizeof(data))
        if not handle:
            continue
        pointer = _kernel32.GlobalLock(handle)
        if not pointer:
            _kernel32.GlobalFree(handle)
            continue
        ctypes.memmove(pointer, ctypes.byref(data), ctypes.sizeof(data))
        _kernel32.GlobalUnlock(handle)
        if not _user32.OpenClipboard(None):
            _kernel32.GlobalFree(handle)
            time.sleep(0.03)
            continue
        try:
            _user32.EmptyClipboard()
            if _user32.SetClipboardData(_CF_UNICODETEXT, handle):
                return True
        finally:
            _user32.CloseClipboard()
        _kernel32.GlobalFree(handle)
        time.sleep(0.03)
    return False


def _claim_single_instance():
    """Only one launcher process may own the global hotkeys.

    The launcher can attach a second window to an already running backend; both
    windows would otherwise type the credentials twice.
    """
    if not _IS_WINDOWS:
        return None
    try:
        _kernel32.CreateMutexW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        _kernel32.CreateMutexW.restype = wintypes.HANDLE
        _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        _kernel32.CloseHandle.restype = wintypes.BOOL
        handle = _kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        if not handle:
            return None
        if _kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            _kernel32.CloseHandle(handle)
            return None
        return handle
    except Exception:
        return None


def _release_mutex(handle) -> None:
    if not handle:
        return
    try:
        _kernel32.CloseHandle(handle)
    except Exception:
        pass


def _vk_for_code(part: str) -> int:
    if part.startswith("Digit") and part[5:].isdigit():
        return 0x30 + int(part[5:])
    if part.startswith("Numpad") and part[6:].isdigit():
        return 0x60 + int(part[6:])
    if part.startswith("Key") and len(part) == 4:
        return 0x41 + ord(part[3].upper()) - ord("A")
    if part.startswith("F") and part[1:].isdigit():
        number = int(part[1:])
        if 1 <= number <= 24:
            return 0x70 + number - 1
    known = _VK_NAMES.get(part)
    if known:
        return known
    character = _PUNCTUATION.get(part)
    if character and _IS_WINDOWS:
        result = _user32.VkKeyScanW(character)
        if result != -1:
            return result & 0xFF
    return 0


def combo_to_win32(combo: str):
    """Convert a page combo (``Alt+Digit1``) to ``(modifiers, virtual-key)``."""
    parts = [part for part in str(combo or "").split("+") if part]
    if not parts:
        return None
    modifiers = 0
    vk = 0
    for part in parts:
        mapped = _MODIFIERS.get(part)
        if mapped:
            modifiers |= mapped
        else:
            vk = _vk_for_code(part)
    if not vk:
        return None
    return modifiers, vk


def _foreground_is_own_process() -> bool:
    """True when the launcher's WebView window is the active window."""
    if not _IS_WINDOWS:
        return False
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return False
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value == os.getpid()
    except Exception:
        return False


def _modifier_bits() -> int:
    bits = 0
    try:
        if _user32.GetAsyncKeyState(_VK_MENU) & 0x8000:
            bits |= _MOD_ALT
        if _user32.GetAsyncKeyState(_VK_CONTROL) & 0x8000:
            bits |= _MOD_CONTROL
        if _user32.GetAsyncKeyState(_VK_SHIFT) & 0x8000:
            bits |= _MOD_SHIFT
        if (_user32.GetAsyncKeyState(_VK_LWIN) | _user32.GetAsyncKeyState(_VK_RWIN)) & 0x8000:
            bits |= _MOD_WIN
    except Exception:
        return 0
    return bits


def _key_input(vk: int = 0, scan: int = 0, flags: int = 0) -> _INPUT:
    item = _INPUT()
    item.type = _INPUT_KEYBOARD
    item.u.ki.wVk = vk
    item.u.ki.wScan = scan
    item.u.ki.dwFlags = flags
    return item


def _send_inputs(items: List[_INPUT]) -> None:
    if not items or not _IS_WINDOWS:
        return
    array = (_INPUT * len(items))(*items)
    sent = _user32.SendInput(len(items), ctypes.byref(array), ctypes.sizeof(_INPUT))
    if sent != len(items):
        raise OSError(f"SendInput sent {sent}/{len(items)} events")


def _type_text(text: str) -> None:
    """Type arbitrary Unicode text independently of the keyboard layout."""
    units: List[int] = []
    for character in text:
        code = ord(character)
        if code > 0xFFFF:
            code -= 0x10000
            units.append(0xD800 + (code >> 10))
            units.append(0xDC00 + (code & 0x3FF))
        else:
            units.append(code)
    items: List[_INPUT] = []
    for unit in units:
        items.append(_key_input(scan=unit, flags=_KEYEVENTF_UNICODE))
        items.append(_key_input(scan=unit, flags=_KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP))
    _send_inputs(items)


def _press_vk(vk: int) -> None:
    _send_inputs([_key_input(vk=vk), _key_input(vk=vk, flags=_KEYEVENTF_KEYUP)])


def _wait_for_modifiers() -> None:
    deadline = time.time() + 1.5
    virtual_keys = (0x11, 0x12, 0x10, 0x5B, 0x5C)  # Ctrl, Alt, Shift, LWin, RWin
    while time.time() < deadline:
        try:
            pressed = any(_user32.GetAsyncKeyState(vk) & 0x8000 for vk in virtual_keys)
        except Exception:
            break
        if not pressed:
            break
        time.sleep(0.02)
    time.sleep(0.05)


def _event_is_keydown(wparam: int) -> bool:
    return wparam in (_WM_KEYDOWN, _WM_SYSKEYDOWN)


def _event_is_keyup(wparam: int) -> bool:
    return wparam in (_WM_KEYUP, _WM_SYSKEYUP)


class GlobalHtekHotkeys:
    def __init__(self, log: Optional[Callable[[str], None]] = None) -> None:
        self._log = log or (lambda _message: None)
        self._lock = threading.RLock()
        self._typing = threading.Lock()
        self._entries: List[Dict[str, object]] = []
        self._last_error = ""
        self._last_copy: Dict[str, int] = {"seq": 0, "index": -1}
        self._thread: Optional[threading.Thread] = None
        self._thread_id = 0
        self._generation = 0
        self._installed = False
        self._held_vks: set = set()
        self._consumed_vks: set = set()
        self._mutex = _claim_single_instance()
        self._single_instance = self._mutex is not None or not _IS_WINDOWS

    # ------------------------------------------------------------------ setup
    def supported(self) -> bool:
        return _IS_WINDOWS and self._single_instance

    def status(self) -> dict:
        with self._lock:
            return {
                "ok": self._installed and not self._last_error,
                "supported": self.supported(),
                "count": len(self._entries) if self._installed else 0,
                "combos": [str(entry["display"]) for entry in self._entries]
                if self._installed
                else [],
                "error": self._last_error,
                "last_copy": dict(self._last_copy),
            }

    def update(self, entries) -> dict:
        if not _IS_WINDOWS:
            return {
                "ok": False,
                "supported": False,
                "count": 0,
                "combos": [],
                "error": "Global shortcuts need the Windows desktop launcher.",
            }
        if not self._single_instance:
            return {
                "ok": False,
                "supported": False,
                "count": 0,
                "combos": [],
                "error": "Another launcher window already owns the global shortcuts.",
            }

        cleaned: List[Dict[str, object]] = []
        seen = set()
        errors: List[str] = []
        for raw in list(entries or [])[:2]:
            if not isinstance(raw, dict):
                continue
            display = str(raw.get("combo") or "")
            parsed = combo_to_win32(display)
            if parsed is None:
                errors.append(f"{display or 'unknown shortcut'}: not a supported key combination")
                continue
            if not parsed[0]:
                errors.append(f"{display}: the shortcut needs Ctrl, Alt or Meta")
                continue
            if parsed in seen:
                errors.append(f"{display}: used by both shortcuts")
                continue
            seen.add(parsed)
            cleaned.append(
                {
                    "id": len(cleaned) + 1,
                    "combo": parsed,
                    "display": display,
                    "user": str(raw.get("user") or ""),
                    "pass": str(raw.get("pass") or ""),
                }
            )

        with self._lock:
            # The page pushes its settings on mount and again on
            # ``pywebviewready``.  Reinstalling the hook for identical settings
            # would leave a short window where the shortcut is not armed, so
            # treat a repeat push as a no-op.
            if self._installed and not errors and cleaned == self._entries:
                return self.status()

        self._stop_listener()
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._entries = cleaned
            self._last_error = "; ".join(errors)
            self._installed = False
            self._held_vks = set()
            self._consumed_vks = set()
        if not cleaned:
            return self.status()

        ready = threading.Event()
        thread = threading.Thread(
            target=self._listen,
            args=(generation, cleaned, ready),
            name="htek-global-hotkeys",
            daemon=True,
        )
        with self._lock:
            self._thread = thread
        thread.start()
        ready.wait(2.5)
        result = self.status()
        if result["ok"]:
            self._log(
                "global hotkeys active: "
                + (", ".join(str(entry["display"]) for entry in cleaned) or "none")
            )
        else:
            self._log(f"global hotkeys unavailable: {result['error'] or 'unknown error'}")
        return result

    def stop(self) -> None:
        self._stop_listener()
        _release_mutex(self._mutex)
        self._mutex = None

    def _stop_listener(self) -> None:
        with self._lock:
            self._generation += 1
            thread_id = self._thread_id
            thread = self._thread
            self._thread = None
            self._thread_id = 0
            self._installed = False
            self._entries = []
            self._held_vks = set()
            self._consumed_vks = set()
        if thread_id:
            try:
                _user32.PostThreadMessageW(thread_id, _WM_QUIT, 0, 0)
            except Exception:
                pass
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.5)

    # --------------------------------------------------------------- hook loop
    def _listen(self, generation: int, entries: List[Dict[str, object]], ready: threading.Event) -> None:
        def handler(code, wparam, lparam):
            if code >= 0 and (wparam in (_WM_KEYDOWN, _WM_SYSKEYDOWN, _WM_KEYUP, _WM_SYSKEYUP)):
                info = ctypes.cast(lparam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
                try:
                    if self._handle_key_event(int(info.vkCode), int(wparam)):
                        return 1  # consume the shortcut key
                except Exception as exc:  # noqa: BLE001 - never break the hook chain
                    self._log(f"global hotkey hook error: {exc}")
            return _user32.CallNextHookEx(None, code, wparam, lparam)

        callback = _LowLevelKeyboardProc(handler)
        self._hook_callback = callback  # keep a reference for the hook's lifetime

        # Force this thread's message queue into existence before another
        # thread can post WM_QUIT to it.
        message = wintypes.MSG()
        _user32.PeekMessageW(ctypes.byref(message), None, 0, 0, _PM_NOREMOVE)
        thread_id = _kernel32.GetCurrentThreadId()

        hook = None
        try:
            hook = _user32.SetWindowsHookExW(_WH_KEYBOARD_LL, callback, None, 0)
        except Exception as exc:  # noqa: BLE001
            hook = None
            error = f"could not install the keyboard hook: {exc}"
        else:
            error = "" if hook else f"could not install the keyboard hook ({ctypes.get_last_error()})"

        with self._lock:
            if generation != self._generation:
                ready.set()
                stale = True
            else:
                self._thread_id = thread_id
                self._installed = bool(hook) and not error
                if error:
                    self._last_error = error
                stale = False
        if stale:
            if hook:
                _user32.UnhookWindowsHookEx(hook)
            ready.set()
            return
        ready.set()

        if not hook:
            self._log(error)
            return

        try:
            while True:
                result = _user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0:
                    break
                _user32.TranslateMessage(ctypes.byref(message))
                _user32.DispatchMessageW(ctypes.byref(message))
        finally:
            try:
                _user32.UnhookWindowsHookEx(hook)
            except Exception:
                pass
            with self._lock:
                if self._thread_id == thread_id:
                    self._thread_id = 0
                    self._installed = False

    def _handle_key_event(self, vk: int, wparam: int) -> bool:
        if _event_is_keyup(wparam):
            self._held_vks.discard(vk)
            if vk in self._consumed_vks:
                self._consumed_vks.discard(vk)
                return True
            return False
        if not _event_is_keydown(wparam):
            return False

        if vk in self._held_vks:
            return vk in self._consumed_vks  # auto-repeat
        modifiers = _modifier_bits() & _MOD_ALL
        with self._lock:
            entry = next(
                (
                    item
                    for item in self._entries
                    if int(item["combo"][1]) == vk  # type: ignore[index]
                    and int(item["combo"][0]) & _MOD_ALL == modifiers  # type: ignore[index]
                ),
                None,
            )
        if entry is None:
            return False
        self._held_vks.add(vk)
        if _foreground_is_own_process():
            # The page cannot see chords that another program has registered
            # (PowerToys owns Alt+2 here), so copy here and let the page know.
            self._consumed_vks.add(vk)
            self._fire(dict(entry))
            return True
        self._fire(dict(entry))
        return False  # let the target application see the chord as well

    # ----------------------------------------------------------------- trigger
    def _fire(self, entry: Dict[str, object]) -> None:
        threading.Thread(
            target=self._perform,
            args=(entry,),
            name=f"htek-hotkey-{entry.get('id')}",
            daemon=True,
        ).start()

    def _copy_to_clipboard(self, entry: Dict[str, object]) -> None:
        user = str(entry.get("user") or "")
        password = str(entry.get("pass") or "")
        if not _write_clipboard(f"{user}\t{password}"):
            self._log("global hotkey: could not write to the clipboard")
            return
        index = int(entry["id"]) - 1
        # The page polls status() and reacts to a new seq.  Pushing JS from the
        # hotkey thread deadlocks pywebview's evaluate_js, so the page pulls.
        with self._lock:
            self._last_copy["seq"] += 1
            self._last_copy["index"] = index
            seq = self._last_copy["seq"]
        _publish_copy(index, seq)

    def _perform(self, entry: Dict[str, object]) -> None:
        # Copying for the launcher's own window is instant and must never be
        # dropped: another suite may fire while the previous one is still
        # finishing.  Only the typing path needs the exclusivity lock.
        if _foreground_is_own_process():
            try:
                self._copy_to_clipboard(entry)
            except Exception as exc:  # noqa: BLE001
                self._log(f"global hotkey clipboard failed: {exc}")
            return
        if not self._typing.acquire(blocking=False):
            return  # a previous shortcut is still typing
        try:
            _wait_for_modifiers()
            # Let the target window finish processing the modifier release;
            # otherwise the first typed character can be eaten as a menu
            # accelerator (e.g. Alt+t).
            time.sleep(0.2)
            if _foreground_is_own_process():
                self._copy_to_clipboard(entry)
                return
            user = str(entry.get("user") or "")
            password = str(entry.get("pass") or "")
            if user:
                _type_text(user)
                time.sleep(0.03)
            _press_vk(_VK_TAB)
            time.sleep(0.05)
            if password:
                _type_text(password)
                time.sleep(0.03)
            _press_vk(_VK_RETURN)
        except Exception as exc:  # noqa: BLE001 - never kill the listener
            self._log(f"global hotkey typing failed: {exc}")
        finally:
            self._typing.release()
