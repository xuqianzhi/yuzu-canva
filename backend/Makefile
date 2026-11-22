.PHONY: help setup build up down logs test lint contract shell clean
.DEFAULT_GOAL := help

help: ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk -F':.*?## ' '{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

setup: ## Create .env from the template and the data folder
	@test -f .env || (cp .env.example .env && echo "created .env -- add your API keys")
	@mkdir -p ../data

build: ## Build the images
	docker compose build api test

up: ## Start the API on http://127.0.0.1:8788 (docs at /docs)
	docker compose up -d api

down: ## Stop the API
	docker compose down

logs: ## Follow the API logs
	docker compose logs -f api

test: ## Run unit tests in Docker
	docker compose run --rm test

lint: ## Run ruff in Docker
	docker compose run --rm test ruff check src tests

contract: ## Regenerate contract/openapi.json and the frontend's TS types
	docker compose run --rm -T test python3 -m canvas_api.export_openapi > ../contract/openapi.json
	cd ../frontend && npm run gen:api

shell: ## Open a shell in the dev image
	docker compose run --rm test bash

clean: ## Remove containers and built images
	docker compose down --rmi local --remove-orphans
