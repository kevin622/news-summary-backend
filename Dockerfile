# 2026년 기준 가장 가볍고 안전한 uv 지원 파이썬 이미지 활용
FROM ghcr.io/astral-sh/uv:python3.12-alpine

WORKDIR /app

# 프로젝트 파일 복사 및 싱크
COPY . /app
RUN uv sync --frozen --no-cache

# FastAPI 포트 개방 및 실행
EXPOSE 8000
CMD ["uv", "run", "fastapi", "run", "main.py", "--host", "0.0.0.0", "--port", "8000"]