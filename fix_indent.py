import os

def fix_indentation(directory):
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                new_content = content
                
                # Replace the unindented block with an indented one
                bad_block1 = """try:
    import sys
get_db = sys.modules["__main__"].get_db
release_db = sys.modules["__main__"].release_db
except ImportError:"""
                
                good_block1 = """try:
    import sys
    get_db = sys.modules["__main__"].get_db
    release_db = sys.modules["__main__"].release_db
except ImportError:"""

                bad_block2 = """    except ImportError:
        import sys
get_db = sys.modules["__main__"].get_db
release_db = sys.modules["__main__"].release_db
    except ImportError:"""

                good_block2 = """    except ImportError:
        import sys
        get_db = sys.modules["__main__"].get_db
        release_db = sys.modules["__main__"].release_db
    except ImportError:"""

                # Since my previous replacement was a simple string replacement, 
                # let's just do a smarter regex replacement or simply replace the specific wrong lines.
                
                import re
                
                # Replace the exact bad text injected
                # Wait, the previous injection was:
                # 'import sys\nget_db = sys.modules["__main__"].get_db\nrelease_db = sys.modules["__main__"].release_db'
                
                # Let's fix the specific occurrences in the files by replacing:
                # \nget_db = sys.modules["__main__"].get_db
                # \nrelease_db = sys.modules["__main__"].release_db
                # with proper indentation. 
                # Actually, the simplest fix is to just replace the whole try-except import blocks with a safe global import.
                
                # Let's just use regex to find:
                # try:\n    import sys\nget_db...
                
                new_content = re.sub(
                    r'try:\s*import sys\s*get_db = sys\.modules\["__main__"\]\.get_db\s*release_db = sys\.modules\["__main__"\]\.release_db\s*except ImportError:',
                    r'try:\n    import sys\n    get_db = sys.modules["__main__"].get_db\n    release_db = sys.modules["__main__"].release_db\nexcept Exception:',
                    new_content
                )
                
                new_content = re.sub(
                    r'except ImportError:\s*import sys\s*get_db = sys\.modules\["__main__"\]\.get_db\s*release_db = sys\.modules\["__main__"\]\.release_db',
                    r'except Exception:\n    import sys\n    get_db = sys.modules["__main__"].get_db\n    release_db = sys.modules["__main__"].release_db',
                    new_content
                )
                
                new_content = re.sub(
                    r'try:\s*import sys\s*get_db = sys\.modules\["__main__"\]\.get_db\s*except ImportError:',
                    r'try:\n    import sys\n    get_db = sys.modules["__main__"].get_db\nexcept Exception:',
                    new_content
                )
                
                # In reports_router.py:
                new_content = re.sub(
                    r'try:\s*import sys\s*get_db = sys\.modules\["__main__"\]\.get_db\s*release_db = sys\.modules\["__main__"\]\.release_db\s*conn = get_db\(\)',
                    r'try:\n        import sys\n        get_db = sys.modules["__main__"].get_db\n        release_db = sys.modules["__main__"].release_db\n        conn = get_db()',
                    new_content
                )

                if new_content != content:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    print(f"Fixed indentation in {filepath}")

if __name__ == '__main__':
    fix_indentation(r"d:\GBOC-New\GBOC-New\GBOC-Server\modules")
