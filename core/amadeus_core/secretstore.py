"""Logins Amadeus keeps for you (mail passwords and sign-in tokens), in the system's own safe place: the Keychain on a
Mac, the Credential Manager on Windows.

On a Mac that's the Keychain: encrypted with your login, locked when you are logged out, and in Keychain Access you can
see each item ("Amadeus" plus what it's for). It's reached through the Security framework directly (ctypes, standard
library only), so a secret never shows up in a command line or a file. Elsewhere `native()` is False and the caller keeps
its file in secrets/, readable only by you (Linux has no Keychain that is always there; that's a later step).

The app is signed ad hoc, not with a paid certificate, so after an update macOS may ask once whether Amadeus may use
its Keychain items again: "Always Allow" answers it for that version."""
import ctypes
import ctypes.util
import threading

from . import system

SERVICE = b"Amadeus"
_lock = threading.Lock()
_sec = None
ERR_NOT_FOUND = -25300  # errSecItemNotFound


class Unavailable(RuntimeError):
    pass


def _lib():
    global _sec
    if _sec is None:
        path = ctypes.util.find_library("Security") or "/System/Library/Frameworks/Security.framework/Security"
        sec = ctypes.cdll.LoadLibrary(path)
        cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation") or "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        u32, vp, cp = ctypes.c_uint32, ctypes.c_void_p, ctypes.c_char_p
        sec.SecKeychainAddGenericPassword.argtypes = [vp, u32, cp, u32, cp, u32, cp, ctypes.POINTER(vp)]
        sec.SecKeychainFindGenericPassword.argtypes = [vp, u32, cp, u32, cp, ctypes.POINTER(u32), ctypes.POINTER(vp), ctypes.POINTER(vp)]
        sec.SecKeychainItemModifyAttributesAndData.argtypes = [vp, vp, u32, cp]
        sec.SecKeychainItemDelete.argtypes = [vp]
        sec.SecKeychainItemFreeContent.argtypes = [vp, vp]
        for f in (sec.SecKeychainAddGenericPassword, sec.SecKeychainFindGenericPassword, sec.SecKeychainItemModifyAttributesAndData,
                  sec.SecKeychainItemDelete, sec.SecKeychainItemFreeContent):
            f.restype = ctypes.c_int32
        cf.CFRelease.argtypes = [vp]
        sec.CFRelease = cf.CFRelease
        _sec = sec
    return _sec


def native():
    """True where the system's own store is used (a Mac, Windows)."""
    return system.MAC or system.WIN


def _check(status, what):
    if status:
        raise Unavailable(f"The Keychain refused to {what} (error {status}). Is it locked?")


def _find(name):
    """(item ref or None, value or None)."""
    sec, n = _lib(), name.encode()
    length, data, item = ctypes.c_uint32(), ctypes.c_void_p(), ctypes.c_void_p()
    status = sec.SecKeychainFindGenericPassword(None, len(SERVICE), SERVICE, len(n), n, ctypes.byref(length), ctypes.byref(data), ctypes.byref(item))
    if status == ERR_NOT_FOUND:
        return None, None
    _check(status, "read a login")
    try:
        value = ctypes.string_at(data, length.value).decode()
    finally:
        sec.SecKeychainItemFreeContent(None, data)
    return item, value


def put(name, value):
    """Store (or replace) one secret under name."""
    if not native():
        raise Unavailable("No system keychain here.")
    if system.WIN:
        return _win_put(name, value)
    v = str(value).encode()
    with _lock:
        sec = _lib()
        item, old = _find(name)
        try:
            if item is not None:
                if old != value:
                    _check(sec.SecKeychainItemModifyAttributesAndData(item, None, len(v), v), "change a login")
                return
            n = name.encode()
            _check(sec.SecKeychainAddGenericPassword(None, len(SERVICE), SERVICE, len(n), n, len(v), v, None), "keep a login")
        finally:
            if item is not None:
                sec.CFRelease(item)


def get(name):
    """The secret, or None when there is none."""
    if not native():
        raise Unavailable("No system keychain here.")
    if system.WIN:
        return _win_get(name)
    with _lock:
        item, value = _find(name)
        if item is not None:
            _lib().CFRelease(item)
        return value


