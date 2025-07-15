import requests
import json
import re

def match_email_pattern(email_to_check, pattern):
    """
    Check if an email matches a pattern where * represents hidden characters.
    Example: pattern "c*****r@b*******h.net" should match "caryn@barkh.net"
    """
    # Escape regex special characters in the pattern
    pattern_regex = re.escape(pattern)
    # Replace escaped asterisks with . (any character)
    pattern_regex = pattern_regex.replace(r'\*', '.')
    # Add start and end anchors
    pattern_regex = f"^{pattern_regex}$"
    
    return re.match(pattern_regex, email_to_check) is not None

def scan_emails_in_json(json_data, target_pattern):
    """
    Recursively scan JSON data for email addresses and check if they match the pattern.
    """
    matching_emails = []
    
    def scan_recursive(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key.lower() in ['email', 'emailaddress', 'email_address']:
                    if isinstance(value, str) and '@' in value:
                        if match_email_pattern(value, target_pattern):
                            matching_emails.append(value)
                else:
                    scan_recursive(value)
        elif isinstance(obj, list):
            for item in obj:
                scan_recursive(item)
    
    scan_recursive(json_data)
    return matching_emails

url = "https://devapi.enformion.com/PersonSearch"

name = "Caryn"
address = "Baton Rouge, LA, 70817"
email = "c*****r@b*******h.net"

payload = {
    "lastName": name,
    "Address": { "addressLine2": address }
}
headers = {
    "accept": "application/json",
    "galaxy-ap-name": "cc490f58acad474b9f0b4294d46ba207",
    "galaxy-ap-password": "fa062caea4cc4e3a8daba44f3240565c",
    "galaxy-search-type": "Person",
    "content-type": "application/json"
}

response = requests.post(url, json=payload, headers=headers)

print("Full response:")
print(response.text)
print("\n" + "="*50 + "\n")

# Parse JSON and scan for matching emails
try:
    json_data = response.json()
    matching_emails = scan_emails_in_json(json_data, email)
    
    print(f"Looking for emails matching pattern: {email}")
    print(f"Found {len(matching_emails)} matching email(s):")
    for email_found in matching_emails:
        print(f"  ✓ {email_found}")
    
    if not matching_emails:
        print("  No matching emails found.")
        
except json.JSONDecodeError:
    print("Error: Response is not valid JSON")
    print("Raw response:", response.text)