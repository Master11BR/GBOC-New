import os

SERVER_PY = r"d:\GBOC-New\GBOC-New\GBOC-Server\gboc_server.py"

def fix_login_redirect():
    with open(SERVER_PY, 'r', encoding='utf-8') as f:
        content = f.read()

    new_content = content.replace('url="/dashboard.html"', 'url="/login.html"')

    if new_content != content:
        with open(SERVER_PY, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("Fixed redirect to login.html")
    else:
        print("Nothing changed.")

if __name__ == '__main__':
    fix_login_redirect()
