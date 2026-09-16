import shutil
import subprocess
from pathlib import Path


def convert(path: Path) -> Path:
    executable = shutil.which("soffice")
    if not executable:
        candidate = Path("C:/Program Files/LibreOffice/program/soffice.exe")
        executable = str(candidate) if candidate.exists() else None
    if not executable:
        raise ValueError("Legacy Office files need LibreOffice. Alternatively save as DOCX, PPTX, or XLSX.")
    extension = {".doc": "docx", ".ppt": "pptx", ".xls": "xlsx"}[path.suffix.lower()]
    subprocess.run([executable, "--headless", "--convert-to", extension,
                    "--outdir", str(path.parent), str(path)], check=True, timeout=120,
                   capture_output=True)
    converted = path.with_suffix("." + extension)
    if not converted.exists():
        raise ValueError("LibreOffice could not convert this file.")
    return converted
