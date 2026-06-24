"""
Seed Chart of Accounts (COA) for Finance & Accounting System
Run this after migration: python seed_chart_of_accounts.py
"""
from app import app, db
from models import Account, District, Project, Party
from datetime import datetime


def seed_coa():
    """Seed the Chart of Accounts with base accounts"""
    
    with app.app_context():
        # Check if accounts already exist
        if Account.query.count() > 0:
            print("⚠️  Accounts already exist. Skipping seed.")
            return
        
        print("🌱 Seeding Chart of Accounts...")
        
        # ═══════════════════════════════════════════════════════════
        # ASSETS
        # ═══════════════════════════════════════════════════════════
        
        # Main parent: Assets
        assets_parent = Account(
            code='1000',
            name='Assets',
            account_type='Asset',
            is_active=True,
            opening_balance=0,
            current_balance=0,
            description='All asset accounts'
        )
        db.session.add(assets_parent)
        db.session.flush()
        
        # Cash & Bank Accounts
        main_bank = Account(
            code='1100',
            name='Main Bank Account',
            account_type='Asset',
            parent_id=assets_parent.id,
            is_active=True,
            opening_balance=0,
            current_balance=0,
            description='Primary bank account for organization'
        )
        db.session.add(main_bank)
        
        cash_in_hand = Account(
            code='1110',
            name='Cash in Hand',
            account_type='Asset',
            parent_id=assets_parent.id,
            is_active=True,
            opening_balance=0,
            current_balance=0,
            description='Physical cash holdings'
        )
        db.session.add(cash_in_hand)
        
        # Employee Wallets (PM/DTO) - will be auto-created per district/project
        # We'll create a parent account for organization
        wallets_parent = Account(
            code='1200',
            name='Employee Wallets',
            account_type='Asset',
            parent_id=assets_parent.id,
            is_active=True,
            opening_balance=0,
            current_balance=0,
            description='PM and DTO wallet accounts'
        )
        db.session.add(wallets_parent)
        
        # Create DTO wallets for each District-Project combination
        districts = District.query.all()
        projects = Project.query.all()
        
        wallet_code_counter = 1210
        for district in districts:
            for project in projects:
                # Check if this district-project combination is valid
                if project in district.projects:
                    wallet = Account(
                        code=f'{wallet_code_counter}',
                        name=f'DTO Wallet - {district.name} - {project.name}',
                        account_type='Asset',
                        parent_id=wallets_parent.id,
                        district_id=district.id,
                        project_id=project.id,
                        is_active=True,
                        opening_balance=0,
                        current_balance=0,
                        description=f'Wallet for DTO in {district.name} working on {project.name}'
                    )
                    db.session.add(wallet)
                    wallet_code_counter += 1
        
        # ═══════════════════════════════════════════════════════════
        # LIABILITIES
        # ═══════════════════════════════════════════════════════════
        
        liabilities_parent = Account(
            code='2000',
            name='Liabilities',
            account_type='Liability',
            is_active=True,
            opening_balance=0,
            current_balance=0,
            description='All liability accounts'
        )
        db.session.add(liabilities_parent)
        
        # Accounts Payable (Party Ledgers)
        payables_parent = Account(
            code='2100',
            name='Accounts Payable',
            account_type='Liability',
            parent_id=liabilities_parent.id,
            is_active=True,
            opening_balance=0,
            current_balance=0,
            description='Amounts owed to vendors and suppliers'
        )
        db.session.add(payables_parent)
        
        # Create party ledgers for each vendor/supplier
        parties = Party.query.all()
        party_code_counter = 2110
        for party in parties:
            party_ledger = Account(
                code=f'{party_code_counter}',
                name=f'Party Ledger - {party.name}',
                account_type='Liability',
                parent_id=payables_parent.id,
                party_id=party.id,
                is_active=True,
                opening_balance=0,
                current_balance=0,
                description=f'Payable account for {party.name} ({party.party_type})'
            )
            db.session.add(party_ledger)
            party_code_counter += 1
        
        # ═══════════════════════════════════════════════════════════
        # EQUITY
        # ═══════════════════════════════════════════════════════════
        
        equity_parent = Account(
            code='3000',
            name='Equity',
            account_type='Equity',
            is_active=True,
            opening_balance=0,
            current_balance=0,
            description='Owner equity and retained earnings'
        )
        db.session.add(equity_parent)
        
        retained_earnings = Account(
            code='3100',
            name='Retained Earnings',
            account_type='Equity',
            parent_id=equity_parent.id,
            is_active=True,
            opening_balance=0,
            current_balance=0,
            description='Accumulated profits/losses'
        )
        db.session.add(retained_earnings)
        
        # ═══════════════════════════════════════════════════════════
        # REVENUE
        # ═══════════════════════════════════════════════════════════
        
        revenue_parent = Account(
            code='4000',
            name='Revenue',
            account_type='Revenue',
            is_active=True,
            opening_balance=0,
            current_balance=0,
            description='All revenue accounts'
        )
        db.session.add(revenue_parent)
        
        service_revenue = Account(
            code='4100',
            name='Service Revenue',
            account_type='Revenue',
            parent_id=revenue_parent.id,
            is_active=True,
            opening_balance=0,
            current_balance=0,
            description='Income from services'
        )
        db.session.add(service_revenue)
        
        # ═══════════════════════════════════════════════════════════
        # EXPENSES
        # ═══════════════════════════════════════════════════════════
        
        expenses_parent = Account(
            code='5000',
            name='Expenses',
            account_type='Expense',
            is_active=True,
            opening_balance=0,
            current_balance=0,
            description='All expense accounts'
        )
        db.session.add(expenses_parent)
        
        # Vehicle Operating Expenses
        vehicle_expenses = Account(
            code='5100',
            name='Vehicle Operating Expenses',
            account_type='Expense',
            parent_id=expenses_parent.id,
            is_active=True,
            opening_balance=0,
            current_balance=0,
            description='All vehicle-related expenses'
        )
        db.session.add(vehicle_expenses)
        
        fuel_expense = Account(
            code='5110',
            name='Fuel Expense',
            account_type='Expense',
            parent_id=vehicle_expenses.id,
            is_active=True,
            opening_balance=0,
            current_balance=0,
            description='Fuel and petroleum costs'
        )
        db.session.add(fuel_expense)
        
        oil_expense = Account(
            code='5120',
            name='Oil & Lubricants Expense',
            account_type='Expense',
            parent_id=vehicle_expenses.id,
            is_active=True,
            opening_balance=0,
            current_balance=0,
            description='Engine oil, brake oil, coolant, etc.'
        )
        db.session.add(oil_expense)
        
        maintenance_expense = Account(
            code='5130',
            name='Maintenance & Repair Expense',
            account_type='Expense',
            parent_id=vehicle_expenses.id,
            is_active=True,
            opening_balance=0,
            current_balance=0,
            description='Vehicle maintenance and repairs'
        )
        db.session.add(maintenance_expense)
        
        # Employee Expenses
        employee_expenses = Account(
            code='5200',
            name='Employee Expenses',
            account_type='Expense',
            parent_id=expenses_parent.id,
            is_active=True,
            opening_balance=0,
            current_balance=0,
            description='Non-vehicle employee expenses'
        )
        db.session.add(employee_expenses)
        
        travel_expense = Account(
            code='5210',
            name='Travel Expense',
            account_type='Expense',
            parent_id=employee_expenses.id,
            is_active=True,
            opening_balance=0,
            current_balance=0,
            description='Employee travel costs'
        )
        db.session.add(travel_expense)
        
        office_expense = Account(
            code='5220',
            name='Office Expense',
            account_type='Expense',
            parent_id=employee_expenses.id,
            is_active=True,
            opening_balance=0,
            current_balance=0,
            description='Office supplies and expenses'
        )
        db.session.add(office_expense)
        
        communication_expense = Account(
            code='5230',
            name='Communication Expense',
            account_type='Expense',
            parent_id=employee_expenses.id,
            is_active=True,
            opening_balance=0,
            current_balance=0,
            description='Phone, internet, communication costs'
        )
        db.session.add(communication_expense)
        
        other_expense = Account(
            code='5240',
            name='Other Expense',
            account_type='Expense',
            parent_id=employee_expenses.id,
            is_active=True,
            opening_balance=0,
            current_balance=0,
            description='Miscellaneous expenses'
        )
        db.session.add(other_expense)
        
        # Salary & Wages
        salary_expense = Account(
            code='5300',
            name='Salary & Wages',
            account_type='Expense',
            parent_id=expenses_parent.id,
            is_active=True,
            opening_balance=0,
            current_balance=0,
            description='Employee salaries and wages'
        )
        db.session.add(salary_expense)
        
        # Commit all accounts
        db.session.commit()
        
        print(f"✅ Successfully seeded {Account.query.count()} accounts!")
        print(f"   - {len(districts) * len([p for d in districts for p in projects if p in d.projects])} DTO Wallet accounts created")
        print(f"   - {len(parties)} Party Ledger accounts created")
        print("\n📊 Account Summary by Type:")
        for acc_type in ['Asset', 'Liability', 'Equity', 'Revenue', 'Expense']:
            count = Account.query.filter_by(account_type=acc_type).count()
            print(f"   {acc_type}: {count}")


if __name__ == '__main__':
    seed_coa()
