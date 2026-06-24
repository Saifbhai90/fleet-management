import sqlite3
import os

# Use the correct db path
db_file = 'F:/Laptop new hard drive Disk D/company_management/db/local.db'
print(f'Using: {db_file}')
print(f'Exists: {os.path.exists(db_file)}')

if os.path.exists(db_file):
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    
    # Check if table exists
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='workspace_journal_entry'")
    tables = c.fetchall()
    print(f'Tables found: {tables}')
    
    if tables:
        c.execute('PRAGMA table_info(workspace_journal_entry)')
        columns = [col[1] for col in c.fetchall()]
        print(f'Existing columns: {columns}')
        
        # Add district_id if not exists
        if 'district_id' not in columns:
            c.execute('ALTER TABLE workspace_journal_entry ADD COLUMN district_id INTEGER')
            print('Added district_id')
        else:
            print('district_id already exists')
        
        # Add project_id if not exists  
        if 'project_id' not in columns:
            c.execute('ALTER TABLE workspace_journal_entry ADD COLUMN project_id INTEGER')
            print('Added project_id')
        else:
            print('project_id already exists')
        
        conn.commit()
    else:
        print('Table workspace_journal_entry not found!')
    
    conn.close()
    print('Migration complete!')
else:
    print('Database file not found!')
