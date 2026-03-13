# Finance & Accounting System - Database Schema Design

## Overview
Double-entry accounting system with Chart of Accounts (COA), vouchers, and integrated expense tracking.

## Core Tables

### 1. Account (Chart of Accounts)
- **id**: Primary key
- **code**: Unique account code (e.g., "1000", "2100")
- **name**: Account name (e.g., "Main Bank", "Fuel Expense")
- **account_type**: ENUM('Asset', 'Liability', 'Equity', 'Revenue', 'Expense')
- **parent_id**: Self-referencing for sub-accounts
- **is_active**: Boolean
- **opening_balance**: Decimal (opening balance)
- **current_balance**: Decimal (computed from journal entries)
- **district_id**: FK to District (for DTO wallets)
- **project_id**: FK to Project (for project-specific accounts)
- **party_id**: FK to Party (for vendor/supplier ledgers)
- **created_at**: Timestamp

**Key Accounts to Seed:**
- Main Bank (Asset)
- Cash in Hand (Asset)
- PM Wallet - [District] (Asset)
- DTO Wallet - [District] - [Project] (Asset)
- Party Ledger - [Party Name] (Liability - Accounts Payable)
- Fuel Expense (Expense)
- Oil Expense (Expense)
- Maintenance Expense (Expense)
- Employee Expense (Expense)

### 2. JournalEntry (Transaction Header)
- **id**: Primary key
- **entry_number**: Unique voucher number (auto-generated)
- **entry_date**: Date of transaction
- **entry_type**: ENUM('Payment', 'Receipt', 'Bank', 'Journal', 'Expense')
- **description**: Transaction description
- **reference_type**: Source type ('FuelExpense', 'OilExpense', 'MaintenanceExpense', 'EmployeeExpense', 'Manual')
- **reference_id**: Source record ID
- **created_by_user_id**: FK to User
- **district_id**: FK to District (for filtering)
- **project_id**: FK to Project (for filtering)
- **is_posted**: Boolean (posted = finalized, cannot edit)
- **posted_at**: Timestamp
- **created_at**: Timestamp

### 3. JournalEntryLine (Transaction Details)
- **id**: Primary key
- **journal_entry_id**: FK to JournalEntry
- **account_id**: FK to Account
- **debit**: Decimal (debit amount)
- **credit**: Decimal (credit amount)
- **description**: Line description
- **sort_order**: Integer

**Constraint:** For each JournalEntry, SUM(debit) must equal SUM(credit)

### 4. PaymentVoucher
- **id**: Primary key
- **voucher_number**: Unique (auto-generated)
- **payment_date**: Date
- **from_account_id**: FK to Account (source: Main Bank or DTO Wallet)
- **to_account_id**: FK to Account (destination: DTO Wallet, Party Ledger, or Driver)
- **amount**: Decimal
- **payment_mode**: ENUM('Cash', 'Cheque', 'Bank Transfer', 'Online')
- **cheque_number**: String (if payment_mode = Cheque)
- **description**: Text
- **journal_entry_id**: FK to JournalEntry (auto-created)
- **created_by_user_id**: FK to User
- **district_id**: FK to District
- **project_id**: FK to Project
- **created_at**: Timestamp

### 5. ReceiptVoucher
- **id**: Primary key
- **voucher_number**: Unique
- **receipt_date**: Date
- **from_account_id**: FK to Account (source: Party or other)
- **to_account_id**: FK to Account (destination: Main Bank or DTO Wallet)
- **amount**: Decimal
- **receipt_mode**: ENUM('Cash', 'Cheque', 'Bank Transfer', 'Online')
- **description**: Text
- **journal_entry_id**: FK to JournalEntry
- **created_by_user_id**: FK to User
- **created_at**: Timestamp

### 6. BankEntry
- **id**: Primary key
- **entry_number**: Unique
- **entry_date**: Date
- **from_account_id**: FK to Account
- **to_account_id**: FK to Account
- **amount**: Decimal
- **description**: Text
- **journal_entry_id**: FK to JournalEntry
- **created_by_user_id**: FK to User
- **created_at**: Timestamp

### 7. EmployeeExpense (NEW)
- **id**: Primary key
- **expense_date**: Date
- **employee_id**: FK to Employee (or User)
- **district_id**: FK to District
- **project_id**: FK to Project
- **expense_category**: ENUM('Travel', 'Office', 'Communication', 'Other')
- **description**: Text
- **amount**: Decimal
- **payment_mode**: ENUM('Cash', 'Reimbursement', 'Advance')
- **receipt_path**: String (uploaded receipt image)
- **journal_entry_id**: FK to JournalEntry (auto-created)
- **created_by_user_id**: FK to User
- **created_at**: Timestamp

## Business Logic

### Payment Voucher Flow
1. **Accounts → DTO Wallet:**
   - Debit: DTO Wallet - [District] - [Project]
   - Credit: Main Bank

2. **DTO → Party (Market Payment):**
   - Debit: Party Ledger - [Party Name] (reduces liability)
   - Credit: DTO Wallet - [District] - [Project]

3. **DTO → Driver (Salary/Advance):**
   - Debit: Salary Expense / Advance to Driver
   - Credit: DTO Wallet

### Expense Recording (Fuel/Oil/Maintenance)
When DTO saves an expense:
1. Create JournalEntry with entry_type='Expense'
2. Add lines:
   - Debit: Fuel/Oil/Maintenance Expense Account
   - Credit: Party Ledger - [Pump/Workshop] (creates liability)

### DTO Ledger View
Shows:
- Opening Balance (wallet balance at period start)
- Receipts from Accounts (Payment Vouchers received)
- Payments to Market (Payment Vouchers issued)
- Expenses Recorded (Fuel/Oil/Maintenance)
- Current Balance
- Total Payables (what DTO owes to parties)

## Indexes
- account.code (unique)
- journal_entry.entry_number (unique)
- journal_entry.entry_date
- journal_entry.district_id, project_id
- journal_entry_line.account_id
- payment_voucher.voucher_number (unique)
- All FK columns
