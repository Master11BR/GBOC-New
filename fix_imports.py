import os

def fix_imports(directory):
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                new_content = content
                new_content = new_content.replace('from GBOC_Server.database import', 'from database import')
                new_content = new_content.replace('from gboc_server import get_db', 'from database import get_db')
                new_content = new_content.replace('from gboc_server import manager', 'from __main__ import manager')
                
                # If the main script is run directly, `manager` is in `__main__` or we can just import from gboc_server
                # But gboc_server is the script being run. `import gboc_server` might cause circular import.
                # Let's replace 'from gboc_server import manager' with 'import sys; manager = sys.modules["__main__"].manager'
                new_content = new_content.replace('from gboc_server import manager', 'import sys\n        manager = sys.modules["__main__"].manager')
                
                if new_content != content:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    print(f"Fixed imports in {filepath}")

if __name__ == '__main__':
    fix_imports(r"d:\GBOC-New\GBOC-New\GBOC-Server\modules")
