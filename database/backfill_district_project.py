import sqlite3
import os

# Use the correct db path
db_file = 'F:/Laptop new hard drive Disk D/company_management/db/local.db'
print(f'Using: {db_file}')

if not os.path.exists(db_file):
    print('Database file not found!')
    exit(1)

conn = sqlite3.connect(db_file)
c = conn.cursor()

# Check if columns exist
c.execute('PRAGMA table_info(workspace_journal_entry)')
columns = [col[1] for col in c.fetchall()]
if 'district_id' not in columns or 'project_id' not in columns:
    print('district_id or project_id columns not found!')
    conn.close()
    exit(1)

print('Columns exist. Starting backfill...')

updated = 0

# 1. Update from WorkspaceMonthClose entries (category = 'Workspace Close')
c.execute("""
    SELECT wje.id, wmc.district_id, wmc.project_id
    FROM workspace_journal_entry wje
    JOIN workspace_month_close wmc ON wje.reference_id = wmc.id
    WHERE wje.category = 'Workspace Close'
    AND (wje.district_id IS NULL OR wje.project_id IS NULL)
""")
rows = c.fetchall()
for row_id, dist_id, proj_id in rows:
    c.execute("""
        UPDATE workspace_journal_entry 
        SET district_id = ?, project_id = ?
        WHERE id = ?
    """, (dist_id, proj_id, row_id))
    updated += 1
print(f'Updated {len(rows)} entries from WorkspaceMonthClose')

# 2. Update from WorkspaceFuelOilMonthClose (category = 'Workspace Fuel/Oil Close')
c.execute("""
    SELECT wje.id, wfomc.district_id, wfomc.project_id
    FROM workspace_journal_entry wje
    JOIN workspace_fuel_oil_month_close wfomc ON wje.reference_id = wfomc.id
    WHERE wje.category = 'Workspace Fuel/Oil Close'
    AND (wje.district_id IS NULL OR wje.project_id IS NULL)
""")
rows = c.fetchall()
for row_id, dist_id, proj_id in rows:
    c.execute("""
        UPDATE workspace_journal_entry 
        SET district_id = ?, project_id = ?
        WHERE id = ?
    """, (dist_id, proj_id, row_id))
    updated += 1
print(f'Updated {len(rows)} entries from WorkspaceFuelOilMonthClose')

# 3. Update Expense entries (check all expense tables that have journal_entry_id)
# Fuel Expense
c.execute("""
    SELECT wje.id, fe.district_id, fe.project_id
    FROM workspace_journal_entry wje
    JOIN fuel_expense fe ON wje.reference_id = fe.id
    WHERE wje.reference_type = 'FuelExpense'
    AND (wje.district_id IS NULL OR wje.project_id IS NULL)
""")
rows = c.fetchall()
for row_id, dist_id, proj_id in rows:
    c.execute("""
        UPDATE workspace_journal_entry 
        SET district_id = ?, project_id = ?
        WHERE id = ?
    """, (dist_id, proj_id, row_id))
    updated += 1
print(f'Updated {len(rows)} entries from FuelExpense')

# Oil Expense
c.execute("""
    SELECT wje.id, oe.district_id, oe.project_id
    FROM workspace_journal_entry wje
    JOIN oil_expense oe ON wje.reference_id = oe.id
    WHERE wje.reference_type = 'OilExpense'
    AND (wje.district_id IS NULL OR wje.project_id IS NULL)
""")
rows = c.fetchall()
for row_id, dist_id, proj_id in rows:
    c.execute("""
        UPDATE workspace_journal_entry 
        SET district_id = ?, project_id = ?
        WHERE id = ?
    """, (dist_id, proj_id, row_id))
    updated += 1
print(f'Updated {len(rows)} entries from OilExpense')

