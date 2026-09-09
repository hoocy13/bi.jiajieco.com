from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


BROWSER_PATHS = (
    Path("/usr/bin/chromium"),
    Path("/usr/bin/chromium-browser"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
)


PDF_PRINT_OVERRIDE = """
<style data-monthly-report-pdf="true">
@media print {
  #data-analytics-portable-fallback { display: none !important; }
  #data-analytics-portable-reader {
    display: block !important;
    position: static !important;
    visibility: visible !important;
    width: 100% !important;
    pointer-events: auto !important;
  }
  .portable-inline-source,
  .portable-sources,
  .portable-chart-data,
  .analytics-top-bar-freshness,
  time { display: none !important; }
}
</style>
"""


def browser_executable() -> Path:
    executable = next((path for path in BROWSER_PATHS if path.exists()), None)
    if executable is None:
        raise RuntimeError("服务器未安装可用于生成PDF的 Edge 或 Chrome")
    return executable


def html_to_pdf(html: str) -> bytes:
    with tempfile.TemporaryDirectory(prefix="monthly-report-pdf-") as directory:
        root = Path(directory).resolve()
        html_path = root / "report.html"
        pdf_path = root / "report.pdf"
        profile_path = root / "browser-profile"
        printable_html = html.replace("</head>", f"{PDF_PRINT_OVERRIDE}</head>", 1)
        html_path.write_text(printable_html, encoding="utf-8")
        subprocess.run(
            [
                str(browser_executable()),
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--no-pdf-header-footer",
                "--run-all-compositor-stages-before-draw",
                "--virtual-time-budget=8000",
                f"--user-data-dir={profile_path}",
                f"--print-to-pdf={pdf_path}",
                html_path.as_uri(),
            ],
            check=True,
            capture_output=True,
            timeout=90,
        )
        if not pdf_path.exists() or pdf_path.stat().st_size < 1000:
            raise RuntimeError("PDF生成失败")
        return pdf_path.read_bytes()
