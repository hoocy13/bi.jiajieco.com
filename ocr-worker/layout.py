"""CPU PP-DocLayoutV3 detection, upstream cropping and reading-order assembly."""
import io
import threading

from PIL import Image

_model = None
_lock = threading.Lock()
ready = threading.Event()


def initialize():
    import numpy as np
    from paddlex import create_model
    global _model
    with _lock:
        if _model is None:
            candidate = create_model('PP-DocLayoutV3', device='cpu', threshold=0.25,
                                     enable_mkldnn=False, cpu_threads=2)
            list(candidate.predict(np.full((512, 512, 3), 255, dtype=np.uint8)))
            _model = candidate
        ready.set()


def recognize(png, infer, max_tokens, cancelled, progress=None):
    if not ready.is_set():
        raise ValueError('版面检测模型尚未就绪，请稍后重试')
    import numpy as np
    from evaluation_pipeline.layout_detect_paddlex import serialize_regions
    from evaluation_pipeline.cropping import crop_region
    from postprocess.region import merge_page_to_markdown
    from postprocess.otsl import convert_otsl_to_html
    with Image.open(io.BytesIO(png)) as source:
        page = source.convert('RGB')
    with _lock:
        detection = list(_model.predict(np.asarray(page)))[0]
    regions = [region for region in serialize_regions(detection, *page.size)
               if region['task_type'] not in {'skip', 'abandon'} and region['score'] >= 0.25]
    if not regions:
        raise ValueError('未检测到可识别区域，请改用整页模式')
    if len(regions) > 100:
        raise ValueError('单页区域超过 100 个，请拆分文档后重试')
    prompts = {'text':'Extract the text in the image.', 'table':'Parse the table in the image into OTSL.',
               'formula':'Identify the formula in the image and represent it using LATEX format.'}
    budgets = {'text':1024, 'table':2048, 'formula':512}
    rows = []
    if progress:
        progress(0, len(regions))
    for index, region in enumerate(regions):
        if cancelled():
            raise ValueError('任务已取消或过期')
        crop = crop_region(page, region['bbox_2d'], polygon=region.get('polygon'))
        output = io.BytesIO()
        crop.save(output, format='PNG')
        kind = region['task_type']
        text = infer(output.getvalue(), prompts.get(kind, prompts['text']), min(max_tokens, budgets.get(kind,1024)))
        if kind == 'table':
            text = convert_otsl_to_html(text)
        rows.append({**region, 'merged':text})
        if progress:
            progress(index + 1, len(regions))
    merged = merge_page_to_markdown(rows)
    if not merged.strip():
        raise ValueError('区域合并结果为空，请尝试整页模式')
    return merged
