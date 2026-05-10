.PHONY: help check-emojis test
.DEFAULT_GOAL := help

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "};{printf "%-20s %s\n", $$1, $$2}'

check-emojis:  ## Run emoji regression guard on prompt, schema, and reports
	python3 scripts/check_no_emojis_in_reports.py

test:  ## Run emoji guard unit tests
	.venv/bin/python -m pytest tests/unit/test_check_no_emojis_in_reports.py -v
