"""Logins Amadeus keeps for you (mail passwords and sign-in tokens), in the system's own safe place.

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
    """True where the system's own store is used (a Mac)."""
    return system.MAC


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
    with _lock:
        item, value = _find(name)
        if item is not None:
            _lib().CFRelease(item)
        return value


def delete(name):
    if not native():
        raise Unavailable("No system keychain here.")
    with _lock:
        item, _ = _find(name)
        if item is None:
            return
        try:
            _check(_lib().SecKeychainItemDelete(item), "remove a login")
        finally:
            _lib().CFRelease(item)
