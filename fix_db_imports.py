import os
import re

def fix_db_imports(directory):
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                new_content = content
                
                # Replace 'from database import get_db, release_db'
                new_content = new_content.replace(
                    'from database import get_db, release_db',
                    'import sys\nget_db = sys.modules["__main__"].get_db\nrelease_db = sys.modules["__main__"].release_db'
                )
                
                # Also handle 'from database import get_db'
                new_content = new_content.replace(
                    'from database import get_db',
                    'import sys\nget_db = sys.modules["__main__"].get_db'
                )

                if new_content != content:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    print(f"Fixed db imports in {filepath}")

if __name__ == '__main__':
    fix_db_imports(r"d:\GBOC-New\GBOC-New\GBOC-Server\modules")
