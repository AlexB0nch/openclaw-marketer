.PHONY: up down test lint deploy openclaw-install

up:
	docker compose up -d --build

down:
	docker compose down

test:
	pytest tests/ -v --asyncio-mode=auto

lint:
	ruff check .
	black --check .

deploy:
	@echo "Deploying to VPS..."
	ssh -o StrictHostKeyChecking=no $${VPS_USER}@$${VPS_HOST} \
		"cd $${VPS_PATH} && git pull origin main && docker compose pull && docker compose up -d --build && docker compose ps"

openclaw-install:
	npm install -g openclaw@latest
	openclaw init --config openclaw.json --port $${OPENCLAW_PORT:-3000}
