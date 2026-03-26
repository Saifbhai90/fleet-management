"""
Physical Book Management Routes
Stock entry, issuance, return, and tracking of logbooks and maintenance books.
"""
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from sqlalchemy import select, func
from models import db, PhysicalBook, BookAssignment, Vehicle, Driver
from forms import BookStockEntryForm, BookIssueForm, BookReturnForm
from permissions_config import can_see_page
from utils import pk_date
from datetime import datetime, date


def _check_auth(permission_code=None):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if permission_code:
        perms = session.get('permissions', [])
        if not session.get('is_master') and not can_see_page(perms, permission_code):
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('dashboard'))
    return None


# ════════════════════════════════════════════════════════════════════════════════
# BOOK INVENTORY (Stock)
# ════════════════════════════════════════════════════════════════════════════════

def book_inventory_list():
    auth = _check_auth('book_inventory_list')
    if auth:
        return auth

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    search = request.args.get('search', '').strip()
    status_filter = request.args.get('status', '').strip()
    type_filter = request.args.get('book_type', '').strip()

    query = db.session.query(PhysicalBook)
    if search:
        for term in search.split():
            query = query.filter(
                db.or_(
                    PhysicalBook.serial_no.ilike(f'%{term}%'),
                    PhysicalBook.remarks.ilike(f'%{term}%'),
                )
            )
    if status_filter:
        query = query.filter(PhysicalBook.status == status_filter)
    if type_filter:
        query = query.filter(PhysicalBook.book_type == type_filter)

    query = query.order_by(PhysicalBook.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    stats = {
        'total': db.session.query(func.count(PhysicalBook.id)).scalar() or 0,
        'in_stock': db.session.query(func.count(PhysicalBook.id)).filter(PhysicalBook.status == 'In-Stock').scalar() or 0,
        'issued': db.session.query(func.count(PhysicalBook.id)).filter(PhysicalBook.status == 'Issued').scalar() or 0,
        'returned': db.session.query(func.count(PhysicalBook.id)).filter(PhysicalBook.status == 'Returned-Full').scalar() or 0,
        'lost': db.session.query(func.count(PhysicalBook.id)).filter(PhysicalBook.status == 'Lost').scalar() or 0,
    }

    return render_template('books/inventory_list.html',
                           books=pagination.items, pagination=pagination,
                           page=page, per_page=per_page, search=search,
                           status_filter=status_filter, type_filter=type_filter, stats=stats)


def book_stock_entry():
    auth = _check_auth('book_stock_add')
    if auth:
        return auth

    form = BookStockEntryForm()

    if request.method == 'POST' and form.validate_on_submit():
        existing = db.session.query(PhysicalBook).filter(PhysicalBook.serial_no == form.serial_no.data.strip()).first()
        if existing:
            flash(f'Book with serial "{form.serial_no.data}" already exists.', 'danger')
            return render_template('books/stock_entry.html', form=form)

        book = PhysicalBook(
            serial_no=form.serial_no.data.strip(),
            book_type=form.book_type.data,
            start_page=form.start_page.data,
            end_page=form.end_page.data,
            status='In-Stock',
            remarks=form.remarks.data,
        )
        db.session.add(book)
        db.session.commit()
        flash(f'Book "{book.serial_no}" added to inventory.', 'success')
        return redirect(url_for('book_inventory_list'))

    return render_template('books/stock_entry.html', form=form)


def book_stock_edit(pk):
    auth = _check_auth('book_stock_add')
    if auth:
        return auth

    book = db.session.get(PhysicalBook, pk)
    if not book:
        flash('Book not found.', 'danger')
        return redirect(url_for('book_inventory_list'))
    form = BookStockEntryForm(obj=book)

    if request.method == 'POST' and form.validate_on_submit():
        dup = db.session.query(PhysicalBook).filter(
            PhysicalBook.serial_no == form.serial_no.data.strip(),
            PhysicalBook.id != pk
        ).first()
        if dup:
            flash(f'Book with serial "{form.serial_no.data}" already exists.', 'danger')
            return render_template('books/stock_entry.html', form=form, book=book)

        book.serial_no = form.serial_no.data.strip()
        book.book_type = form.book_type.data
        book.start_page = form.start_page.data
        book.end_page = form.end_page.data
        book.remarks = form.remarks.data
        db.session.commit()
        flash(f'Book "{book.serial_no}" updated.', 'success')
        return redirect(url_for('book_inventory_list'))

    return render_template('books/stock_entry.html', form=form, book=book)


def book_stock_delete(pk):
    auth = _check_auth('book_stock_delete')
    if auth:
        return auth

    book = db.session.get(PhysicalBook, pk)
    if not book:
        flash('Book not found.', 'danger')
        return redirect(url_for('book_inventory_list'))
    if book.status == 'Issued':
        flash('Cannot delete an issued book. Return it first.', 'danger')
        return redirect(url_for('book_inventory_list'))

    active = db.session.query(func.count(BookAssignment.id)).filter(
        BookAssignment.book_id == pk, BookAssignment.status == 'Active'
    ).scalar() or 0
    if active > 0:
        flash('Cannot delete: book has active assignments.', 'danger')
        return redirect(url_for('book_inventory_list'))

    db.session.delete(book)
    db.session.commit()
    flash(f'Book "{book.serial_no}" deleted.', 'success')
    return redirect(url_for('book_inventory_list'))


def book_mark_lost(pk):
    auth = _check_auth('book_stock_add')
    if auth:
        return auth

    book = db.session.get(PhysicalBook, pk)
    if not book:
        flash('Book not found.', 'danger')
        return redirect(url_for('book_inventory_list'))
    book.status = 'Lost'
    active_assign = db.session.query(BookAssignment).filter(
        BookAssignment.book_id == pk, BookAssignment.status == 'Active'
    ).first()
    if active_assign:
        active_assign.status = 'Closed'
        active_assign.return_date = pk_date()
        active_assign.remarks = (active_assign.remarks or '') + ' [Marked as Lost]'
    db.session.commit()
    flash(f'Book "{book.serial_no}" marked as Lost.', 'warning')
    return redirect(url_for('book_inventory_list'))


# ════════════════════════════════════════════════════════════════════════════════
# BOOK ISSUANCE
# ════════════════════════════════════════════════════════════════════════════════

def book_issue():
    auth = _check_auth('book_issue')
    if auth:
        return auth

    form = BookIssueForm()

    available_books = db.session.query(PhysicalBook).filter(
        PhysicalBook.status == 'In-Stock'
    ).order_by(PhysicalBook.serial_no).all()
    form.book_id.choices = [(0, '-- Select Book --')] + [
        (b.id, f"{b.serial_no} ({b.book_type}) – Pages {b.start_page}-{b.end_page}")
        for b in available_books
    ]

    vehicles = db.session.query(Vehicle).order_by(Vehicle.vehicle_no).all()
    form.vehicle_id.choices = [(0, '-- Select Vehicle --')] + [
        (v.id, f"{v.vehicle_no} – {v.model}") for v in vehicles
    ]

    drivers = db.session.query(Driver).filter(Driver.status == 'Active').order_by(Driver.name).all()
    form.issued_to_driver_id.choices = [(0, '-- Select Driver --')] + [
        (d.id, f"{d.driver_id} – {d.name}") for d in drivers
    ]

    if request.method == 'POST' and form.validate_on_submit():
        book = db.session.get(PhysicalBook, form.book_id.data)
        if not book or book.status != 'In-Stock':
            flash('Selected book is not available.', 'danger')
            return redirect(url_for('book_issue'))

        vehicle_id = form.vehicle_id.data
        book_type = book.book_type

        active_same_type = db.session.query(BookAssignment).join(
            PhysicalBook, BookAssignment.book_id == PhysicalBook.id
        ).filter(
            BookAssignment.vehicle_id == vehicle_id,
            BookAssignment.status == 'Active',
            PhysicalBook.book_type == book_type,
        ).first()
        if active_same_type:
            flash(f'This vehicle already has an active {book_type}. Return the current one first.', 'warning')
            return redirect(url_for('book_issue'))

        assignment = BookAssignment(
            book_id=book.id,
            vehicle_id=vehicle_id,
            issued_to_driver_id=form.issued_to_driver_id.data,
            issue_date=form.issue_date.data,
            status='Active',
            remarks=form.remarks.data,
        )
        book.status = 'Issued'
        db.session.add(assignment)
        db.session.commit()
        flash(f'Book "{book.serial_no}" issued to vehicle {assignment.vehicle.vehicle_no}.', 'success')
        return redirect(url_for('book_assignment_list'))

    return render_template('books/issue_form.html', form=form)


# ════════════════════════════════════════════════════════════════════════════════
# BOOK ASSIGNMENTS (Active + History)
# ════════════════════════════════════════════════════════════════════════════════

def book_assignment_list():
    auth = _check_auth('book_assignment_list')
    if auth:
        return auth

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    search = request.args.get('search', '').strip()
    status_filter = request.args.get('status', '').strip()

    query = db.session.query(BookAssignment).join(
        PhysicalBook, BookAssignment.book_id == PhysicalBook.id
    ).outerjoin(
        Vehicle, BookAssignment.vehicle_id == Vehicle.id
    ).outerjoin(
        Driver, BookAssignment.issued_to_driver_id == Driver.id
    )

    if search:
        for term in search.split():
            query = query.filter(
                db.or_(
                    PhysicalBook.serial_no.ilike(f'%{term}%'),
                    Vehicle.vehicle_no.ilike(f'%{term}%'),
                    Driver.name.ilike(f'%{term}%'),
                    Driver.driver_id.ilike(f'%{term}%'),
                )
            )
    if status_filter:
        query = query.filter(BookAssignment.status == status_filter)

    query = query.order_by(BookAssignment.status.asc(), BookAssignment.issue_date.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template('books/assignment_list.html',
                           assignments=pagination.items, pagination=pagination,
                           page=page, per_page=per_page, search=search,
                           status_filter=status_filter)


def book_return(pk):
    """Mark a book assignment as returned."""
    auth = _check_auth('book_return')
    if auth:
        return auth

    assignment = db.session.get(BookAssignment, pk)
    if not assignment:
        flash('Assignment not found.', 'danger')
        return redirect(url_for('book_assignment_list'))
    if assignment.status != 'Active':
        flash('This assignment is already closed.', 'warning')
        return redirect(url_for('book_assignment_list'))

    form = BookReturnForm()
    drivers = db.session.query(Driver).filter(Driver.status == 'Active').order_by(Driver.name).all()
    form.returned_by_driver_id.choices = [(0, '-- Select Driver --')] + [
        (d.id, f"{d.driver_id} – {d.name}") for d in drivers
    ]

    if request.method == 'POST' and form.validate_on_submit():
        assignment.status = 'Closed'
        assignment.return_date = form.return_date.data
        assignment.returned_by_driver_id = form.returned_by_driver_id.data
        if form.remarks.data:
            assignment.remarks = (assignment.remarks or '') + '\nReturn: ' + form.remarks.data

        assignment.book.status = 'Returned-Full'
        db.session.commit()
        flash(f'Book "{assignment.book.serial_no}" returned successfully.', 'success')
        return redirect(url_for('book_assignment_list'))

    return render_template('books/return_form.html', form=form, assignment=assignment)


# ════════════════════════════════════════════════════════════════════════════════
# PENDING RETURNS REPORT
# ════════════════════════════════════════════════════════════════════════════════

def book_pending_returns():
    auth = _check_auth('book_pending_returns')
    if auth:
        return auth

    pending = db.session.query(BookAssignment).filter(
        BookAssignment.status == 'Active'
    ).join(
        PhysicalBook, BookAssignment.book_id == PhysicalBook.id
    ).outerjoin(
        Vehicle, BookAssignment.vehicle_id == Vehicle.id
    ).outerjoin(
        Driver, BookAssignment.issued_to_driver_id == Driver.id
    ).order_by(BookAssignment.issue_date.asc()).all()

    total = len(pending)
    logbooks = [p for p in pending if p.book.book_type == 'Logbook']
    maint_books = [p for p in pending if p.book.book_type == 'Maintenance Book']

    return render_template('books/pending_returns.html',
                           pending=pending, total=total,
                           logbooks=logbooks, maint_books=maint_books,
                           today=pk_date())


# ════════════════════════════════════════════════════════════════════════════════
# BOOK HISTORY (for Vehicle Profile)
# ════════════════════════════════════════════════════════════════════════════════

def api_vehicle_book_history(vehicle_id):
    """AJAX: Get book assignment history for a vehicle."""
    assignments = db.session.query(BookAssignment).filter(
        BookAssignment.vehicle_id == vehicle_id
    ).join(
        PhysicalBook, BookAssignment.book_id == PhysicalBook.id
    ).order_by(BookAssignment.issue_date.desc()).all()

    result = []
    for a in assignments:
        result.append({
            'id': a.id,
            'serial_no': a.book.serial_no,
            'book_type': a.book.book_type,
            'pages': f"{a.book.start_page}-{a.book.end_page}",
            'issue_date': a.issue_date.strftime('%d-%m-%Y') if a.issue_date else '',
            'return_date': a.return_date.strftime('%d-%m-%Y') if a.return_date else '–',
            'issued_to': a.issued_to_driver.name if a.issued_to_driver else '–',
            'returned_by': a.returned_by_driver.name if a.returned_by_driver else '–',
            'status': a.status,
        })

    return jsonify({'assignments': result, 'total': len(result)})


def register_book_routes(application):
    """Register all book URLs on the Flask app."""
    application.add_url_rule('/books/inventory', 'book_inventory_list', book_inventory_list)
    application.add_url_rule('/books/add', 'book_stock_entry', book_stock_entry, methods=['GET', 'POST'])
    application.add_url_rule('/books/<int:pk>/edit', 'book_stock_edit', book_stock_edit, methods=['GET', 'POST'])
    application.add_url_rule('/books/<int:pk>/delete', 'book_stock_delete', book_stock_delete, methods=['POST'])
    application.add_url_rule('/books/<int:pk>/mark-lost', 'book_mark_lost', book_mark_lost, methods=['POST'])
    application.add_url_rule('/books/issue', 'book_issue', book_issue, methods=['GET', 'POST'])
    application.add_url_rule('/books/assignments', 'book_assignment_list', book_assignment_list)
    application.add_url_rule('/books/assignment/<int:pk>/return', 'book_return', book_return, methods=['GET', 'POST'])
    application.add_url_rule('/books/pending-returns', 'book_pending_returns', book_pending_returns)
    application.add_url_rule('/api/vehicle/<int:vehicle_id>/book-history', 'api_vehicle_book_history', api_vehicle_book_history)
