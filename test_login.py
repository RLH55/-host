import sys
import os
import hashlib
from datetime import datetime

# إضافة المسار الحالي للاستيراد
sys.path.append(os.getcwd())

# محاكاة لبعض وظائف app.py
ADMIN_USERNAME = "OMAR_ADMIN"
ADMIN_PASSWORD = "OMAR_2026_BRO"

def test_admin_login(input_user, input_pass):
    print(f"Testing Login for: '{input_user}' / '{input_pass}'")
    
    # الكود المأخوذ من app.py (النسخة المعدلة)
    username = input_user.strip()
    password = input_pass.strip()
    
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        print("✅ SUCCESS: Admin Login Matches!")
        return True
    else:
        print(f"❌ FAILED: Login Mismatch.")
        print(f"Expected: '{ADMIN_USERNAME}' / '{ADMIN_PASSWORD}'")
        print(f"Received: '{username}' / '{password}'")
        return False

# اختبار حالات مختلفة
print("--- Case 1: Exact Match ---")
test_admin_login("OMAR_ADMIN", "OMAR_2026_BRO")

print("\n--- Case 2: With Spaces ---")
test_admin_login(" OMAR_ADMIN ", " OMAR_2026_BRO ")

print("\n--- Case 3: Lowercase (Should Fail) ---")
test_admin_login("omar_admin", "omar_2026_bro")
