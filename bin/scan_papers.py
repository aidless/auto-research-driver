"""scan_papers.py - one-shot scanner used by the e2e diagnostic above.
Non-destructive: only reads directory listings.
"""
import os
from pathlib import Path

root = Path(r'F:\Research')
print('=== F:\\Research 顶级条目(挑出像 paper 工程的) ===')
candidates = []
for entry in sorted(root.iterdir()):
    if not entry.is_dir():
        continue
    has_state = (entry / '.driver' / 'state.json').exists()
    has_main = (entry / 'main.tex').exists()
    has_refs = (entry / 'refs.bib').exists()
    if has_state or has_main or has_refs:
        candidates.append((entry.name, has_state, has_main, has_refs))
        tag = ('S' if has_state else '-') + ('T' if has_main else '-') + ('R' if has_refs else '-')
        print(f'  [{tag}] {entry.name}')
print()
print(f'paper 候选总数: {len(candidates)}')
print('S=.driver/state.json  T=main.tex  R=refs.bib')