def delete(name):
    if not native():
        raise Unavailable("No system keychain here.")
    if system.WIN:
        return _win_delete(name)
    with _lock:
        item, _ = _find(name)
        if item is None:
            return
        try:
            _check(_lib().SecKeychainItemDelete(item), "remove a login")
        finally:
            _lib().CFRelease(item)


# ---------- Windows: the Credential Manager (Control Panel → Credential Manager → Windows Credentials, "Amadeus/…") ----------
# A credential holds at most 2,560 bytes, and a Microsoft sign-in token can be longer: a long secret is kept in parts.
WIN_PART = 2400
CRED_TYPE_GENERIC, CRED_PERSIST_LOCAL_MACHINE, ERROR_NOT_FOUND = 1, 2, 1168
_advapi = None


def _win():
    global _advapi
    if _advapi is None:
        import ctypes.wintypes as w

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [("Flags", w.DWORD), ("Type", w.DWORD), ("TargetName", w.LPWSTR), ("Comment", w.LPWSTR),
                        ("LastWritten", w.FILETIME), ("CredentialBlobSize", w.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
                        ("Persist", w.DWORD), ("AttributeCount", w.DWORD), ("Attributes", ctypes.c_void_p),
                        ("TargetAlias", w.LPWSTR), ("UserName", w.LPWSTR)]
        a = ctypes.WinDLL("advapi32", use_last_error=True)
        a.CredWriteW.argtypes, a.CredWriteW.restype = [ctypes.POINTER(CREDENTIAL), w.DWORD], w.BOOL
        a.CredReadW.argtypes, a.CredReadW.restype = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIAL))], w.BOOL
        a.CredDeleteW.argtypes, a.CredDeleteW.restype = [w.LPCWSTR, w.DWORD, w.DWORD], w.BOOL
        a.CredFree.argtypes = [ctypes.c_void_p]
        a.CREDENTIAL = CREDENTIAL
        _advapi = a
    return _advapi


def _target(name, part=0):
    return f"Amadeus/{name}" + (f"#{part}" if part else "")


def _win_write(target, data):
    a = _win()
    blob = ctypes.create_string_buffer(data, len(data))
    cred = a.CREDENTIAL(Type=CRED_TYPE_GENERIC, TargetName=target, CredentialBlobSize=len(data),
                        CredentialBlob=ctypes.cast(blob, ctypes.POINTER(ctypes.c_char)), Persist=CRED_PERSIST_LOCAL_MACHINE,
                        UserName="Amadeus")
    if not a.CredWriteW(ctypes.byref(cred), 0):
        raise Unavailable(f"The Credential Manager refused to keep a login (error {ctypes.get_last_error()}).")


def _win_read(target):
    a = _win()
    p = ctypes.POINTER(a.CREDENTIAL)()
    if not a.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
        if ctypes.get_last_error() == ERROR_NOT_FOUND:
            return None
        raise Unavailable(f"The Credential Manager refused to read a login (error {ctypes.get_last_error()}).")
    try:
        return ctypes.string_at(p.contents.CredentialBlob, p.contents.CredentialBlobSize)
    finally:
        a.CredFree(p)


def _win_delete(name):
    with _lock:
        part = 0
        while _win().CredDeleteW(_target(name, part), CRED_TYPE_GENERIC, 0) or part == 0:
            part += 1
            if part > 64:
                break


def _win_put(name, value):
    data = str(value).encode()
    parts = [data[i:i + WIN_PART] for i in range(0, len(data), WIN_PART)] or [b""]
    with _lock:
        _win_write(_target(name), str(len(parts)).encode() + b"\n" + parts[0])  # the first part says how many there are
        for i, chunk in enumerate(parts[1:], 1):
            _win_write(_target(name, i), chunk)
        i = len(parts)
        while _win().CredDeleteW(_target(name, i), CRED_TYPE_GENERIC, 0):  # leftovers of a longer earlier value
            i += 1


def _win_get(name):
    with _lock:
        first = _win_read(_target(name))
        if first is None:
            return None
        count, _, data = first.partition(b"\n")
        for i in range(1, int(count or 1)):
            data += _win_read(_target(name, i)) or b""
        return data.decode()
