

import base64
import ctypes
import io
import os
import sys
import threading
import time

# ---------- COM initialization (fixes -2147221008) ----------
_ole32 = ctypes.windll.ole32
_COINIT_APARTMENTTHREADED = 0x2
_ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint]
_ole32.CoInitializeEx.restype = ctypes.c_long

def _ensure_com():
    hr = _ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    # S_OK = 0, S_FALSE = 1 (already initialized) are both fine
    if hr not in (0, 1):
        print(f"[SDK] CoInitializeEx returned 0x{hr & 0xffffffff:08X}", flush=True)

# Call once at import time
_ensure_com()

# Process-wide lock so open/scan/close never overlap
_device_lock = threading.RLock()

if getattr(sys, "frozen", False):
    # Running as a bundled PyInstaller executable - DLLs sit next to the .exe
    _DLL_DIR = os.path.dirname(sys.executable)
else:
    # Running as a normal Python script
    _DLL_DIR = os.path.dirname(os.path.abspath(__file__))

_DLL_PATH = os.path.join(_DLL_DIR, "uareu4500.dll")

if not os.path.exists(_DLL_PATH):
    raise FileNotFoundError(
        f"uareu4500.dll not found at {_DLL_PATH}. "
        "Copy uareu4500.dll, dpfpdd.dll, dpfj.dll and dpuareu_jni.dll "
        "into this same folder."
    )

# winmode=0 is required on Windows so the DLL's dependencies (dpfpdd.dll,
# dpfj.dll) are found correctly.
_lib = ctypes.CDLL(_DLL_PATH, winmode=0)

_lib.python_read_fingerprint_and_get_base64_string.restype = ctypes.c_char_p
_lib.python_compare_base64_string_with_finger.argtypes = [ctypes.c_char_p]
_lib.python_compare_base64_string_with_finger.restype = ctypes.c_int

# --- direct dpfj.dll binding, for offline FMD-to-FMD compare -------------
_DPFJ_PATH = os.path.join(_DLL_DIR, "dpfj.dll")
if not os.path.exists(_DPFJ_PATH):
    raise FileNotFoundError(f"dpfj.dll not found at {_DPFJ_PATH}.")

# IMPORTANT: dpfj.h declares its functions as DPAPICALL, which on Windows
# expands to __stdcall - NOT __cdecl. Must load with WinDLL, not CDLL.
_dpfj = ctypes.WinDLL(_DPFJ_PATH)

_DPFJ_SUCCESS = 0
_MATCH_THRESHOLD = 500  # dissimilarity score: 0 = identical, higher = worse. TUNE THIS.

DPFJ_FMD_ANSI_378_2004 = 0x001B0001
DPFJ_FMD_ISO_19794_2_2005 = 0x01010001
_FMD_FORMAT = DPFJ_FMD_ANSI_378_2004

try:
    _dpfj.dpfj_compare.argtypes = [
        ctypes.c_int, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint,
        ctypes.c_int, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint,
        ctypes.POINTER(ctypes.c_uint),
    ]
    _dpfj.dpfj_compare.restype = ctypes.c_int
    _DPFJ_COMPARE_AVAILABLE = True
except AttributeError:
    _DPFJ_COMPARE_AVAILABLE = False


def capture_fingerprint() -> str:
    ptr = _lib.python_read_fingerprint_and_get_base64_string()
    if not ptr:
        raise RuntimeError("Capture failed: no data returned from the reader.")
    combined = ctypes.string_at(ptr).decode("utf-8")
    return combined.split("|", 1)[0]

