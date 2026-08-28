import sys, os
import traceback

# Ensure project root is on sys.path when running from tools/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app_factory import create_app

app = create_app()
client = app.test_client()
for route in ['/events','/attendance']:
    print('\n===', route)
    try:
        resp = client.get(route)
        print('STATUS', resp.status_code)
        text = resp.get_data(as_text=True)
        print(text[:1200])
    except Exception:
        traceback.print_exc()
