# Makefile for this Python project.
# Run `make` or `make help` to see all commands.

# ---- Settings (you can override any of these, e.g. `make run FILE=src/app.py`) ----
PYTHON_SYSTEM ?= python3
VENV          ?= data-engineering
REQUIREMENTS  ?= requirements.txt
FILE          ?= main.py

# Paths inside the virtual environment. Using these directly means you do NOT
# need to activate the environment before running `make` commands.
BIN    := $(VENV)/bin
PYTHON := $(BIN)/python
PIP    := $(PYTHON) -m pip

.DEFAULT_GOAL := help
.PHONY: help venv install add remove freeze upgrade outdated list run shell activate \
        test lint format clean clean-venv reset check-venv

help: ## Show this help
	@echo "Usage: make <command> [VAR=value]"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

venv: ## Create the virtual environment (only if it does not exist yet)
	@if [ ! -x "$(PYTHON)" ]; then \
		echo "Creating virtual environment in ./$(VENV) ..."; \
		$(PYTHON_SYSTEM) -m venv $(VENV); \
		$(PIP) install --upgrade pip; \
	else \
		echo "Virtual environment already exists in ./$(VENV)"; \
	fi

check-venv:
	@if [ ! -x "$(PYTHON)" ]; then \
		echo "No virtual environment found. Run 'make venv' first."; exit 1; \
	fi

activate: ## Print the command to activate the environment in your shell
	@echo "Run this in your terminal:"
	@echo ""
	@echo "  source $(VENV)/bin/activate"
	@echo ""
	@echo "To leave it later, run: deactivate"

shell: check-venv ## Open a new shell with the environment already active (type 'exit' to leave)
	@echo "Starting a new shell with ./$(VENV) active. Type 'exit' to leave."
	@. $(BIN)/activate && exec $${SHELL:-/bin/zsh}

# ---------------------------------------------------------------------------
# Packages
# ---------------------------------------------------------------------------

install: venv ## Install all packages listed in requirements.txt
	@touch $(REQUIREMENTS)
	$(PIP) install -r $(REQUIREMENTS)

add: check-venv ## Install a package and save it to requirements.txt (make add PKG=pandas)
	@if [ -z "$(PKG)" ]; then echo "Usage: make add PKG=<package>"; exit 1; fi
	$(PIP) install $(PKG)
	@$(MAKE) --no-print-directory freeze

remove: check-venv ## Uninstall a package and update requirements.txt (make remove PKG=pandas)
	@if [ -z "$(PKG)" ]; then echo "Usage: make remove PKG=<package>"; exit 1; fi
	$(PIP) uninstall -y $(PKG)
	@$(MAKE) --no-print-directory freeze

freeze: check-venv ## Save the currently installed packages to requirements.txt
	$(PIP) freeze > $(REQUIREMENTS)
	@echo "Updated $(REQUIREMENTS)"

upgrade: check-venv ## Upgrade every package in requirements.txt to its latest version
	@if [ ! -s "$(REQUIREMENTS)" ]; then echo "$(REQUIREMENTS) is empty, nothing to upgrade."; exit 0; fi
	$(PIP) install --upgrade pip
	sed -E 's/[[:space:]]*([=<>~!;].*)?$$//' $(REQUIREMENTS) | grep -v '^\s*#' | grep -v '^\s*$$' | \
		xargs $(PIP) install --upgrade
	@$(MAKE) --no-print-directory freeze

outdated: check-venv ## List packages that have newer versions available
	$(PIP) list --outdated

list: check-venv ## List installed packages
	$(PIP) list

# ---------------------------------------------------------------------------
# Running and checking code
# ---------------------------------------------------------------------------

run: check-venv ## Run a Python file (default main.py; make run FILE=src/app.py)
	$(PYTHON) $(FILE)

test: check-venv ## Run tests with pytest (installs pytest if missing)
	@$(PYTHON) -c "import pytest" 2>/dev/null || $(PIP) install pytest
	$(PYTHON) -m pytest

lint: check-venv ## Check code style and common errors with ruff (installs ruff if missing)
	@$(PYTHON) -m ruff --version >/dev/null 2>&1 || $(PIP) install ruff
	$(PYTHON) -m ruff check . --exclude $(VENV)

format: check-venv ## Auto-format code with ruff (installs ruff if missing)
	@$(PYTHON) -m ruff --version >/dev/null 2>&1 || $(PIP) install ruff
	$(PYTHON) -m ruff format . --exclude $(VENV)

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean: ## Delete Python cache files (__pycache__, .pytest_cache, etc.)
	find . -path ./$(VENV) -prune -o -type d \( -name "__pycache__" -o -name ".pytest_cache" -o -name ".ruff_cache" \) -print -exec rm -rf {} +
	find . -path ./$(VENV) -prune -o -type f -name "*.py[co]" -print -delete

clean-venv: ## Delete the virtual environment folder
	rm -rf $(VENV)

reset: clean-venv venv install ## Delete and rebuild the environment from requirements.txt
