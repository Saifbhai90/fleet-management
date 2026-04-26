"""
List UI: when to show Upload status + Media columns.
Hide both only when every row in the *filtered* result is “ideal”:
  upload in a finished-success state, and all attachments are on Cloud (R2/HTTPS URL).

If any row is processing / error / partial, has no files, or has local / mixed / non-HTTP media, show the columns.
"""


def _upload_status_is_problematic(value):
    st = (value or "success").strip().lower()
    return st in ("processing", "error", "partial")


def _media_fully_cloud(attachments_queryable):
    """
    Match fuel/oil/MWO list templates: green “Cloud” when there is at least one
    attachment row and no local (disk) file_path — see ns.local==0 after counting.
    """
    cloud, local, n = 0, 0, 0
    for a in attachments_queryable.all():
        p = a.file_path or ""
        n += 1
        if p and (p.startswith("http://") or p.startswith("https://")):
            cloud += 1
        elif p:
            local += 1
    if n == 0:
        return False
    return local == 0


def expense_or_work_order_needs_upload_media_columns(rec):
    """
    rec: FuelExpense, OilExpense, MaintenanceExpense, or MaintenanceWorkOrder.
    Returns True if Upload/Media columns should be visible (something needs attention or isn’t all-cloud).
    """
    if _upload_status_is_problematic(getattr(rec, "upload_status", None)):
        return True
    if not _media_fully_cloud(rec.attachments):
        return True
    return False


def fund_transfer_needs_upload_media_columns(row):
    """
    FundTransfer or WorkspaceFundTransfer: single `attachment` string; ideal = non-empty https URL.
    """
    a = (getattr(row, "attachment", None) or "").strip()
    if not a:
        return True
    if a.startswith("http://") or a.startswith("https://"):
        return False
    return True
