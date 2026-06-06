#!/bin/bash

# 에러 발생 시 스크립트 중단
set -e

# 이미지 이름 및 태그 설정
IMAGE_NAME="news-summary-backend"
TAG="latest"
FULL_IMAGE_NAME="${IMAGE_NAME}:${TAG}"

echo "=========================================="
echo "🐳 Docker Image Build: ${FULL_IMAGE_NAME}"
echo "=========================================="

# Docker 이미지 빌드 실행
docker build -t "${FULL_IMAGE_NAME}" .

echo ""
echo "✅ 빌드가 완료되었습니다: ${FULL_IMAGE_NAME}"
echo "=========================================="
echo "💡 아래 명령어로 컨테이너를 실행할 수 있습니다:"
echo "   docker run -it --rm -p 8000:8000 --name ${IMAGE_NAME} --env-file .env ${FULL_IMAGE_NAME}"
echo "=========================================="
