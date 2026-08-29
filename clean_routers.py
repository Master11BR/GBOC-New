import os
import re

def fix_all_routers(directory):
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('_router.py'):
                filepath = os.path.join(root, file)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # We need to remove ALL messy try/except blocks related to get_db and release_db
                # and replace them with a clean single block.
                
                # It's easier to find the `logger = logging.getLogger(...)` line, and delete 
                # everything above it up to `# Import database helpers` or `import sys`.
                
                # Let's use a simpler regex: find anything from `try:` up to `logger = logging.getLogger` 
                # that mentions `sys.modules["__main__"]`.
                
                # Since the files are relatively small, I'll use regex to match the broken blocks
                # and replace them with a single clean block.
                
                # Pattern: from the first `try:` that contains `import sys` and `sys.modules` down to `logger = `
                pattern = r'(try:[\s\S]*?)(logger\s*=\s*logging\.getLogger)'
                
                def replacer(match):
                    broken_block = match.group(1)
                    if 'sys.modules["__main__"]' in broken_block or 'get_db' in broken_block:
                        clean_block = """try:
    import sys
    get_db = sys.modules["__main__"].get_db
    release_db = sys.modules["__main__"].release_db
except Exception:
    get_db = None
    release_db = None

"""
                        return clean_block + match.group(2)
                    return match.group(0)
                
                new_content = re.sub(pattern, replacer, content)
                
                if new_content != content:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    print(f"Fixed {file}")

if __name__ == '__main__':
    fix_all_routers(r"d:\GBOC-New\GBOC-New\GBOC-Server\modules")
