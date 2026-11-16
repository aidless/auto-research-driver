# Offline evidence. No sister repos and no network.
# checks.yml and pr-checks.yml call this same target.
.PHONY: check eval

check:
	python3 -m pytest tests -q
	python3 evidence/verify_trace.py
	python3 eval/run_cases.py

eval:
	python3 eval/run_cases.py