# Maintenance Expense
c.execute("""
    SELECT wje.id, me.district_id, me.project_id
    FROM workspace_journal_entry wje
    JOIN maintenance_expense me ON wje.reference_id = me.id
    WHERE wje.reference_type = 'MaintenanceExpense'
    AND (wje.district_id IS NULL OR wje.project_id IS NULL)
""")
rows = c.fetchall()
for row_id, dist_id, proj_id in rows:
    c.execute("""
        UPDATE workspace_journal_entry 
        SET district_id = ?, project_id = ?
        WHERE id = ?
    """, (dist_id, proj_id, row_id))
    updated += 1
print(f'Updated {len(rows)} entries from MaintenanceExpense')

# Employee Expense
c.execute("""
    SELECT wje.id, ee.district_id, ee.project_id
    FROM workspace_journal_entry wje
    JOIN employee_expense ee ON wje.reference_id = ee.id
    WHERE wje.reference_type = 'EmployeeExpense'
    AND (wje.district_id IS NULL OR wje.project_id IS NULL)
""")
rows = c.fetchall()
for row_id, dist_id, proj_id in rows:
    c.execute("""
        UPDATE workspace_journal_entry 
        SET district_id = ?, project_id = ?
        WHERE id = ?
    """, (dist_id, proj_id, row_id))
    updated += 1
print(f'Updated {len(rows)} entries from EmployeeExpense')

# 4. Update Opening Expenses
c.execute("""
    SELECT wje.id, woe.district_id, woe.project_id
    FROM workspace_journal_entry wje
    JOIN workspace_opening_expense woe ON wje.reference_id = woe.id
    WHERE wje.entry_type = 'Opening'
    AND (wje.district_id IS NULL OR wje.project_id IS NULL)
""")
rows = c.fetchall()
for row_id, dist_id, proj_id in rows:
    c.execute("""
        UPDATE workspace_journal_entry 
        SET district_id = ?, project_id = ?
        WHERE id = ?
    """, (dist_id, proj_id, row_id))
    updated += 1
print(f'Updated {len(rows)} entries from WorkspaceOpeningExpense')

# Fuel/Oil Opening
c.execute("""
    SELECT wje.id, wfooe.district_id, wfooe.project_id
    FROM workspace_journal_entry wje
    JOIN workspace_fuel_oil_opening_expense wfooe ON wje.reference_id = wfooe.id
    WHERE wje.entry_type = 'Opening'
    AND (wje.district_id IS NULL OR wje.project_id IS NULL)
""")
rows = c.fetchall()
for row_id, dist_id, proj_id in rows:
    c.execute("""
        UPDATE workspace_journal_entry 
        SET district_id = ?, project_id = ?
        WHERE id = ?
    """, (dist_id, proj_id, row_id))
    updated += 1
print(f'Updated {len(rows)} entries from WorkspaceFuelOilOpeningExpense')

# 5. Update Fund Transfers - use employee's district/project if available
# For Transfers, we don't have direct district/project in the transfer table
# So we'll leave them as NULL or use a default
c.execute("""
    SELECT wje.id, wje.employee_id
    FROM workspace_journal_entry wje
    WHERE wje.entry_type = 'Transfer'
    AND (wje.district_id IS NULL OR wje.project_id IS NULL)
""")
rows = c.fetchall()
# For transfers, we can't easily determine district/project from the transfer table
# since it doesn't have those columns. We'll skip these for now.
print(f'Skipped {len(rows)} Transfer entries (no district/project data in transfer table)')

# 6. For Manual Journal entries with NULL district/project, leave as is
# They were created before the new fields were added
c.execute("""
    SELECT COUNT(*) FROM workspace_journal_entry 
    WHERE entry_type = 'Journal' AND category IS NULL
    AND (district_id IS NULL OR project_id IS NULL)
""")
manual_count = c.fetchone()[0]
print(f'{manual_count} Manual Journal entries remain without district/project (expected for old entries)')

conn.commit()
conn.close()

print(f'\nBackfill complete! Total entries updated: {updated}')
print('Refresh the page to see the updated data.')

