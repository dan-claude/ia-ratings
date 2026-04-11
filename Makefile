.PHONY: dev test

dev:
	PYTHONPATH=. python -m server.app

test:
	PYTHONPATH=. pytest -q
