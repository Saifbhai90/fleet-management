# Employee Workspace Dependency Matrix

## Scope move contracts

| Legacy area | Existing dependency | Workspace-safe strategy |
|---|---|---|
| Master Parties (`party`) | Used by fuel/oil/maintenance and fund transfer | Keep legacy table untouched; workspace uses `workspace_party` per employee |
| Master Products (`product`) | Used by oil/maintenance item rows and balances | Keep legacy product + balances; workspace uses `workspace_product` only |
| Company COA (`account`) | Global accounting/reporting and wallet logic | Keep global COA unchanged; workspace posts only in `workspace_account` |
| Company Journal (`journal_entry`) | All finance reports + ledgers | Workspace writes to `workspace_journal_entry`; company JE only on month-close bridge |
| Expense management forms | Linked with existing vehicle/task workflows | Legacy forms remain active for current users; workspace has isolated expense forms |
| Fund transfer | Existing wallets across company/driver/employee/party | Workspace transfer uses isolated accounts; no daily posting to company books |
| Freeze Data | Endpoint-based write protection | Workspace POST endpoints added to freeze catalog for date guard consistency |
| Permissions | Section/page/action tree with endpoint mapping | New `workspace` section + granular action codes mapped to workspace endpoints |

## Bridge controls

- Daily workspace operations do not touch `account` / `journal_entry`.
- Month close computes unclosed workspace expenses for period.
- One controlled bridge JE posts summarized expense to selected company account with employee wallet as contra.
- `workspace_month_close` stores both workspace JE and company JE references for audit trail and rollback analysis.

## Compatibility notes

- Legacy `party_list` / `product_list` routes are still present for backward compatibility.
- Sidebar navigation for Parties/Products now points users to Employee Workspace module.
- Existing reports and ledgers continue to use legacy data with no schema-breaking changes.
