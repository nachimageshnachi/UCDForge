import sys
import os

sys.path.append(os.path.abspath('C:/Users/mages/Desktop/FYP/METHODOLOGICAL_ASSISTANT/Software/CBR'))
from verification.text_tools import TextVerificationTools

test_cases = [
    # Valid actors
    "Safety Engineer",
    "System Administrator",
    "Admin",
    "Website Admin",
    "User",
    "Database",
    "Control System",
    "Manager",
    
    # Ambiguous but valid (can be both, but noun reading is valid here)
    "Monitor",
    "Display",
    "Controller",
    
    # Invalid verbs commonly used as actors
    "Repair",
    "Process",
    "Update",
    "Fix",
    "Run",
    "Create",
    
    # Other invalid
    "Users", # Plural
    "The Administrator", # Contains article (might be stripped or flagged)
]

print("--- Testing isMeaningfulCommonSingularNounPhrase ---\n")
for actor in test_cases:
    print(f"Testing: '{actor}'")
    valid, msg, warns = TextVerificationTools.isMeaningfulCommonSingularNounPhrase(actor)
    if valid:
        print("PASS")
    else:
        print(f"FAIL: {msg}")
    if warns:
        print(f"   Warnings: {warns}")
    print()
