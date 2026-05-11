import tkinter as tk
from tkinter import filedialog, messagebox
import subprocess
import os
import sys
import shutil
import random
import string
from datetime import datetime, timedelta, timezone

# Исправленные импорты для работы с сертификатами
try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.serialization import pkcs12
except ImportError:
    print("Ошибка: pip install cryptography")

def get_dynamic_paths(work_dir):
    """Формирует абсолютные пути для текущей сессии сборки"""
    return {
        "pfx": os.path.abspath(os.path.join(work_dir, "session_cert.pfx")),
        "temp_py": os.path.abspath(os.path.join(work_dir, "temp_build_source.py")),
        "spec": os.path.abspath(os.path.join(work_dir, "FinalApp.spec")),
        "build": os.path.abspath(os.path.join(work_dir, "build")),
        "dist": os.path.abspath(os.path.join(work_dir, "dist")),
        "exe": os.path.abspath(os.path.join(work_dir, "dist", "FinalApp.exe"))
    }

def generate_pfx_dynamic(pfx_path, password):
    """Генерирует уникальный PFX сертификат (SHA-512) на 50 лет"""
    key = rsa.generate_private_key(public_exponent=65537, key_size=4096, backend=default_backend())
    rand_org = "Dev-Node-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, rand_org),
        x509.NameAttribute(NameOID.COMMON_NAME, u"Verified Asset"),
    ])

    now = datetime.now(timezone.utc)
    expiry = now + timedelta(days=18250)

    cert = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(
        key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(
        now).not_valid_after(expiry).sign(key, hashes.SHA512(), default_backend())

    pfx_data = pkcs12.serialize_key_and_certificates(
        name=b"Signature", key=key, cert=cert, cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(password.encode())
    )
    with open(pfx_path, "wb") as f:
        f.write(pfx_data)

def sign_exe_pro(exe_path, pfx_path, password):
    """Подписывает готовый EXE через SignTool"""
    possible_tools = [
        "signtool.exe",
        r"C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64\signtool.exe",
        r"C:\Program Files (x86)\Windows Kits\10\bin\10.0.19041.0\x64\signtool.exe",
    ]
    tool = "signtool"
    for p in possible_tools:
        if os.path.exists(p):
            tool = f'"{p}"'
            break

    cmd = f'{tool} sign /f "{pfx_path}" /p {password} /fd SHA512 /v "{exe_path}"'
    try:
        subprocess.run(cmd, shell=True, check=True, capture_output=True, creationflags=0x08000000)
        return True
    except:
        return False

def full_cleanup(paths, clean_dist=False):
    targets = [paths["build"], paths["temp_py"], paths["spec"], paths["pfx"]]
    if clean_dist: targets.append(paths["dist"])
    for path in targets:
        if os.path.exists(path):
            try:
                if os.path.isdir(path): shutil.rmtree(path, ignore_errors=True)
                else: os.remove(path)
            except: pass

def start_compilation():
    file_path = filedialog.askopenfilename(title="Выбор скрипта", filetypes=[("Python files", "*.py")])
    if not file_path: return

    work_dir = os.path.dirname(file_path)
    paths = get_dynamic_paths(work_dir)
    full_cleanup(paths, clean_dist=True)

    pfx_password = "Pass" + ''.join(random.choices(string.digits, k=6))
    try:
        generate_pfx_dynamic(paths["pfx"], pfx_password)
    except Exception as e:
        messagebox.showerror("Крипто-ошибка", str(e)); return

    # 3. ПОДГОТОВКА КОДА + ИСПРАВЛЕНИЕ 'flush' AttributeError
    try:
        with open(file_path, "r", encoding="utf-8") as f: original_code = f.read()
        
        # Этот блок имитирует консоль для GUI приложений, предотвращая ошибку NoneType.flush
        fix_output_logic = """
import sys, os
if sys.stdout is None or sys.stdout.__class__.__name__ == 'NoneType':
    class DummyStream:
        def write(self, x): pass
        def flush(self): pass
    sys.stdout = DummyStream()
    sys.stderr = DummyStream()
"""
        junk = f"\n# BuildID: {os.urandom(8).hex()}\n"
        for i in range(15):
            junk += f"v_{i} = '{os.urandom(8).hex()}'\n"
        
        with open(paths["temp_py"], "w", encoding="utf-8") as f:
            f.write(fix_output_logic + junk + "\n" + original_code)
    except Exception as e:
        messagebox.showerror("Ошибка записи", str(e)); return

    # 4. КОМПИЛЯЦИЯ
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile", "--clean", "--noconsole",
        "--name", "FinalApp", paths["temp_py"]
    ]

    try:
        messagebox.showinfo("Сборка", "Начинаем компиляцию и подпись...")
        proc = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True, encoding='utf-8', creationflags=0x08000000)
        
        if proc.returncode == 0:
            signed = sign_exe_pro(paths["exe"], paths["pfx"], pfx_password)
            full_cleanup(paths, clean_dist=False)
            msg = "Успешно!" + ("\nПодписано SHA-512." if signed else "\nSignTool не найден.")
            messagebox.showinfo("Итог", msg)
            os.startfile(paths["dist"])
        else:
            messagebox.showerror("Ошибка сборки", proc.stderr)
    except Exception as e:
        messagebox.showerror("Критический сбой", str(e))

# UI
root = tk.Tk()
root.title("Compiler PRO 2026")
root.geometry("350x200")
tk.Label(root, text="Dynamic Signer & Fixer", font=("Arial", 10, "bold")).pack(pady=10)
tk.Button(root, text="ВЫБРАТЬ .PY И СОБРАТЬ", command=start_compilation, 
          bg="#1e1e1e", fg="white", padx=20, pady=10).pack(pady=20)
root.mainloop()
