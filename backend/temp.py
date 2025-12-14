from pathlib import Path
path = Path('app/core/security.py')
text = path.read_text(encoding='utf-8')
text = text.replace('from jos', 'from jos')
