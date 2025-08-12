# app/prompt/renderer.py
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from functools import lru_cache

TEMPLATE_DIR = Path(__file__).parent / "templates"

@lru_cache(maxsize=1)
def _env():
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape([]),   # 텍스트 프롬프트라 보통 비활성
        undefined=StrictUndefined,          # 누락 변수 바로 실패 → 디버깅 쉬움
        trim_blocks=True,
        lstrip_blocks=True,
    )

def render(name: str, **kwargs) -> str:
    tpl = _env().get_template(name)
    return tpl.render(**kwargs)
