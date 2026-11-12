PYTHON ?= python3
CORE := core

.PHONY: help install lint test generate-data validate-data run report benchmark

help:
	@echo "make install        - instala o núcleo (modo editável) + dependências de desenvolvimento"
	@echo "make lint           - ruff check no núcleo"
	@echo "make test           - pytest no núcleo"
	@echo "make generate-data  - gera os CSVs fictícios em data/"
	@echo "make validate-data  - valida os CSVs de data/"
	@echo "make run            - executa as 3 estratégias e mostra a comparação"
	@echo "make report         - gera mapas, gráficos, comparison.csv e report.md em outputs/"
	@echo "make benchmark      - compara as estratégias em 30 datasets gerados"

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e "$(CORE)[dev]"

lint:
	cd $(CORE) && $(PYTHON) -m ruff check .

test:
	cd $(CORE) && $(PYTHON) -m pytest

generate-data:
	$(PYTHON) -m rota_core generate-data

validate-data:
	$(PYTHON) -m rota_core validate-data

run:
	$(PYTHON) -m rota_core run --strategy all

report:
	$(PYTHON) -m rota_core report

benchmark:
	$(PYTHON) -m rota_core benchmark --seeds 30
