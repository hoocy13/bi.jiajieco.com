"""Outbound-only OCR worker. No HTTP listener and no exposed container ports."""
import base64
import io
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request

from PIL import Image, ImageOps
import pypdfium2 as pdfium
from postprocess.document import finalize_document
import layout

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
for noisy_logger in ('httpx', 'httpcore', 'huggingface_hub', 'modelscope'):
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)
BI_URL = os.environ["OCR_BI_URL"].rstrip("/")
KEY = os.environ["OCR_WORKER_KEY"]
OLLAMA = os.environ.get("OCR_OLLAMA_URL", "http://host.docker.internal:11434").rstrip("/")
MODEL = os.environ.get("OCR_MODEL", "longwayxu/xiaomi-ocr-0:bf16")
if not KEY or len(KEY) < 32:
    raise RuntimeError("OCR_WORKER_KEY must contain at least 32 characters")
if not BI_URL.startswith("https://") and not os.environ.get("OCR_ALLOW_LOCAL_HTTP") == "1":
    raise RuntimeError("Use HTTPS for OCR_BI_URL; allow HTTP only for a local test")

DOC_PROMPT = (
    "Extract all information from the main body of the document image and represent it in markdown format, "
    "ignoring headers and footers. Tables should be expressed in OTSL format, formulas in the document should "
    "be represented using LATEX format, and the parsing should be organized according to the reading order."
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    # Never forward the dedicated worker key to a redirected host.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))


def request(url, payload=None, headers=None, timeout=30):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})})
    with OPENER.open(req, timeout=timeout) as response:
        return response.read()


def api(path, payload=None, lease=None, binary=False):
    headers = {"X-OCR-Worker-Key": KEY}
    if lease:
        headers["X-OCR-Lease"] = lease
    raw = request(BI_URL + "/api/v1/tools/ocr" + path, payload, headers)
    return raw if binary else json.loads(raw)["data"]


def model_ready():
    try:
        models = json.loads(request(OLLAMA + "/api/tags", timeout=10)).get("models", [])
        return any(item.get("name") == MODEL for item in models)
    except Exception:
        return False


def image_png(raw):
    with Image.open(io.BytesIO(raw)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((2048, 2048))
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()


def infer(png, prompt, max_tokens=4096):
    payload = {"model": MODEL, "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}},
        {"type": "text", "text": prompt}]}], "temperature": 0, "max_tokens": max_tokens, "stream": False,
        "chat_template_kwargs": {"enable_thinking": False}}
    data = json.loads(request(OLLAMA + "/v1/chat/completions", payload, timeout=300))
    choice = data["choices"][0]
    text = choice["message"].get("content", "").strip()
    if not text or choice.get("finish_reason") == "length":
        raise ValueError("识别结果为空或内容过长，请拆分文档后重试")
    return text


def process(job):
    path, lease = "/worker/jobs/" + job["id"], job["lease"]
    stop, lost = threading.Event(), threading.Event()
    progress = {"pages_done": 0, "pages_total": 0, "regions_done":0, "regions_total":0}

    def pulse():
        while not stop.wait(20):
            try:
                api(path + "/heartbeat", dict(progress), lease)
            except urllib.error.HTTPError as exc:
                if exc.code == 409:
                    lost.set()
                    return
                logging.warning("heartbeat HTTP %s", exc.code)
            except Exception:
                logging.warning("heartbeat connection unavailable")

    heartbeat = threading.Thread(target=pulse, daemon=True)
    heartbeat.start()
    try:
        raw = api(path + "/file", lease=lease, binary=True)
        if job["task"] == "kie":
            names = [part.strip() for part in job["fields"].replace("，", ",").replace("\n", ",").split(",") if part.strip()]
            prompt = "Extract the key information from the document image as a JSON object. Return JSON only; use an empty string for missing values."
            if names:
                prompt += " Use this schema: " + json.dumps({name: "" for name in names}, ensure_ascii=False)
        elif job["task"] == "vqa":
            prompt = job["question"] + "\nAnswer the question using a single word or phrase."
        else:
            prompt = job["prompt"] or DOC_PROMPT

        outputs = []

        def one_page(png):
            if lost.is_set():
                raise ValueError("任务已取消或过期")
            if job.get("mode") == "region":
                def region_progress(done, total):
                    progress.update(regions_done=done, regions_total=total)
                    api(path + "/heartbeat", dict(progress), lease)
                text = layout.recognize(png, infer, job.get("max_tokens",4096), lost.is_set, region_progress)
            else:
                text = infer(png, prompt, job.get("max_tokens", 4096))
            if job["task"] == "document":
                text = finalize_document(text)
            elif job["task"] == "kie":
                try:
                    start, end = text.index("{"), text.rindex("}") + 1
                    parsed = json.loads(text[start:end])
                    if not isinstance(parsed, dict):
                        raise ValueError()
                    text = json.dumps({name: parsed.get(name, "") for name in names} if names else parsed, ensure_ascii=False, indent=2)
                except (ValueError, json.JSONDecodeError):
                    raise ValueError("模型未返回有效字段 JSON，请调整字段后重试")
            outputs.append(text)
            progress["pages_done"] += 1
            api(path + "/heartbeat", dict(progress), lease)

        if job["mime"] == "application/pdf":
            with pdfium.PdfDocument(raw) as document:
                count = len(document)
                if not 1 <= count <= 20:
                    raise ValueError("PDF 最多支持 20 页，请拆分后上传")
                progress["pages_total"] = count
                for index in range(count):
                    page = document[index]
                    try:
                        width, height = page.get_size()
                        bitmap = page.render(scale=min(2, 2048 / max(width, height)))
                        try:
                            buffer = io.BytesIO()
                            bitmap.to_pil().save(buffer, format="PNG")
                            one_page(image_png(buffer.getvalue()))
                        finally:
                            bitmap.close()
                    finally:
                        page.close()
        else:
            progress["pages_total"] = 1
            one_page(image_png(raw))
        text = "\n\n---\n\n".join(f"<!-- page {i + 1} -->\n\n{part}" for i, part in enumerate(outputs)) if len(outputs) > 1 else outputs[0]
        api(path + "/finish", {"result": text}, lease)
        logging.info("job completed pages=%s", progress["pages_total"])
    except Exception as exc:
        # Only our own validation errors are safe to return. Transport errors can
        # include endpoint details and must never be exposed as document results.
        message = str(exc) if isinstance(exc, ValueError) else "识别失败，请检查文档或稍后重试"
        logging.warning("job failed type=%s", type(exc).__name__)
        try:
            api(path + "/finish", {"error": message[:255]}, lease)
        except Exception:
            logging.warning("result delivery unavailable; lease will expire")
    finally:
        stop.set()
        heartbeat.join(timeout=35)


def main():
    def initialize_layout():
        while not layout.ready.is_set():
            try:
                layout.initialize()
                logging.info("CPU layout detection ready")
            except Exception as exc:
                logging.warning("layout unavailable type=%s", type(exc).__name__)
                time.sleep(60)
    threading.Thread(target=initialize_layout, daemon=True).start()
    while True:
        try:
            job = api("/worker/poll", {"ready": model_ready(), "region_ready":layout.ready.is_set()})
            if job:
                process(job)
                continue
        except Exception as exc:
            logging.warning("poll unavailable type=%s", type(exc).__name__)
        time.sleep(10)


if __name__ == "__main__":
    main()