def capture_fingerprint_with_image(max_retries: int = 2, retry_delay: float = 0.8):
    """
    Open → capture → close in one critical section.
    Retries a couple of times on transient device/COM errors.
    """
    last_err = None
    for attempt in range(1, max_retries + 1):
        with _device_lock:
            try:
                _ensure_com()          # re-ensure on every attempt
                ptr = _lib.python_read_fingerprint_and_get_base64_string()
                if not ptr:
                    raise RuntimeError("Capture failed: DLL returned null pointer")

                combined = ctypes.string_at(ptr).decode("utf-8", errors="replace")
                parts = combined.split("|")
                if len(parts) < 1 or not parts[0]:
                    raise RuntimeError(f"Capture returned empty/invalid data: {combined[:80]!r}")

                template_b64 = parts[0]
                image_data_url = None
                if len(parts) == 4:
                    try:
                        width, height = int(parts[1]), int(parts[2])
                        image_data_url = fid_to_png_data_url(parts[3], width, height)
                    except Exception:
                        pass

                return template_b64, image_data_url

            except OSError as e:
                # access violation, bad handle, etc.
                last_err = e
                print(f"[SDK] OSError on attempt {attempt}: {e}", flush=True)
            except Exception as e:
                last_err = e
                print(f"[SDK] Exception on attempt {attempt}: {e}", flush=True)

        if attempt < max_retries:
            time.sleep(retry_delay)

    raise RuntimeError(f"Fingerprint capture failed after {max_retries} attempts: {last_err}")


def fid_to_png_data_url(fid_b64: str, width: int, height: int):
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError(
            "Pillow is required to convert fingerprint images. "
            "Install it with: pip install Pillow"
        )

    if not width or not height:
        return None

    raw = base64.b64decode(fid_b64)
    if not raw:
        return None

    needed = width * height
    if len(raw) >= needed:
        pixels = raw[len(raw) - needed:]
    else:
        pixels = raw.rjust(needed, b"\x00")

    img = Image.frombytes("L", (width, height), pixels)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{png_b64}"


def describe_template(base64_str: str) -> dict:
    raw_bytes = base64.b64decode(base64_str)
    return {
        "python_type": type(base64_str).__name__,
        "base64_length": len(base64_str),
        "decoded_byte_size": len(raw_bytes),
        "preview_base64": base64_str[:60],
        "preview_bytes_hex": raw_bytes[:16].hex(),
    }


def print_capture_report(base64_str: str, label: str = "") -> None:
    info = describe_template(base64_str)
    prefix = f"[{label}] " if label else ""
    print(f"{prefix}Capture complete:")
    print(f"  Python type        : {info['python_type']}")
    print(f"  Base64 string length: {info['base64_length']} characters")
    print(f"  Decoded byte size   : {info['decoded_byte_size']} bytes")
    print(f"  Base64 preview      : {info['preview_base64']}...")
    print(f"  Raw bytes preview   : {info['preview_bytes_hex']}")


def verify_fingerprint(stored_base64: str) -> bool:
    if not stored_base64:
        raise ValueError("stored_base64 is empty - nothing to compare against.")
    result = _lib.python_compare_base64_string_with_finger(
        stored_base64.encode("utf-8")
    )
    return bool(result)


def match_two_templates(template_a_b64: str, template_b_b64: str) -> bool:
    """
    Compares two ALREADY-CAPTURED base64 templates using dpfj_compare()
    directly - no reader access needed. This is what powers 1:N verify:
    the local agent fetches every stored template from the remote server,
    then loops this function locally against each one.
    """
    if not _DPFJ_COMPARE_AVAILABLE:
        raise RuntimeError(
            "dpfj.dll does not export 'dpfj_compare' under that exact name "
            "on this build. Check the real symbol name/casing with dumpbin."
        )

    fmd1 = base64.b64decode(template_a_b64)
    fmd2 = base64.b64decode(template_b_b64)
    score = ctypes.c_uint(0)

    result = _dpfj.dpfj_compare(
        _FMD_FORMAT, fmd1, len(fmd1), 0,
        _FMD_FORMAT, fmd2, len(fmd2), 0,
        ctypes.byref(score),
    )

    if result != _DPFJ_SUCCESS:
        raise RuntimeError(
            f"dpfj_compare failed (code {hex(result & 0xffffffff)}) - "
            "likely wrong FMD format constant. Try switching _FMD_FORMAT "
            "from ANSI_378_2004 to ISO_19794_2_2005."
        )

    return score.value <= _MATCH_THRESHOLD
