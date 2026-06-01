with open('admin.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'newsTableBody' in line:
        print(f"Line {i+1}: {line.strip()}")
    if '<table' in line:
        print(f"Line {i+1}: {line.strip()}")
