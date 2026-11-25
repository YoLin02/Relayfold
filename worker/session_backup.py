import ctypes
import json
import os
from ctypes import wintypes


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_char))]


def crypt(data, binding_id, protect):
    source = ctypes.create_string_buffer(data)
    salt = binding_id.encode("utf-8")
    entropy_buffer = ctypes.create_string_buffer(salt)
    input_blob = Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_char)))
    entropy = Blob(len(salt), ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_char)))
    output = Blob()
    crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
    operation = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p,
                          ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    if not operation(ctypes.byref(input_blob), None, ctypes.byref(entropy), None, None, 1, ctypes.byref(output)):
        raise ctypes.WinError(ctypes.get_last_error())
    free = ctypes.WinDLL("Kernel32.dll").LocalFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        free(output.data)


def save(profile, binding_id, cookies, filename="session.dat"):
    encrypted = crypt(json.dumps(cookies).encode("utf-8"), binding_id, True)
    path = profile / filename
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as stream:
        stream.write(encrypted)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def load(profile, binding_id, filename="session.dat"):
    path = profile / filename
    if not path.exists():
        return []
    return json.loads(crypt(path.read_bytes(), binding_id, False))
