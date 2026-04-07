"""add employee workspace tables

Revision ID: l5m6n7o8p9q0
Revises: k4l5m6n7o8p9
Create Date: 2026-04-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "l5m6n7o8p9q0"
down_revision = "k4l5m6n7o8p9"
branch_labels = None
depends_on = None


def _table_exists(bind, name):
    return name in inspect(bind).get_table_names()


def upgrade():
    bind = op.get_bind()

    if not _table_exists(bind, "workspace_party"):
        op.create_table(
            "workspace_party",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employee.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("party_type", sa.String(length=50), nullable=True),
            sa.Column("phone", sa.String(length=30), nullable=True),
            sa.Column("address", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("employee_id", "name", name="uq_workspace_party_employee_name"),
        )
        op.create_index("ix_workspace_party_employee_id", "workspace_party", ["employee_id"], unique=False)
        op.create_index("ix_workspace_party_name", "workspace_party", ["name"], unique=False)

    if not _table_exists(bind, "workspace_product"):
        op.create_table(
            "workspace_product",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employee.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("unit", sa.String(length=50), nullable=True),
            sa.Column("used_in_forms", sa.String(length=120), nullable=True),
            sa.Column("default_price", sa.Numeric(15, 2), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("employee_id", "name", name="uq_workspace_product_employee_name"),
        )
        op.create_index("ix_workspace_product_employee_id", "workspace_product", ["employee_id"], unique=False)
        op.create_index("ix_workspace_product_name", "workspace_product", ["name"], unique=False)

    if not _table_exists(bind, "workspace_account"):
        op.create_table(
            "workspace_account",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employee.id", ondelete="CASCADE"), nullable=False),
            sa.Column("code", sa.String(length=20), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("account_type", sa.String(length=20), nullable=False),
            sa.Column("parent_id", sa.Integer(), sa.ForeignKey("workspace_account.id"), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("opening_balance", sa.Numeric(15, 2), nullable=False, server_default="0"),
            sa.Column("current_balance", sa.Numeric(15, 2), nullable=False, server_default="0"),
            sa.Column("entity_type", sa.String(length=30), nullable=True),
            sa.Column("entity_id", sa.Integer(), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("employee_id", "code", name="uq_workspace_account_employee_code"),
        )
        op.create_index("ix_workspace_account_employee_id", "workspace_account", ["employee_id"], unique=False)
        op.create_index("ix_workspace_account_code", "workspace_account", ["code"], unique=False)
        op.create_index("ix_workspace_account_entity_type", "workspace_account", ["entity_type"], unique=False)

    if not _table_exists(bind, "workspace_journal_entry"):
        op.create_table(
            "workspace_journal_entry",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employee.id", ondelete="CASCADE"), nullable=False),
            sa.Column("entry_number", sa.String(length=50), nullable=False),
            sa.Column("entry_date", sa.Date(), nullable=False),
            sa.Column("entry_type", sa.String(length=20), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("reference_type", sa.String(length=50), nullable=True),
            sa.Column("reference_id", sa.Integer(), nullable=True),
            sa.Column("category", sa.String(length=30), nullable=True),
            sa.Column("is_posted", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("posted_at", sa.DateTime(), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
            sa.Column("company_journal_entry_id", sa.Integer(), sa.ForeignKey("journal_entry.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_workspace_journal_entry_employee_id", "workspace_journal_entry", ["employee_id"], unique=False)
        op.create_index("ix_workspace_journal_entry_entry_number", "workspace_journal_entry", ["entry_number"], unique=False)
        op.create_index("ix_workspace_journal_entry_entry_date", "workspace_journal_entry", ["entry_date"], unique=False)
        op.create_index("ix_workspace_journal_entry_category", "workspace_journal_entry", ["category"], unique=False)

    if not _table_exists(bind, "workspace_journal_entry_line"):
        op.create_table(
            "workspace_journal_entry_line",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("journal_entry_id", sa.Integer(), sa.ForeignKey("workspace_journal_entry.id", ondelete="CASCADE"), nullable=False),
            sa.Column("account_id", sa.Integer(), sa.ForeignKey("workspace_account.id"), nullable=False),
            sa.Column("debit", sa.Numeric(15, 2), nullable=False, server_default="0"),
            sa.Column("credit", sa.Numeric(15, 2), nullable=False, server_default="0"),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index("ix_workspace_journal_entry_line_journal_entry_id", "workspace_journal_entry_line", ["journal_entry_id"], unique=False)
        op.create_index("ix_workspace_journal_entry_line_account_id", "workspace_journal_entry_line", ["account_id"], unique=False)

    if not _table_exists(bind, "workspace_month_close"):
        op.create_table(
            "workspace_month_close",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employee.id", ondelete="CASCADE"), nullable=False),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="Draft"),
            sa.Column("total_expense", sa.Numeric(15, 2), nullable=False, server_default="0"),
            sa.Column("workspace_expense_account_id", sa.Integer(), sa.ForeignKey("workspace_account.id"), nullable=True),
            sa.Column("company_account_id", sa.Integer(), sa.ForeignKey("account.id"), nullable=True),
            sa.Column("workspace_journal_entry_id", sa.Integer(), sa.ForeignKey("workspace_journal_entry.id"), nullable=True),
            sa.Column("company_journal_entry_id", sa.Integer(), sa.ForeignKey("journal_entry.id"), nullable=True),
            sa.Column("closed_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
            sa.Column("reopened_at", sa.DateTime(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("employee_id", "period_start", "period_end", name="uq_workspace_month_close_period"),
        )
        op.create_index("ix_workspace_month_close_employee_id", "workspace_month_close", ["employee_id"], unique=False)
        op.create_index("ix_workspace_month_close_period_start", "workspace_month_close", ["period_start"], unique=False)
        op.create_index("ix_workspace_month_close_period_end", "workspace_month_close", ["period_end"], unique=False)

    if not _table_exists(bind, "workspace_expense"):
        op.create_table(
            "workspace_expense",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employee.id", ondelete="CASCADE"), nullable=False),
            sa.Column("expense_number", sa.String(length=40), nullable=False),
            sa.Column("expense_date", sa.Date(), nullable=False),
            sa.Column("expense_type", sa.String(length=40), nullable=False),
            sa.Column("workspace_party_id", sa.Integer(), sa.ForeignKey("workspace_party.id"), nullable=True),
            sa.Column("workspace_product_id", sa.Integer(), sa.ForeignKey("workspace_product.id"), nullable=True),
            sa.Column("to_driver_id", sa.Integer(), sa.ForeignKey("driver.id"), nullable=True),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("amount", sa.Numeric(15, 2), nullable=False),
            sa.Column("payment_mode", sa.String(length=30), nullable=False, server_default="Cash"),
            sa.Column("category", sa.String(length=30), nullable=True),
            sa.Column("journal_entry_id", sa.Integer(), sa.ForeignKey("workspace_journal_entry.id"), nullable=True),
            sa.Column("month_close_id", sa.Integer(), sa.ForeignKey("workspace_month_close.id"), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_workspace_expense_employee_id", "workspace_expense", ["employee_id"], unique=False)
        op.create_index("ix_workspace_expense_expense_date", "workspace_expense", ["expense_date"], unique=False)
        op.create_index("ix_workspace_expense_expense_type", "workspace_expense", ["expense_type"], unique=False)
        op.create_index("ix_workspace_expense_category", "workspace_expense", ["category"], unique=False)
        op.create_index("ix_workspace_expense_month_close_id", "workspace_expense", ["month_close_id"], unique=False)

    if not _table_exists(bind, "workspace_fund_transfer"):
        op.create_table(
            "workspace_fund_transfer",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employee.id", ondelete="CASCADE"), nullable=False),
            sa.Column("transfer_number", sa.String(length=40), nullable=False),
            sa.Column("transfer_date", sa.Date(), nullable=False),
            sa.Column("from_account_id", sa.Integer(), sa.ForeignKey("workspace_account.id"), nullable=False),
            sa.Column("to_account_id", sa.Integer(), sa.ForeignKey("workspace_account.id"), nullable=False),
            sa.Column("to_workspace_party_id", sa.Integer(), sa.ForeignKey("workspace_party.id"), nullable=True),
            sa.Column("to_driver_id", sa.Integer(), sa.ForeignKey("driver.id"), nullable=True),
            sa.Column("amount", sa.Numeric(15, 2), nullable=False),
            sa.Column("payment_mode", sa.String(length=30), nullable=False, server_default="Cash"),
            sa.Column("reference_no", sa.String(length=50), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("category", sa.String(length=30), nullable=True),
            sa.Column("journal_entry_id", sa.Integer(), sa.ForeignKey("workspace_journal_entry.id"), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_workspace_fund_transfer_employee_id", "workspace_fund_transfer", ["employee_id"], unique=False)
        op.create_index("ix_workspace_fund_transfer_transfer_number", "workspace_fund_transfer", ["transfer_number"], unique=False)
        op.create_index("ix_workspace_fund_transfer_transfer_date", "workspace_fund_transfer", ["transfer_date"], unique=False)
        op.create_index("ix_workspace_fund_transfer_category", "workspace_fund_transfer", ["category"], unique=False)


def downgrade():
    bind = op.get_bind()

    if _table_exists(bind, "workspace_fund_transfer"):
        op.drop_table("workspace_fund_transfer")
    if _table_exists(bind, "workspace_expense"):
        op.drop_table("workspace_expense")
    if _table_exists(bind, "workspace_month_close"):
        op.drop_table("workspace_month_close")
    if _table_exists(bind, "workspace_journal_entry_line"):
        op.drop_table("workspace_journal_entry_line")
    if _table_exists(bind, "workspace_journal_entry"):
        op.drop_table("workspace_journal_entry")
    if _table_exists(bind, "workspace_account"):
        op.drop_table("workspace_account")
    if _table_exists(bind, "workspace_product"):
        op.drop_table("workspace_product")
    if _table_exists(bind, "workspace_party"):
        op.drop_table("workspace_party")
