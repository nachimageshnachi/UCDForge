# import os
# from Parser import ParserOperations
# from connection import connection

# base_dir = os.path.dirname(os.path.abspath(__file__))  # directory of this script
# folder_path = os.path.join(base_dir, '..', 'UCD')
# folder_path = os.path.normpath(folder_path)


# folder = [os.path.join(folder_path, f) for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]

# print(folder)

# ParserOperations.destroyTables()
# ParserOperations.createTables()
# ParserOperations.clearTables()

# for file in folder:
#     print(file)
#     a = ParserOperations(file)
#     a.addToDb()
    
# connection.close_connection()

import os
from Parser import ParserOperations
from connection import connection

# --- CONFIGURATION ---
# Path to your Google Drive folder containing XML files
folder_path = r"H:\My Drive"

# --- COLLECT ALL XML FILES IN THAT FOLDER ---
if not os.path.isdir(folder_path):
    raise FileNotFoundError(f"Folder not found: {folder_path}")

# Get full paths to all XML files
xml_files = [
    os.path.join(folder_path, f)
    for f in os.listdir(folder_path)
    if f.lower().endswith(".xml") and os.path.isfile(os.path.join(folder_path, f))
]

if not xml_files:
    raise FileNotFoundError(f"No XML files found in {folder_path}")

print(f"Found {len(xml_files)} XML files to process.")

# --- DATABASE OPERATIONS ---
ParserOperations.destroyTables()
ParserOperations.createTables()
ParserOperations.clearTables()

# --- PROCESS EACH XML FILE ---
total = len(xml_files)
for idx, file in enumerate(xml_files, start=1):
    print(f"Processing ({idx}/{total}): {file}")
    try:
        parser = ParserOperations(file)
        parser.addToDb()
    except Exception as e:
        # Highlight parsing errors clearly; keep going with next file
        print(f"!! PARSE ERROR ({idx}/{total}) in {file}: {e}")

# --- CLOSE CONNECTION ---
connection.close_connection()

print("All files processed and database updated successfully.")
