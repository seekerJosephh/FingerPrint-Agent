# Fingerprint Agent — build instructions

## 1. Copy in the 4 DLLs (not included here — copy from your existing project)

From your current `FingerPrintProject` folder, copy these 4 files into this
`fingerprint-agent` folder, alongside `main.py`:

```
uareu4500.dll
dpfj.dll
dpfpdd.dll
dpuareu_jni.dll
```

Also copy `libwinpthread-1.dll` if your current project has one sitting
next to the other DLLs — it's a runtime dependency some builds of
`dpfj.dll` need.

## 2. Edit the two config values before building

In `main.py`:
```python
FRONTEND_URL = "https://app.yourdomain.com"   # your hosted React app
```

In `local_agent.py`:
```python
REMOTE_API = "https://172.30.243.253:2083"     # your hosted backend
```

(Or leave the defaults and set `FP_FRONTEND_URL` / `FP_REMOTE_API`
environment variables instead — no rebuild needed if you do it that way.)

## 3. Install dependencies

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 4. Build with PyInstaller

```powershell
pyinstaller --name FingerprintAgent --onedir ^
  --add-binary "uareu4500.dll;." ^
  --add-binary "dpfj.dll;." ^
  --add-binary "dpfpdd.dll;." ^
  --add-binary "dpuareu_jni.dll;." ^
  main.py
```

Use `--onedir`, not `--onefile` — the DLL loading code needs a stable
folder path on disk, which `--onefile`'s self-extracting temp folder
doesn't reliably give it.

## 5. Result

```
dist/FingerprintAgent/
├── FingerprintAgent.exe
├── uareu4500.dll
├── dpfj.dll
├── dpfpdd.dll
├── dpuareu_jni.dll
└── (bundled Python runtime)
```

Zip the whole `dist/FingerprintAgent` folder — that's the distributable.
Copy it to any reception PC with a reader attached, no Python install
needed on the target machine. Double-click `FingerprintAgent.exe` to run.

## 6. Optional — run silently in the background (no console window)

Add `--windowed` to the PyInstaller command, and consider adding a system
tray icon (`pystray` + `pillow`, already commonly discussed) so staff have
a visible "Quit" option instead of a bare hidden process.
