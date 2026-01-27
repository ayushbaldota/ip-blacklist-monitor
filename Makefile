.PHONY: help install dev test lint format migrate docker-up docker-down api-key check-now

help:
	@echo "IP Blacklist Monitor - Available commands:"
	@echo ""
	@echo "  install      Install dependencies with Poetry"
	@echo "  dev          Run development server with auto-reload"
	@echo "  test         Run tests with coverage"
	@echo "  lint         Run linters (ruff, mypy)"
	@echo "  format       Format code with black and ruff"
	@echo "  migrate      Run database migrations"
	@echo "  docker-up    Start Docker services"
	@echo "  docker-down  Stop Docker services"
	@echo "  api-key      Create a new API key (usage: make api-key NAME=mykey)"
	@echo "  check-now    Run blacklist check immediately"
	@echo ""

install:
	poetry install

dev:
	poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	poetry run pytest

lint:
	poetry run ruff check .
	poetry run mypy app

format:
	poetry run black .
	poetry run ruff check --fix .

migrate:
	poetry run alembic upgrade head

migrate-create:
	poetry run alembic revision --autogenerate -m "$(MSG)"

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

docker-build:
	docker-compose build

api-key:
	poetry run python scripts/create_api_key.py $(NAME)

check-now:
	poetry run python scripts/run_check_now.py

# Development database setup
db-setup:
	docker-compose up -d db
	@echo "Waiting for database to be ready..."
	@sleep 3
	poetry run alembic upgrade head
	@echo "Database setup complete!"

# Clean up
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
