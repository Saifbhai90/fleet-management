"""Project-wise default vehicle sort order (Settings → Vehicle Sort Order)."""
from sqlalchemy import nullslast

from models import Vehicle


def vehicle_order_by(*prefix_columns):
    """SQLAlchemy order_by columns: optional prefix, then project_sort_order, then vehicle_no."""
    cols = list(prefix_columns) + [
        nullslast(Vehicle.project_sort_order.asc()),
        Vehicle.vehicle_no.asc(),
    ]
    return tuple(cols)


def sort_vehicles_in_memory(vehicles):
    """Sort an in-memory list using the same rules as vehicle_order_by()."""
    def _key(v):
        order = v.project_sort_order if getattr(v, 'project_sort_order', None) is not None else 999_999
        return (order, (v.vehicle_no or '').lower())
    return sorted(vehicles, key=_key)
