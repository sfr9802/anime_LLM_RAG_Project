from jinja2 import Environment, FileSystemLoader, TemplateNotFound
from pathlib import Path

# 템플릿 디렉토리 경로 설정
TEMPLATE_DIR = Path(__file__).parent / "templates"

# Jinja2 환경 초기화 (캐싱 포함)
env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=False,  # 일반 텍스트니까 autoescape 꺼둠
    trim_blocks=True,
    lstrip_blocks=True,
)

def render_template(template_name: str, **kwargs) -> str:
    """
    지정된 템플릿 이름과 변수로 프롬프트 문자열을 렌더링합니다.
    
    :param template_name: 템플릿 파일명 (확장자 없이 입력: "rag_prompt")
    :param kwargs: 템플릿에 주입할 변수들
    :return: 렌더링된 문자열
    """
    try:
        template = env.get_template(f"{template_name}.j2")
        return template.render(**kwargs)
    except TemplateNotFound:
        raise FileNotFoundError(f"템플릿 '{template_name}.j2'를 찾을 수 없습니다.")
    except Exception as e:
        raise RuntimeError(f"템플릿 렌더링 중 오류 발생: {str(e)}")
