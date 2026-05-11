import tkinter as tk
from tkinter import filedialog, messagebox
import subprocess
import os
import sys
import shutil
import random
import string
import struct
from datetime import datetime, timedelta, timezone

# Библиотеки для автономной работы и подписи
try:
    import pefile
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.serialization import pkcs12
except ImportError:
    print("Ошибка: выполните 'pip install cryptography pefile'")

def get_dynamic_paths(work_dir, exe_name="FinalApp"):
    """Формирует абсолютные пути относительно папки скрипта"""
    return {
        "work_dir": work_dir,
        "pfx": os.path.join(work_dir, "internal_session.pfx"),
        "temp_py": os.path.join(work_dir, "temp_build_source.py"),
        "spec": os.path.join(work_dir, f"{exe_name}.spec"),
        "build": os.path.join(work_dir, "build"),
        "dist": os.path.join(work_dir, "dist"),
        "exe": os.path.join(work_dir, "dist", f"{exe_name}.exe"),
        "exe_name": f"{exe_name}.exe"
    }

def internal_pe_signer_sha512(exe_path, pfx_path, password):
    """Автономная подпись PE-файла (SHA-512)"""
    try:
        # Загрузка ключа и сертификата
        with open(pfx_path, "rb") as f:
            p_key, cert, _ = pkcs12.load_key_and_certificates(f.read(), password.encode())

        pe = pefile.PE(exe_path)
        
        # Получаем данные файла для подписи
        # В pefile метод get_authenticode_hash() возвращает хеш (обычно sha256 или sha1)
        # Для ручного SHA512 мы подписываем данные напрямую через cryptography
        raw_data = pe.get_data()
        digest = hashes.Hash(hashes.SHA512(), backend=default_backend())
        digest.update(raw_data)
        file_hash = digest.finalize()

        # Создаем подпись
        signature = p_key.sign(
            file_hash,
            padding.PKCS1v15(),
            hashes.SHA512()
        )

        cert_der = cert.public_bytes(serialization.Encoding.DER)
        
        # Структура WIN_CERTIFICATE (Length, Revision, CertificateType)
        # Revision 0x0200 = WIN_CERT_REVISION_2_0, Type 0x0002 = PKCS_SIGNED_DATA (имитация)
        header = struct.pack("<IHH", 8 + len(cert_der) + len(signature), 0x0200, 0x0002)
        full_blob = header + cert_der + signature
        
        # Выравнивание по 8 байт (требование PE спецификации)
        padding_len = (8 - (len(full_blob) % 8)) % 8
        full_blob += b"\x00" * padding_len

        # Читаем исходный файл целиком
        with open(exe_path, "rb") as f:
            raw_exe = bytearray(f.read())

        sig_offset = len(raw_exe)
        
        # Обновляем таблицу директорий безопасности в заголовке
        security_entry = pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_SECURITY']
        pe.OPTIONAL_HEADER.DATA_DIRECTORY[security_entry].VirtualAddress = sig_offset
        pe.OPTIONAL_HEADER.DATA_DIRECTORY[security_entry].Size = len(full_blob)

        # Пересчитываем чексумму и сохраняем изменения заголовка
        pe.OPTIONAL_HEADER.CheckSum = pe.generate_checksum()
        pe.write(exe_path)
        pe.close()

        # Дописываем саму подпись в конец файла физически
        with open(exe_path, "ab") as f:
            f.write(full_blob)

        return True
    except Exception as e:
        print(f"Ошибка подписи: {e}")
        return False

def generate_pfx_dynamic(pfx_path, password):
    """Генерация самоподписанного сертификата SHA-512 на 50 лет"""
    key = rsa.generate_private_key(65537, 4096, default_backend())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, u"Standalone Builder 2026")])
    now = datetime.now(timezone.utc)
    cert = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(
        key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(
        now).not_valid_after(now + timedelta(days=18250)).sign(key, hashes.SHA512(), default_backend())

    pfx_data = pkcs12.serialize_key_and_certificates(
        name=b"Sign", key=key, cert=cert, cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(password.encode())
    )
    with open(pfx_path, "wb") as f:
        f.write(pfx_data)

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
    source_file = filedialog.askopenfilename(title="Выбор скрипта", filetypes=[("Python files", "*.py")])
    if not source_file: return

    target_name = "FinalApp"
    work_dir = os.path.dirname(os.path.abspath(source_file))
    paths = get_dynamic_paths(work_dir, target_name)
    
    # Завершение процесса, если запущен
    try:
        subprocess.run(["taskkill", "/F", "/IM", paths["exe_name"], "/T"], 
                       capture_output=True, creationflags=0x08000000)
    except:
        pass

    full_cleanup(paths, clean_dist=True)

    pfx_pass = "".join(random.choices(string.ascii_letters + string.digits, k=12))
    
    try:
        generate_pfx_dynamic(paths["pfx"], pfx_pass)
        
        with open(source_file, "r", encoding="utf-8") as f: 
            original_code = f.read()

        fix_logic = "import sys\nclass D: write=flush=lambda *a,**k:None\nsys.stdout=sys.stderr=D()\n"
        junk = f"# BuildID: {os.urandom(8).hex()}\n"
        
        with open(paths["temp_py"], "w", encoding="utf-8") as f:
            f.write(fix_logic + junk + original_code)

        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--onefile", "--clean", "--noconsole",
            "--distpath", paths["dist"],
            "--workpath", paths["build"],
            "--specpath", paths["work_dir"],
            "--name", target_name, 
            paths["temp_py"]
        ]

        messagebox.showinfo("Инфо", f"Старая копия {paths['exe_name']} закрыта. Начинаем сборку...")
        
        proc = subprocess.run(cmd, cwd=work_dir, capture_output=True, creationflags=0x08000000)

        if proc.returncode == 0:
            signed = internal_pe_signer_sha512(paths["exe"], paths["pfx"], pfx_pass)
            full_cleanup(paths, clean_dist=False)
            
            status = "Сборка завершена!" + ("\nФайл подписан SHA-512." if signed else "\nОшибка подписи.")
            messagebox.showinfo("Готово", status)
            os.startfile(paths["dist"])
        else:
            messagebox.showerror("Ошибка PyInstaller", proc.stderr.decode('utf-8', errors='ignore'))

    except Exception as e:
        messagebox.showerror("Критический сбой", str(e))

# Главное окно
root = tk.Tk()
root.title("Compiler & Auto-Killer 2026")
root.geometry("400x200")

tk.Label(root, text="Standalone Py Compiler", font=("Arial", 12, "bold"), pady=10).pack()
tk.Label(root, text="Авто-завершение процесса включено", fg="green").pack()

tk.Button(root, text="ВЫБРАТЬ .PY И СОБРАТЬ", command=start_compilation,
          bg="#27ae60", fg="white", font=("Arial", 10, "bold"), padx=20, pady=15).pack(pady=20)

root.mainloop()
