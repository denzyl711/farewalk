.PHONY: install test_unit test_integration test_all

install:
	pip install -e .

test_unit:
	pytest tests/ -v --ignore=tests/integration

test_integration: install
	pytest tests/integration -v

test_all: test_unit test_integration
