from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date, time
from utils import pk_now
import hashlib


db = SQLAlchemy()

# ────────────────────────────────────────────────
# Association Table: Project ↔ District (Many-to-Many)
# ────────────────────────────────────────────────
project_district = db.Table('project_district',
    db.Column('project_id', db.Integer, db.ForeignKey('project.id'), primary_key=True),
    db.Column('district_id', db.Integer, db.ForeignKey('district.id'), primary_key=True),
    db.Column('assign_date', db.Date, nullable=True),
    db.Column('remarks', db.Text, nullable=True)
)

# Employee ↔ Project (many-to-many): one employee can be assigned multiple projects
employee_project = db.Table('employee_project',
    db.Column('employee_id', db.Integer, db.ForeignKey('employee.id', ondelete='CASCADE'), primary_key=True),
    db.Column('project_id', db.Integer, db.ForeignKey('project.id', ondelete='CASCADE'), primary_key=True)
)

# Employee ↔ District (many-to-many): one employee can be assigned multiple districts
employee_district = db.Table('employee_district',
    db.Column('employee_id', db.Integer, db.ForeignKey('employee.id', ondelete='CASCADE'), primary_key=True),
    db.Column('district_id', db.Integer, db.ForeignKey('district.id', ondelete='CASCADE'), primary_key=True)
)

# ────────────────────────────────────────────────
# Company Model
# ────────────────────────────────────────────────
class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False, index=True)
    office_address = db.Column(db.String(200))
    state = db.Column(db.String(100))
    district = db.Column(db.String(100))
    mobile = db.Column(db.String(20))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    remarks = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=pk_now)

    # Relationship with Projects
    projects = db.relationship('Project', backref='company', lazy=True)

    def __repr__(self):
        return f'<Company {self.name}>'

# ────────────────────────────────────────────────
# Project Model
# ────────────────────────────────────────────────
class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, unique=True, index=True)
    start_date = db.Column(db.Date, index=True)
    status = db.Column(db.String(20), default='Active', index=True)  # 'Active' or 'Inactive'
    inactive_date = db.Column(db.Date)
    
    # Project Assignment Info (Project -> Company)
    assign_date = db.Column(db.Date, nullable=True, index=True)
    assign_remarks = db.Column(db.Text, nullable=True)
    
    remarks = db.Column(db.Text)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)

    # Relationships
    districts = db.relationship('District', secondary=project_district,
                               backref=db.backref('projects', lazy='dynamic'),
                               lazy='dynamic')

    vehicles = db.relationship('Vehicle', backref='project', lazy=True)
    drivers = db.relationship('Driver', backref='project', lazy=True)
    parking_stations = db.relationship('ParkingStation', backref='project', lazy=True)

    @property
    def vehicle_count(self):
        from sqlalchemy import func
        return db.session.query(func.count(Vehicle.id)).filter(Vehicle.project_id == self.id).scalar() or 0

    @property
    def driver_count(self):
        from sqlalchemy import func
        return db.session.query(func.count(Driver.id)).filter(Driver.project_id == self.id).scalar() or 0

    @property
    def parking_count(self):
        from sqlalchemy import func
        return db.session.query(func.count(ParkingStation.id)).filter(ParkingStation.project_id == self.id).scalar() or 0

    def __repr__(self):
        return f'<Project {self.name}>'


# ────────────────────────────────────────────────
# Employee Post Master (for DriverForm.post)
# ────────────────────────────────────────────────
class EmployeePost(db.Model):
    __tablename__ = 'driver_post'  # reuse existing table

    id = db.Column(db.Integer, primary_key=True)
    short_name = db.Column('name', db.String(100), unique=True, nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    remarks = db.Column(db.Text)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id', ondelete='SET NULL'), nullable=True)

    role = db.relationship('Role', backref='employee_posts', lazy=True)

    def __repr__(self):
        return f'<EmployeePost {self.full_name}>'


# ────────────────────────────────────────────────
# Other Employees (non-drivers)
# ────────────────────────────────────────────────
class Employee(db.Model):
    __tablename__ = 'employee'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)  # e.g. EMP-2026-0001
    name = db.Column(db.String(100), nullable=False)

    post_id = db.Column(db.Integer, db.ForeignKey('driver_post.id'), nullable=True)
    department = db.Column(db.String(100))

    father_name = db.Column(db.String(100))
    place_of_birth = db.Column(db.String(100))
    dob = db.Column(db.Date)
    education = db.Column(db.String(50))
    marital_status = db.Column(db.String(20))
    cnic_no = db.Column(db.String(20), unique=True)
    district = db.Column(db.String(100))
    address = db.Column(db.Text)

    phone1 = db.Column(db.String(20))
    phone2 = db.Column(db.String(20))
    email = db.Column(db.String(120))

    bank_name = db.Column(db.String(100))
    account_no = db.Column(db.String(50))
    account_title = db.Column(db.String(100))

    joining_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='Active')  # Active / Inactive / Left
    remarks = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=pk_now)

    wallet_account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=True)

    post = db.relationship('EmployeePost', backref='employees')
    wallet_account = db.relationship('Account', foreign_keys=[wallet_account_id], backref='wallet_employee', lazy='select')
    projects = db.relationship('Project', secondary=employee_project, backref=db.backref('employees', lazy='dynamic'), lazy='dynamic')
    districts = db.relationship('District', secondary=employee_district, backref=db.backref('employees', lazy='dynamic'), lazy='dynamic')
    documents = db.relationship('EmployeeDocument', backref='employee', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Employee {self.name}>'


# Employee documents (optional): CNIC copy, contract, etc.
class EmployeeDocument(db.Model):
    __tablename__ = 'employee_document'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id', ondelete='CASCADE'), nullable=False)
    title = db.Column(db.String(120), nullable=True)  # e.g. "CNIC Copy", "Contract"
    file_path = db.Column(db.String(500), nullable=False)  # relative to UPLOAD_FOLDER, e.g. employees/1/abc.pdf
    created_at = db.Column(db.DateTime, default=pk_now)

    def __repr__(self):
        return f'<EmployeeDocument {self.title or self.file_path}>'


# ────────────────────────────────────────────────
# Driver Model
# ────────────────────────────────────────────────
class Driver(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.String(20), unique=True, nullable=False)
    post = db.Column(db.String(50))
    application_date = db.Column(db.Date, nullable=False)
    name = db.Column(db.String(100), nullable=False, index=True)
    father_name = db.Column(db.String(100))
    phone1 = db.Column(db.String(20), index=True)
    phone2 = db.Column(db.String(20))
    education = db.Column(db.String(50))
    dob = db.Column(db.Date)
    blood_group = db.Column(db.String(10))
    address = db.Column(db.Text)
    emergency_no = db.Column(db.String(20))
    emergency_relation = db.Column(db.String(100), nullable=True)
    
    # Identity
    cnic_no = db.Column(db.String(20), unique=True)
    cnic_issue_date = db.Column(db.Date)
    cnic_expiry_date = db.Column(db.Date)
    cnic_status = db.Column(db.String(20))  # Valid/Expired
    
    # License
    license_no = db.Column(db.String(50), unique=True)
    license_issue_date = db.Column(db.Date)
    license_expiry_date = db.Column(db.Date)
    license_status = db.Column(db.String(20)) # Valid/Expired
    issue_district = db.Column(db.String(50))
    license_type = db.Column(db.String(50))
    
    # Bank & Sizes
    bank_name = db.Column(db.String(100))
    account_no = db.Column(db.String(50))
    account_title = db.Column(db.String(100))
    shirt_size = db.Column(db.String(10))
    trouser_size = db.Column(db.String(10))
    jacket_size = db.Column(db.String(10))
    
    shift       = db.Column(db.String(20), nullable=True)          # Morning / Night
    driver_district = db.Column(db.String(50), index=True)
    assign_date = db.Column(db.Date, nullable=True, index=True)
    assign_remarks = db.Column(db.Text, nullable=True)
    remarks = db.Column(db.Text)
    status = db.Column(db.String(20), default='Active') # Active / Left
    created_at = db.Column(db.DateTime, default=pk_now)

    # Photo and documents (stored as R2 public URL or local relative path)
    photo_path = db.Column(db.String(500), nullable=True)
    cnic_front_path = db.Column(db.String(500), nullable=True)
    cnic_back_path = db.Column(db.String(500), nullable=True)
    license_front_path = db.Column(db.String(500), nullable=True)
    license_back_path = db.Column(db.String(500), nullable=True)
    document_path = db.Column(db.String(500), nullable=True)

    # Links
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True, index=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=True, index=True)
    district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=True, index=True)
    wallet_account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=True)

    district = db.relationship('District', backref='drivers', lazy=True)
    vehicle = db.relationship('Vehicle', backref=db.backref('drivers', lazy=True), foreign_keys=[vehicle_id], lazy=True)
    wallet_account = db.relationship('Account', foreign_keys=[wallet_account_id], backref='wallet_driver', lazy='select')

    def __repr__(self):
        return f'<Driver {self.name}>'

# ────────────────────────────────────────────────
# Vehicle Model
# ────────────────────────────────────────────────
class Vehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_no = db.Column(db.String(50), unique=True, nullable=False, index=True)
    model = db.Column(db.String(100), nullable=False, index=True)
    engine_no = db.Column(db.String(50), unique=True)
    chassis_no = db.Column(db.String(50), unique=True)
    vehicle_type = db.Column(db.String(50), index=True)
    phone_no = db.Column(db.String(20))
    active_date = db.Column(db.Date, index=True)
    driver_capacity = db.Column(db.Integer, default=1)
    remarks = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=pk_now)

    # Assignment Links
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True, index=True)
    district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=True, index=True)
    parking_station_id = db.Column(db.Integer, db.ForeignKey('parking_station.id'), nullable=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=True, index=True)

    # Assignment Details (Vehicle -> District)
    assign_to_district_date = db.Column(db.Date, index=True)
    assignment_remarks = db.Column(db.Text)

    # NAYE COLUMNS: Ye Parking assignment ke liye hain (Inhein add karein)
    parking_assign_date = db.Column(db.Date, index=True)
    parking_remarks = db.Column(db.Text)

    # Vehicle documents (single PDF)
    document_path = db.Column(db.String(255), nullable=True)

    # Relationships for easy access in templates
    district = db.relationship('District', backref='vehicles')

    def __repr__(self):
        return f'<Vehicle {self.vehicle_no}>'

# ────────────────────────────────────────────────
# Parking Station Model
# ────────────────────────────────────────────────
class ParkingStation(db.Model):
    __table_args__ = (db.UniqueConstraint('name', 'district', name='uq_parking_name_district'),)
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    district = db.Column(db.String(100), index=True)
    tehsil = db.Column(db.String(100), index=True)
    mouza = db.Column(db.String(100))
    uc_name = db.Column(db.String(100))
    create_date = db.Column(db.Date, default=date.today, index=True)
    address_location = db.Column(db.Text)
    remarks = db.Column(db.Text)
    capacity = db.Column(db.Integer, nullable=False, index=True)
    latitude = db.Column(db.Numeric(10, 6), nullable=True)
    longitude = db.Column(db.Numeric(10, 6), nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)

    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    vehicles = db.relationship('Vehicle', backref='parking_station', lazy=True)

    def __repr__(self):
        return f'<ParkingStation {self.name}>'

# ────────────────────────────────────────────────
# District Model
# ────────────────────────────────────────────────
class District(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    province = db.Column(db.String(100), index=True)
    remarks = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=pk_now, index=True)

    def __repr__(self):
        return f'<District {self.name}>'

# Project Transfer History (audit trail)
class ProjectTransfer(db.Model):
    __tablename__ = 'project_transfer'
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    old_company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=True)
    new_company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    transfer_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    remarks = db.Column(db.Text)
    transferred_by = db.Column(db.String(100))  # future mein user login se
    created_at = db.Column(db.DateTime, default=pk_now)

    project = db.relationship('Project', backref='transfer_history', lazy='select')
    old_company = db.relationship('Company', foreign_keys=[old_company_id], lazy='select')
    new_company = db.relationship('Company', foreign_keys=[new_company_id], lazy='select')

    def __repr__(self):
        return f'<ProjectTransfer {self.project.name} to {self.new_company.name}>'

# Vehicle ↔ District association table (many-to-many)
vehicle_district = db.Table('vehicle_district',
    db.Column('vehicle_id', db.Integer, db.ForeignKey('vehicle.id'), primary_key=True),
    db.Column('district_id', db.Integer, db.ForeignKey('district.id'), primary_key=True),
    db.Column('assign_date', db.Date, nullable=True),
    db.Column('remarks', db.Text, nullable=True)
)

# Vehicle Transfer History
class VehicleTransfer(db.Model):
    __tablename__ = 'vehicle_transfer'
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=False, index=True)
    
    # Old Locations
    old_project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    old_district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=True)
    old_parking_id = db.Column(db.Integer, db.ForeignKey('parking_station.id'), nullable=True)
    
    # New Locations
    new_project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    new_district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=False)
    new_parking_id = db.Column(db.Integer, db.ForeignKey('parking_station.id'), nullable=True)
    
    transfer_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    remarks = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=pk_now)

    # Relationships
    vehicle = db.relationship('Vehicle', backref='transfer_history', lazy='select')
    
    old_project = db.relationship('Project', foreign_keys=[old_project_id])
    new_project = db.relationship('Project', foreign_keys=[new_project_id])
    
    old_district = db.relationship('District', foreign_keys=[old_district_id])
    new_district = db.relationship('District', foreign_keys=[new_district_id])
    
    old_parking = db.relationship('ParkingStation', foreign_keys=[old_parking_id])
    new_parking = db.relationship('ParkingStation', foreign_keys=[new_parking_id])

    def __repr__(self):
        return f'<VehicleTransfer {self.vehicle.vehicle_no}>'

# Driver Transfer History
class DriverTransfer(db.Model):
    __tablename__ = 'driver_transfer'
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=False, index=True)
    
    # Old Location
    old_project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    old_vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=True)
    old_shift     = db.Column(db.String(20), nullable=True)
    old_district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=True)   # ← yeh column
    
    # New Location
    new_project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    new_vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=False)
    new_shift     = db.Column(db.String(20), nullable=False)
    new_district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=False)  # ← yeh column
    
    transfer_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    is_shift_only = db.Column(db.Boolean, default=False, nullable=False)
    remarks = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=pk_now)

    # Relationships
    driver = db.relationship('Driver', backref='transfer_history', lazy='select')
    
    old_project = db.relationship('Project', foreign_keys=[old_project_id])
    new_project = db.relationship('Project', foreign_keys=[new_project_id])
    
    old_vehicle = db.relationship('Vehicle', foreign_keys=[old_vehicle_id])
    new_vehicle = db.relationship('Vehicle', foreign_keys=[new_vehicle_id])
    
    # Yeh do lines sahi tarah likhen
    old_district = db.relationship('District', foreign_keys=[old_district_id])
    new_district = db.relationship('District', foreign_keys=[new_district_id])

    def __repr__(self):
        return f'<DriverTransfer {self.driver.name}>'   # yeh safe hai

class DriverStatusChange(db.Model):
    __tablename__ = 'driver_status_change'
    
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=False)
    action_type = db.Column(db.String(20), nullable=False)          # 'left' ya 'rejoin'
    reason = db.Column(db.String(100))                              # Resigned, Terminated, etc.
    change_date = db.Column(db.Date, nullable=False, default=date.today)
    remarks = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=pk_now)
    
    # Left ke waqt purana assignment
    left_project_id = db.Column(db.Integer, db.ForeignKey('project.id'))
    left_district_id = db.Column(db.Integer, db.ForeignKey('district.id'))
    left_vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'))
    left_shift = db.Column(db.String(20))
    
    # Rejoin ke waqt naya assignment (optional)
    new_project_id = db.Column(db.Integer, db.ForeignKey('project.id'))
    new_district_id = db.Column(db.Integer, db.ForeignKey('district.id'))
    new_vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'))
    new_shift = db.Column(db.String(20))
    
    driver = db.relationship('Driver', backref='status_changes', lazy='select')
    left_project = db.relationship('Project', foreign_keys=[left_project_id])
    left_district = db.relationship('District', foreign_keys=[left_district_id])
    left_vehicle = db.relationship('Vehicle', foreign_keys=[left_vehicle_id])
    new_project = db.relationship('Project', foreign_keys=[new_project_id])
    new_district = db.relationship('District', foreign_keys=[new_district_id])
    new_vehicle = db.relationship('Vehicle', foreign_keys=[new_vehicle_id])
    
    def __repr__(self):
        return f'<StatusChange {self.driver.name} - {self.action_type}>'


# ────────────────────────────────────────────────
# Driver Attendance (rozana haziri)
# ────────────────────────────────────────────────
class DriverAttendance(db.Model):
    __tablename__ = 'driver_attendance'
    __table_args__ = (db.UniqueConstraint('driver_id', 'attendance_date', name='uq_attendance_driver_date'),)
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=False, index=True)
    attendance_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='Present')
    # Present | Absent | Leave | Late | Half-Day | Off
    check_in = db.Column(db.Time, nullable=True)
    check_out = db.Column(db.Time, nullable=True)
    check_out_date = db.Column(db.Date, nullable=True)
    remarks = db.Column(db.Text, nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    # Geofenced check-in: parking station, driver's coords at check-in, selfie
    parking_station_id = db.Column(db.Integer, db.ForeignKey('parking_station.id'), nullable=True)
    check_in_latitude = db.Column(db.Numeric(12, 8), nullable=True)
    check_in_longitude = db.Column(db.Numeric(12, 8), nullable=True)
    check_in_photo_path = db.Column(db.String(500), nullable=True)
    # Geofenced check-out: coords and selfie at check-out
    check_out_latitude = db.Column(db.Numeric(12, 8), nullable=True)
    check_out_longitude = db.Column(db.Numeric(12, 8), nullable=True)
    check_out_photo_path = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)
    updated_at = db.Column(db.DateTime, default=pk_now, onupdate=pk_now)

    driver = db.relationship('Driver', backref='attendance_records', lazy='select')
    project = db.relationship('Project', backref='attendance_records', lazy='select')
    parking_station = db.relationship('ParkingStation', backref='attendance_checkins', lazy='select')

    def __repr__(self):
        return f'<DriverAttendance {self.driver_id} {self.attendance_date} {self.status}>'


# ────────────────────────────────────────────────
# Task Report: Daily vehicle task entry (user)
# ────────────────────────────────────────────────
class VehicleDailyTask(db.Model):
    __tablename__ = 'vehicle_daily_task'
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=True)
    task_date = db.Column(db.Date, nullable=False)
    start_reading = db.Column(db.Numeric(12, 2), nullable=True)
    close_reading = db.Column(db.Numeric(12, 2), nullable=False)
    tasks_count = db.Column(db.Integer, default=1)
    remarks = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)

    vehicle = db.relationship('Vehicle', backref='daily_tasks', lazy='select')
    project = db.relationship('Project', backref='daily_tasks', lazy='select')
    district = db.relationship('District', backref='daily_tasks', lazy='select')

    def __repr__(self):
        return f'<VehicleDailyTask {self.vehicle_id} {self.task_date}>'


class EmergencyTaskRecord(db.Model):
    __tablename__ = 'emergency_task_record'
    id = db.Column(db.Integer, primary_key=True)
    task_date = db.Column(db.Date, nullable=False)
    upload_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=pk_now)

    task_id_ext = db.Column(db.String(50))           # A: TaskId
    request_from = db.Column(db.String(100))         # B: RequestFrom
    phone = db.Column(db.String(50))                 # C: Phone
    cli = db.Column(db.String(50))                   # D: CLI
    name = db.Column(db.String(200))                 # E: Name
    husband = db.Column(db.String(200))              # F: Husband
    address = db.Column(db.Text)                     # G: Address
    location = db.Column(db.Text)                    # H: Location
    house_color = db.Column(db.String(100))          # I: HouseColor
    door_color = db.Column(db.String(100))           # J: DoorColor
    nearest_landmark = db.Column(db.String(200))     # K: NearestLandmark
    edd = db.Column(db.String(50))                   # L: EDD
    clinical_details = db.Column(db.Text)            # M: ClinicalDetails
    district_name = db.Column(db.String(100))        # N: DistrictName
    tehsil_name = db.Column(db.String(100))          # O: TehsilName
    uc_name = db.Column(db.String(100))              # P: UCname
    amb_reg_no = db.Column(db.String(50))            # Q: ambRegNo
    status = db.Column(db.String(50))                # R: Status
    received_by = db.Column(db.String(200))          # S: ReceivedBy
    category = db.Column(db.String(50))              # T: Category
    sub_category = db.Column(db.Text)                # U: SubCategory
    facility_name = db.Column(db.String(200))        # V: FacilityName
    facility_code = db.Column(db.String(50))         # W: FacilityCode
    facility_type = db.Column(db.String(100))        # X: facilityType
    change_facility_comments = db.Column(db.Text)    # Y: ChangeFacilityComments
    excel_created_date = db.Column(db.String(50))    # Z: CreatedDate
    completed_date_time = db.Column(db.String(50))   # AA: CompletedDateTime
    first_transfer_created_date = db.Column(db.String(50))       # AB
    first_transfer_clinical_details = db.Column(db.Text)         # AC
    first_transfer_facility_name = db.Column(db.String(200))     # AD
    first_transfer_facility_type = db.Column(db.String(100))     # AE
    first_transfer_doctor_detail = db.Column(db.Text)            # AF
    second_transfer_created_date = db.Column(db.String(50))      # AG
    second_transfer_clinical_details = db.Column(db.Text)        # AH
    second_transfer_facility_name = db.Column(db.String(200))    # AI
    second_transfer_facility_type = db.Column(db.String(100))    # AJ
    second_transfer_doctor_detail = db.Column(db.Text)           # AK
    created_by = db.Column(db.String(200))           # AL: CreatedBy
    created_date1 = db.Column(db.String(50))         # AM: CreatedDate1
    created_time = db.Column(db.String(50))          # AN: CreatedTime
    pregnancy_month = db.Column(db.String(50))       # AO: PregnancyMonth
    closing_remarks = db.Column(db.Text)             # AP: ClosingRemarks
    pregnancy_month_closing = db.Column(db.String(50))  # AQ
    cli_closing = db.Column(db.String(50))           # AR: cliClosing
    task_closed_by = db.Column(db.String(200))       # AS: TaskClosedBy
    patient_cnic = db.Column(db.String(50))          # AT: PatientCNIC
    patient_admission_no = db.Column(db.String(50))  # AU: PatientAdmissionNo
    request_for = db.Column(db.String(200))          # AV: RequestFor
    closed_by = db.Column(db.String(200))            # AW: Closed_By
    caller_name = db.Column(db.String(200))          # AX: CallerName
    task_start_lat = db.Column(db.String(30))        # AY: taskStartLat
    task_start_lon = db.Column(db.String(30))        # AZ: taskStartLon
    task_end_lat = db.Column(db.String(30))          # BA: taskEndLat
    task_end_lon = db.Column(db.String(30))          # BB: taskEndLon
    ras_cow = db.Column(db.String(20))               # BC: rasCow
    distance_in_km = db.Column(db.String(30))        # BD: distanceInKM
    nearrest_health_facility = db.Column(db.String(200))  # BE: nearrestHealthFacility

    def __repr__(self):
        return f'<EmergencyTaskRecord {self.amb_reg_no} {self.task_date}>'


class VehicleMileageRecord(db.Model):
    __tablename__ = 'vehicle_mileage_record'
    id = db.Column(db.Integer, primary_key=True)
    task_date = db.Column(db.Date, nullable=False)
    upload_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=pk_now)

    reg_no = db.Column(db.String(50))                # B: RegNo
    date_time_c = db.Column(db.String(50))           # C: Date/time
    date_time_d = db.Column(db.String(50))           # D: Date/time
    date_time_e = db.Column(db.String(50))           # E: Date/time
    date_time_f = db.Column(db.String(50))           # F: Date/time
    mileage = db.Column(db.Numeric(12, 2), default=0)  # G: Mileage (Running KMs)
    ptop = db.Column(db.Numeric(12, 2), default=0)     # H: PtoP (Running KMs)
    selected_km = db.Column(db.Numeric(12, 2), nullable=True)  # user override; NULL = auto MAX(mileage,ptop)

    def effective_km(self):
        if self.selected_km is not None:
            return float(self.selected_km)
        return float(max(self.mileage or 0, self.ptop or 0))

    def __repr__(self):
        return f'<VehicleMileageRecord {self.reg_no} {self.task_date}>'


# ────────────────────────────────────────────────
# Red Task Report (Red Task entries)
# ────────────────────────────────────────────────
class RedTask(db.Model):
    __tablename__ = 'red_task'
    id = db.Column(db.Integer, primary_key=True)
    task_date = db.Column(db.Date, nullable=False)
    task_id = db.Column(db.String(50), nullable=True)  # e.g. PHF-4642638
    district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=True)
    reason = db.Column(db.Text, nullable=True)        # Reason of Red Task
    driver_name = db.Column(db.String(100), nullable=True)
    call_to_dto = db.Column(db.String(10), nullable=True)   # Yes / No
    dto_investigation = db.Column(db.Text, nullable=True)   # According to DTO Investigation
    action = db.Column(db.String(100), nullable=True)       # Action Against Red Task (No, Fine, etc.)
    fine_amount = db.Column(db.Numeric(12, 2), default=0)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)

    district = db.relationship('District', backref='red_tasks', lazy='select')
    project = db.relationship('Project', backref='red_tasks', lazy='select')
    vehicle = db.relationship('Vehicle', backref='red_tasks', lazy='select')
    driver = db.relationship('Driver', backref='red_tasks', lazy='select')

    def __repr__(self):
        return f'<RedTask {self.task_id or self.id} {self.task_date}>'


# ────────────────────────────────────────────────
# Vehicle Move without Task (Without Task Running Ambulances Data)
# ────────────────────────────────────────────────
class VehicleMoveWithoutTask(db.Model):
    __tablename__ = 'vehicle_move_without_task'
    id = db.Column(db.Integer, primary_key=True)
    move_date = db.Column(db.Date, nullable=False)
    district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=True)
    km_in = db.Column(db.Numeric(12, 2), nullable=True)
    km_out = db.Column(db.Numeric(12, 2), nullable=True)
    d_km = db.Column(db.Numeric(12, 2), nullable=True)       # Driven KM
    logbook_task = db.Column(db.Integer, default=0)
    emg_task = db.Column(db.Integer, default=0)
    t_km = db.Column(db.Numeric(12, 2), nullable=True)       # Task KM
    remarks = db.Column(db.Text, nullable=True)
    fine = db.Column(db.String(50), nullable=True)            # "No" or amount e.g. "500"
    fine_amount = db.Column(db.Numeric(12, 2), default=0)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)

    district = db.relationship('District', backref='move_without_tasks', lazy='select')
    project = db.relationship('Project', backref='move_without_tasks', lazy='select')
    vehicle = db.relationship('Vehicle', backref='move_without_tasks', lazy='select')
    driver = db.relationship('Driver', backref='move_without_tasks', lazy='select')

    def __repr__(self):
        return f'<VehicleMoveWithoutTask {self.vehicle_id} {self.move_date}>'


# ────────────────────────────────────────────────
# Penalty Record (Driver Status)
# ────────────────────────────────────────────────
class PenaltyRecord(db.Model):
    __tablename__ = 'penalty_record'
    id = db.Column(db.Integer, primary_key=True)
    district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=True)
    record_date = db.Column(db.Date, nullable=False)
    fine = db.Column(db.String(100), nullable=True)   # amount or text
    remarks = db.Column(db.Text, nullable=True)
    source_type = db.Column(db.String(30), nullable=True)  # 'red_task' or 'without_task'
    source_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)

    district = db.relationship('District', backref='penalty_records', lazy='select')
    project = db.relationship('Project', backref='penalty_records', lazy='select')
    vehicle = db.relationship('Vehicle', backref='penalty_records', lazy='select')
    driver = db.relationship('Driver', backref='penalty_records', lazy='select')

    def __repr__(self):
        return f'<PenaltyRecord {self.id} {self.record_date}>'


# ────────────────────────────────────────────────
# Party Name (Pump / Workshop / Spare parts shop)
# ────────────────────────────────────────────────
class Party(db.Model):
    __tablename__ = 'party'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    party_type = db.Column(db.String(30), nullable=False)  # Pump, Workshop, Spare parts shop
    __table_args__ = (db.UniqueConstraint('name', 'party_type', name='uq_party_name_type'),)
    district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=True)
    contact = db.Column(db.String(100), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    remarks = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)

    district = db.relationship('District', backref='parties', lazy=True)

    def __repr__(self):
        return f'<Party {self.name} ({self.party_type})>'


# ────────────────────────────────────────────────
# Product Name (used in Fueling / Oil / Maintenance forms)
# ────────────────────────────────────────────────
class Product(db.Model):
    __tablename__ = 'product'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, unique=True)
    used_in_forms = db.Column(db.String(100), nullable=True)  # comma-separated: Fueling,Oil,Maintenance
    remarks = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)

    def __repr__(self):
        return f'<Product {self.name}>'


# ────────────────────────────────────────────────
# Fuel Expense (per fueling entry)
# ────────────────────────────────────────────────
class FuelExpense(db.Model):
    __tablename__ = 'fuel_expense'
    id = db.Column(db.Integer, primary_key=True)
    district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=False)

    fueling_date = db.Column(db.Date, nullable=False)
    card_swipe_date = db.Column(db.Date, nullable=True)
    payment_type = db.Column(db.String(20), nullable=True)  # Cash, Credit, Tp/Card, Shl/Card
    slip_no = db.Column(db.String(50), nullable=True)
    fuel_type = db.Column(db.String(20), nullable=True)     # Diesel, Super (Petrol)
    fuel_pump_id = db.Column(db.Integer, db.ForeignKey('party.id'), nullable=True)  # Pump name from Party

    previous_reading = db.Column(db.Numeric(12, 2), nullable=True)   # last fueling's current_reading
    current_reading = db.Column(db.Numeric(12, 2), nullable=False)
    km = db.Column(db.Numeric(12, 2), nullable=True)                    # current - previous
    fuel_price = db.Column(db.Numeric(12, 2), nullable=True)
    liters = db.Column(db.Numeric(12, 2), nullable=True)
    mpg = db.Column(db.Numeric(12, 2), nullable=True)                  # km / liters
    amount = db.Column(db.Numeric(12, 2), nullable=True)               # fuel_price * liters

    km_out_task = db.Column(db.Numeric(12, 2), nullable=True)          # KM out (Day Start) from task report
    km_in_task = db.Column(db.Numeric(12, 2), nullable=True)          # KM In (Day Close) from task report
    meter_reading_matched = db.Column(db.String(10), nullable=True)    # Yes / No

    created_at = db.Column(db.DateTime, default=pk_now)

    district = db.relationship('District', backref='fuel_expenses', lazy='select')
    project = db.relationship('Project', backref='fuel_expenses', lazy='select')
    vehicle = db.relationship('Vehicle', backref='fuel_expenses', lazy='select')
    fuel_pump = db.relationship('Party', backref='fuel_expenses', lazy='select')

    def __repr__(self):
        return f'<FuelExpense {self.vehicle_id} {self.fueling_date}>'


# ────────────────────────────────────────────────
# Product Balance (in-hand stock for Oil/Maintenance)
# ────────────────────────────────────────────────
class ProductBalance(db.Model):
    __tablename__ = 'product_balance'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, unique=True)
    balance_qty = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    updated_at = db.Column(db.DateTime, default=pk_now, onupdate=pk_now)

    product = db.relationship('Product', backref=db.backref('balance', uselist=False), lazy=True)

    def __repr__(self):
        return f'<ProductBalance product_id={self.product_id} qty={self.balance_qty}>'


# ────────────────────────────────────────────────
# Oil Expense (header: vehicle, date, readings)
# ────────────────────────────────────────────────
class OilExpense(db.Model):
    __tablename__ = 'oil_expense'
    id = db.Column(db.Integer, primary_key=True)
    district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=False)
    expense_date = db.Column(db.Date, nullable=False)
    card_swipe_date = db.Column(db.Date, nullable=True)
    previous_reading = db.Column(db.Numeric(12, 2), nullable=True)
    current_reading = db.Column(db.Numeric(12, 2), nullable=True)
    km = db.Column(db.Numeric(12, 2), nullable=True)  # current - previous
    remarks = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)

    district = db.relationship('District', backref='oil_expenses', lazy='select')
    project = db.relationship('Project', backref='oil_expenses', lazy='select')
    vehicle = db.relationship('Vehicle', backref='oil_expenses', lazy='select')
    items = db.relationship('OilExpenseItem', backref='oil_expense', lazy='dynamic', order_by='OilExpenseItem.sort_order', cascade='all, delete-orphan')
    attachments = db.relationship('OilExpenseAttachment', backref='oil_expense', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<OilExpense {self.vehicle_id} {self.expense_date}>'


# ────────────────────────────────────────────────
# Oil Expense Item (line: product, purchase_qty, used_qty, payment, price, amount)
# ────────────────────────────────────────────────
class OilExpenseItem(db.Model):
    __tablename__ = 'oil_expense_item'
    id = db.Column(db.Integer, primary_key=True)
    oil_expense_id = db.Column(db.Integer, db.ForeignKey('oil_expense.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    payment_type = db.Column(db.String(30), nullable=True)  # Card, Credit, Cash, In Hand Stock
    purchase_qty = db.Column(db.Numeric(12, 2), nullable=True, default=0)   # adds to balance
    used_qty = db.Column(db.Numeric(12, 2), nullable=True, default=0)       # subtracts from balance
    qty = db.Column(db.Numeric(12, 2), nullable=True, default=0)            # legacy
    price = db.Column(db.Numeric(12, 2), nullable=True, default=0)
    amount = db.Column(db.Numeric(12, 2), nullable=True)  # purchase_qty * price (bill)
    sort_order = db.Column(db.Integer, default=0, nullable=False)

    product = db.relationship('Product', backref='oil_expense_items', lazy=True)

    def __repr__(self):
        return f'<OilExpenseItem {self.product_id} p={self.purchase_qty} u={self.used_qty}>'


# ────────────────────────────────────────────────
# Oil Expense Attachment (photos / videos)
# ────────────────────────────────────────────────
class OilExpenseAttachment(db.Model):
    __tablename__ = 'oil_expense_attachment'
    id = db.Column(db.Integer, primary_key=True)
    oil_expense_id = db.Column(db.Integer, db.ForeignKey('oil_expense.id'), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(20), nullable=True)  # image, video
    original_name = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)

    def __repr__(self):
        return f'<OilExpenseAttachment {self.file_path}>'


# ────────────────────────────────────────────────
# Maintenance Expense (header: vehicle, date, meter readings)
# ────────────────────────────────────────────────
class MaintenanceExpense(db.Model):
    __tablename__ = 'maintenance_expense'
    id = db.Column(db.Integer, primary_key=True)
    district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=False)
    expense_date = db.Column(db.Date, nullable=False)
    previous_reading = db.Column(db.Numeric(12, 2), nullable=True)
    current_reading = db.Column(db.Numeric(12, 2), nullable=True)
    km = db.Column(db.Numeric(12, 2), nullable=True)
    remarks = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)

    district = db.relationship('District', backref='maintenance_expenses', lazy='select')
    project = db.relationship('Project', backref='maintenance_expenses', lazy='select')
    vehicle = db.relationship('Vehicle', backref='maintenance_expenses', lazy='select')
    items = db.relationship('MaintenanceExpenseItem', backref='maintenance_expense', lazy='dynamic', order_by='MaintenanceExpenseItem.sort_order', cascade='all, delete-orphan')
    attachments = db.relationship('MaintenanceExpenseAttachment', backref='maintenance_expense', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<MaintenanceExpense {self.vehicle_id} {self.expense_date}>'


# ────────────────────────────────────────────────
# Maintenance Expense Item (product, qty, price, amount)
# ────────────────────────────────────────────────
class MaintenanceExpenseItem(db.Model):
    __tablename__ = 'maintenance_expense_item'
    id = db.Column(db.Integer, primary_key=True)
    maintenance_expense_id = db.Column(db.Integer, db.ForeignKey('maintenance_expense.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    qty = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    price = db.Column(db.Numeric(12, 2), nullable=True, default=0)
    amount = db.Column(db.Numeric(12, 2), nullable=True)
    sort_order = db.Column(db.Integer, default=0, nullable=False)

    product = db.relationship('Product', backref='maintenance_expense_items', lazy=True)

    def __repr__(self):
        return f'<MaintenanceExpenseItem {self.product_id} qty={self.qty}>'


# ────────────────────────────────────────────────
# Maintenance Expense Attachment (photos / videos)
# ────────────────────────────────────────────────
class MaintenanceExpenseAttachment(db.Model):
    __tablename__ = 'maintenance_expense_attachment'
    id = db.Column(db.Integer, primary_key=True)
    maintenance_expense_id = db.Column(db.Integer, db.ForeignKey('maintenance_expense.id'), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(20), nullable=True)
    original_name = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)

    def __repr__(self):
        return f'<MaintenanceExpenseAttachment {self.file_path}>'


# ────────────────────────────────────────────────
# Notification (dashboard / in-app alerts) — broadcast to all users; per-user read state
# ────────────────────────────────────────────────
class Notification(db.Model):
    __tablename__ = 'notification'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text)
    link = db.Column(db.String(500))
    link_text = db.Column(db.String(100))
    notification_type = db.Column(db.String(50), default='info')
    read_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    required_permission = db.Column(db.String(500), nullable=True)

    created_by = db.relationship('User', backref='created_notifications', foreign_keys=[created_by_user_id], lazy=True)

    def __repr__(self):
        return f'<Notification {self.title}>'


class NotificationRead(db.Model):
    """Per-user read state for notifications (so each user marks read independently)."""
    __tablename__ = 'notification_read'
    notification_id = db.Column(db.Integer, db.ForeignKey('notification.id', ondelete='CASCADE'), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True)
    read_at = db.Column(db.DateTime, default=pk_now, nullable=False)


class Reminder(db.Model):
    """Personal reminder for a user (only that user sees it)."""
    __tablename__ = 'reminder'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text)
    reminder_date = db.Column(db.Date, nullable=False)
    reminder_time = db.Column(db.Time, nullable=True)  # optional
    is_completed = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=pk_now)

    user = db.relationship('User', backref='reminders', lazy=True)

    def __repr__(self):
        return f'<Reminder {self.title}>'


# ────────────────────────────────────────────────
# User Login & Role-Based Access Control
# ────────────────────────────────────────────────
role_permissions = db.Table('role_permissions',
    db.Column('role_id', db.Integer, db.ForeignKey('role.id', ondelete='CASCADE'), primary_key=True),
    db.Column('permission_id', db.Integer, db.ForeignKey('permission.id', ondelete='CASCADE'), primary_key=True)
)


class Permission(db.Model):
    """Permission code for access control (e.g. master, expenses, reports)."""
    __tablename__ = 'permission'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(80), unique=True, nullable=False)   # e.g. 'master', 'expenses', 'users_manage'
    name = db.Column(db.String(120), nullable=False)               # Display name
    category = db.Column(db.String(80), nullable=True)             # Group in UI: Master, Expenses, etc.

    def __repr__(self):
        return f'<Permission {self.code}>'


class Role(db.Model):
    """Role: has many permissions. Users get permissions via their role."""
    __tablename__ = 'role'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    permissions = db.relationship('Permission', secondary=role_permissions, backref='roles', lazy='select')

    def __repr__(self):
        return f'<Role {self.name}>'

    def permission_codes(self):
        return [p.code for p in self.permissions]


class User(db.Model):
    """App user: login with username/password, linked to a role for permissions."""
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120), nullable=True)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id', ondelete='SET NULL'), nullable=True)
    employee_post_id = db.Column(db.Integer, db.ForeignKey('driver_post.id', ondelete='SET NULL'), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    force_password_change = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=pk_now)

    role = db.relationship('Role', backref='users', lazy=True)
    employee_post = db.relationship('EmployeePost', backref='users', foreign_keys=[employee_post_id], lazy=True)

    def __repr__(self):
        return f'<User {self.username}>'

    def permission_codes(self):
        if self.role:
            return self.role.permission_codes()
        return []


class LoginLog(db.Model):
    """One record per user login: who, when, from where (IP + device/browser)."""
    __tablename__ = 'login_log'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    login_at = db.Column(db.DateTime, default=pk_now, nullable=False)
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)  # Browser/device string
    logout_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref='login_logs', lazy=True)
    activities = db.relationship('ActivityLog', backref='login_log', lazy='dynamic', foreign_keys='ActivityLog.login_log_id')

    @property
    def device_id(self):
        """Short stable ID for this device/browser (from user_agent hash)."""
        raw = (self.user_agent or '').encode()
        return hashlib.sha256(raw).hexdigest()[:8] if raw else '-'

    def __repr__(self):
        return f'<LoginLog user_id={self.user_id} at {self.login_at}>'


class ActivityLog(db.Model):
    """Per-request activity in a session: endpoint, method, time, optional details."""
    __tablename__ = 'activity_log'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    login_log_id = db.Column(db.Integer, db.ForeignKey('login_log.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now, nullable=False)
    endpoint = db.Column(db.String(120), nullable=True)
    method = db.Column(db.String(10), nullable=True)
    path = db.Column(db.String(500), nullable=True)
    description = db.Column(db.String(500), nullable=True)  # Human-readable action

    user = db.relationship('User', backref='activity_logs', lazy=True)

    def __repr__(self):
        return f'<ActivityLog {self.method} {self.endpoint} at {self.created_at}>'


class ClientActivityLog(db.Model):
    """Client-side activity logs with device ID and geolocation (one row per logActivity() call)."""
    __tablename__ = 'activity_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    device_id = db.Column(db.String(80), nullable=True)   # UUID from localStorage
    action = db.Column(db.String(200), nullable=False)    # e.g. Login, Page View, Button Click
    latitude = db.Column(db.Numeric(12, 8), nullable=True)
    longitude = db.Column(db.Numeric(12, 8), nullable=True)
    accuracy = db.Column(db.Numeric(10, 2), nullable=True)  # meters
    ip_address = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now, nullable=False)

    user = db.relationship('User', backref='client_activity_logs', lazy=True)

    def __repr__(self):
        return f'<ClientActivityLog {self.action} at {self.created_at}>'


# ────────────────────────────────────────────────
# Form Control: Attendance time windows (Morning / Night shift)
# Single row: kis time se kis time tak attendance lag sakti hai
# ────────────────────────────────────────────────
class AttendanceTimeControl(db.Model):
    """Single-row settings: Morning shift & Night shift attendance allowed time window."""
    __tablename__ = 'attendance_time_control'
    id = db.Column(db.Integer, primary_key=True)
    morning_start = db.Column(db.Time, nullable=True)   # e.g. 06:00
    morning_end   = db.Column(db.Time, nullable=True)   # e.g. 10:00
    night_start   = db.Column(db.Time, nullable=True)   # e.g. 18:00
    night_end     = db.Column(db.Time, nullable=True)   # e.g. 22:00
    updated_at    = db.Column(db.DateTime, default=pk_now, onupdate=pk_now)

    def __repr__(self):
        return f'<AttendanceTimeControl Morning {self.morning_start}-{self.morning_end} Night {self.night_start}-{self.night_end}>'


# ────────────────────────────────────────────────
# Hierarchical Attendance Time Override
# Priority: Vehicle > District > Project > Global
# ────────────────────────────────────────────────
class AttendanceTimeOverride(db.Model):
    """Per-scope attendance time windows. Most specific scope wins."""
    __tablename__ = 'attendance_time_override'
    id = db.Column(db.Integer, primary_key=True)
    scope = db.Column(db.String(20), nullable=False, default='global')  # global / project / district / vehicle
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=True)
    morning_start = db.Column(db.Time, nullable=True)
    morning_end = db.Column(db.Time, nullable=True)
    night_start = db.Column(db.Time, nullable=True)
    night_end = db.Column(db.Time, nullable=True)
    morning_checkout_start = db.Column(db.Time, nullable=True)
    morning_checkout_end = db.Column(db.Time, nullable=True)
    night_checkout_start = db.Column(db.Time, nullable=True)
    night_checkout_end = db.Column(db.Time, nullable=True)
    allow_future_checkout = db.Column(db.Boolean, nullable=False, server_default='0')
    remarks = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=pk_now, onupdate=pk_now)

    project = db.relationship('Project', foreign_keys=[project_id], lazy='joined')
    district_rel = db.relationship('District', foreign_keys=[district_id], lazy='joined')
    vehicle = db.relationship('Vehicle', foreign_keys=[vehicle_id], lazy='joined')

    __table_args__ = (
        db.UniqueConstraint('scope', 'project_id', 'district_id', 'vehicle_id', name='uq_time_override_scope'),
    )

    @property
    def scope_label(self):
        if self.scope == 'vehicle' and self.vehicle:
            return f"Vehicle: {self.vehicle.vehicle_no}"
        if self.scope == 'district' and self.district_rel:
            proj = self.project.name if self.project else '–'
            return f"{proj} → {self.district_rel.name}"
        if self.scope == 'project' and self.project:
            return f"Project: {self.project.name}"
        return "Global Default"

    def __repr__(self):
        return f'<AttendanceTimeOverride scope={self.scope} id={self.id}>'


# ════════════════════════════════════════════════════════════════════════════════
# FINANCE & ACCOUNTING SYSTEM (Double-Entry Bookkeeping)
# ════════════════════════════════════════════════════════════════════════════════

# ────────────────────────────────────────────────────
# Account (Chart of Accounts - COA)
# ────────────────────────────────────────────────────
class Account(db.Model):
    """Chart of Accounts: Assets, Liabilities, Equity, Revenue, Expenses"""
    __tablename__ = 'account'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    account_type = db.Column(db.String(20), nullable=False)  # Asset, Liability, Equity, Revenue, Expense
    parent_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    opening_balance = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    current_balance = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    
    # Optional: link to specific entities for auto-created accounts
    district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    party_id = db.Column(db.Integer, db.ForeignKey('party.id'), nullable=True)
    entity_type = db.Column(db.String(30), nullable=True, index=True)  # driver, employee, party, company
    entity_id = db.Column(db.Integer, nullable=True)
    
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)
    
    # Relationships
    parent = db.relationship('Account', remote_side=[id], backref='sub_accounts')
    district = db.relationship('District', backref='accounts', lazy='select')
    project = db.relationship('Project', backref='accounts', lazy='select')
    party = db.relationship('Party', backref='accounts', lazy='select')
    
    def __repr__(self):
        return f'<Account {self.code} {self.name}>'


# ────────────────────────────────────────────────────
# Journal Entry (Transaction Header)
# ────────────────────────────────────────────────────
class JournalEntry(db.Model):
    """Journal Entry: header for double-entry transactions"""
    __tablename__ = 'journal_entry'
    
    id = db.Column(db.Integer, primary_key=True)
    entry_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    entry_date = db.Column(db.Date, nullable=False, index=True)
    entry_type = db.Column(db.String(20), nullable=False)  # Payment, Receipt, Bank, Journal, Expense
    description = db.Column(db.Text, nullable=True)
    
    # Reference to source transaction (if auto-generated from expense)
    reference_type = db.Column(db.String(50), nullable=True)  # FuelExpense, OilExpense, MaintenanceExpense, EmployeeExpense, Manual
    reference_id = db.Column(db.Integer, nullable=True)
    
    # Tracking
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    
    # Posting status
    is_posted = db.Column(db.Boolean, default=True, nullable=False)
    posted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)
    
    # Relationships
    created_by = db.relationship('User', backref='journal_entries', lazy='select')
    district = db.relationship('District', backref='journal_entries', lazy='select')
    project = db.relationship('Project', backref='journal_entries', lazy='select')
    lines = db.relationship('JournalEntryLine', backref='journal_entry', lazy='dynamic', cascade='all, delete-orphan', order_by='JournalEntryLine.sort_order')
    
    def __repr__(self):
        return f'<JournalEntry {self.entry_number} {self.entry_date}>'
    
    def total_debit(self):
        return sum(line.debit or 0 for line in self.lines)
    
    def total_credit(self):
        return sum(line.credit or 0 for line in self.lines)
    
    def is_balanced(self):
        return abs(self.total_debit() - self.total_credit()) < 0.01


# ────────────────────────────────────────────────────
# Journal Entry Line (Transaction Details)
# ────────────────────────────────────────────────────
class JournalEntryLine(db.Model):
    """Journal Entry Line: individual debit/credit entries"""
    __tablename__ = 'journal_entry_line'
    
    id = db.Column(db.Integer, primary_key=True)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entry.id'), nullable=False, index=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False, index=True)
    debit = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    credit = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    description = db.Column(db.Text, nullable=True)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    
    # Relationships
    account = db.relationship('Account', backref='journal_lines', lazy='select')
    
    def __repr__(self):
        return f'<JournalEntryLine JE#{self.journal_entry_id} Acc#{self.account_id} Dr:{self.debit} Cr:{self.credit}>'


# ────────────────────────────────────────────────────
# Payment Voucher
# ────────────────────────────────────────────────────
class PaymentVoucher(db.Model):
    """Payment Voucher: money going out (Accounts → DTO, DTO → Party/Driver)"""
    __tablename__ = 'payment_voucher'
    
    id = db.Column(db.Integer, primary_key=True)
    voucher_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    payment_date = db.Column(db.Date, nullable=False, index=True)
    
    from_account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    to_account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    
    payment_mode = db.Column(db.String(20), nullable=False, default='Cash')  # Cash, Cheque, Bank Transfer, Online
    cheque_number = db.Column(db.String(50), nullable=True)
    description = db.Column(db.Text, nullable=True)
    
    # Auto-created journal entry
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entry.id'), nullable=True)
    
    # Tracking
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)
    
    # Relationships
    from_account = db.relationship('Account', foreign_keys=[from_account_id], backref='payments_from', lazy='select')
    to_account = db.relationship('Account', foreign_keys=[to_account_id], backref='payments_to', lazy='select')
    journal_entry = db.relationship('JournalEntry', backref='payment_voucher', lazy='select')
    created_by = db.relationship('User', backref='payment_vouchers', lazy='select')
    district = db.relationship('District', backref='payment_vouchers', lazy='select')
    project = db.relationship('Project', backref='payment_vouchers', lazy='select')
    
    def __repr__(self):
        return f'<PaymentVoucher {self.voucher_number} {self.amount}>'


# ────────────────────────────────────────────────────
# Receipt Voucher
# ────────────────────────────────────────────────────
class ReceiptVoucher(db.Model):
    """Receipt Voucher: money coming in (refunds, income)"""
    __tablename__ = 'receipt_voucher'
    
    id = db.Column(db.Integer, primary_key=True)
    voucher_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    receipt_date = db.Column(db.Date, nullable=False, index=True)
    
    from_account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    to_account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    
    receipt_mode = db.Column(db.String(20), nullable=False, default='Cash')
    description = db.Column(db.Text, nullable=True)
    
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entry.id'), nullable=True)
    
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)
    
    # Relationships
    from_account = db.relationship('Account', foreign_keys=[from_account_id], backref='receipts_from', lazy='select')
    to_account = db.relationship('Account', foreign_keys=[to_account_id], backref='receipts_to', lazy='select')
    journal_entry = db.relationship('JournalEntry', backref='receipt_voucher', lazy='select')
    created_by = db.relationship('User', backref='receipt_vouchers', lazy='select')
    
    def __repr__(self):
        return f'<ReceiptVoucher {self.voucher_number} {self.amount}>'


# ────────────────────────────────────────────────────
# Bank Entry
# ────────────────────────────────────────────────────
class BankEntry(db.Model):
    """Bank Entry: transfers between bank accounts or cash"""
    __tablename__ = 'bank_entry'
    
    id = db.Column(db.Integer, primary_key=True)
    entry_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    entry_date = db.Column(db.Date, nullable=False, index=True)
    
    from_account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    to_account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    description = db.Column(db.Text, nullable=True)
    
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entry.id'), nullable=True)
    
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)
    
    # Relationships
    from_account = db.relationship('Account', foreign_keys=[from_account_id], backref='bank_entries_from', lazy='select')
    to_account = db.relationship('Account', foreign_keys=[to_account_id], backref='bank_entries_to', lazy='select')
    journal_entry = db.relationship('JournalEntry', backref='bank_entry', lazy='select')
    created_by = db.relationship('User', backref='bank_entries', lazy='select')
    
    def __repr__(self):
        return f'<BankEntry {self.entry_number} {self.amount}>'


# ────────────────────────────────────────────────────
# Employee Expense (Non-Vehicle Expenses)
# ────────────────────────────────────────────────────
class EmployeeExpense(db.Model):
    """Employee Expense: travel, office, communication, etc."""
    __tablename__ = 'employee_expense'
    
    id = db.Column(db.Integer, primary_key=True)
    expense_date = db.Column(db.Date, nullable=False, index=True)
    
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # If expense by system user
    district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    
    expense_category = db.Column(db.String(50), nullable=False)  # Travel, Office, Communication, Other
    description = db.Column(db.Text, nullable=False)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    
    payment_mode = db.Column(db.String(20), nullable=False, default='Cash')  # Cash, Reimbursement, Advance
    receipt_path = db.Column(db.String(500), nullable=True)  # Uploaded receipt image
    
    # Auto-created journal entry
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entry.id'), nullable=True)
    
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)
    
    # Relationships
    employee = db.relationship('Employee', backref='expenses', lazy='select')
    user = db.relationship('User', foreign_keys=[user_id], backref='user_expenses', lazy='select')
    district = db.relationship('District', backref='employee_expenses', lazy='select')
    project = db.relationship('Project', backref='employee_expenses', lazy='select')
    journal_entry = db.relationship('JournalEntry', backref='employee_expense', lazy='select')
    created_by = db.relationship('User', foreign_keys=[created_by_user_id], backref='created_employee_expenses', lazy='select')
    
    def __repr__(self):
        return f'<EmployeeExpense {self.expense_date} {self.expense_category} {self.amount}>'


# ────────────────────────────────────────────────────
# Voucher Sequence Counter (atomic sequence generation)
# ────────────────────────────────────────────────────
class VoucherSequence(db.Model):
    """Atomic per-prefix/per-month sequence counter.
    SELECT FOR UPDATE on this row prevents concurrent requests from
    generating the same voucher/entry number (B-04 race condition fix).
    """
    __tablename__ = 'voucher_sequence'

    id = db.Column(db.Integer, primary_key=True)
    prefix = db.Column(db.String(10), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    last_seq = db.Column(db.Integer, default=0, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('prefix', 'year', 'month', name='uq_voucher_seq_prefix_ym'),
    )

    def __repr__(self):
        return f'<VoucherSequence {self.prefix}-{self.year:04d}-{self.month:02d} seq={self.last_seq}>'


# ────────────────────────────────────────────────────
# Payroll Module
# ────────────────────────────────────────────────────

class EmployeeSalaryConfig(db.Model):
    """Salary configuration for an Employee OR a Driver."""
    __tablename__ = 'employee_salary_config'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id', ondelete='CASCADE'), unique=True, nullable=True, index=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id', ondelete='CASCADE'), unique=True, nullable=True, index=True)

    basic_salary = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    extra_day_rate = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    absent_penalty_rate = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    payment_mode = db.Column(db.String(20), default='Cash')  # Cash, Bank Transfer, Cheque
    remarks = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=pk_now)
    updated_at = db.Column(db.DateTime, default=pk_now, onupdate=pk_now)

    employee = db.relationship('Employee', backref=db.backref('salary_config', uselist=False, lazy='select'))
    driver = db.relationship('Driver', backref=db.backref('salary_config', uselist=False, lazy='select'))

    @property
    def person_name(self):
        if self.employee:
            return self.employee.name
        if self.driver:
            return self.driver.name
        return '–'

    @property
    def person_code(self):
        if self.employee:
            return self.employee.code
        if self.driver:
            return self.driver.driver_id
        return '–'

    @property
    def person_type(self):
        if self.employee_id:
            return 'Employee'
        if self.driver_id:
            return 'Driver'
        return '–'

    def __repr__(self):
        return f'<SalaryConfig {self.person_type}#{self.employee_id or self.driver_id} Basic={self.basic_salary}>'


class MonthlyPayroll(db.Model):
    """Monthly payroll record per employee/driver with attendance-based calculations."""
    __tablename__ = 'monthly_payroll'
    __table_args__ = (
        db.UniqueConstraint('employee_id', 'driver_id', 'month', 'year', name='uq_payroll_person_month_year'),
    )

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id', ondelete='CASCADE'), nullable=True, index=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id', ondelete='CASCADE'), nullable=True, index=True)
    month = db.Column(db.Integer, nullable=False)  # 1-12
    year = db.Column(db.Integer, nullable=False)

    # Attendance stats (synced from driver_attendance)
    total_days = db.Column(db.Integer, default=0, nullable=False)
    present_days = db.Column(db.Integer, default=0, nullable=False)
    absent_days = db.Column(db.Integer, default=0, nullable=False)
    leave_days = db.Column(db.Integer, default=0, nullable=False)
    late_days = db.Column(db.Integer, default=0, nullable=False)
    half_days = db.Column(db.Integer, default=0, nullable=False)
    off_days = db.Column(db.Integer, default=0, nullable=False)
    extra_working_days = db.Column(db.Integer, default=0, nullable=False)

    # Earnings
    basic_salary = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    calculated_basic = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    extra_working_pay = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    bonus = db.Column(db.Numeric(15, 2), default=0, nullable=False)

    # Deductions
    absent_fine = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    manual_fine = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    mpg_fine = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    loan_deduction = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    other_deduction = db.Column(db.Numeric(15, 2), default=0, nullable=False)

    # Totals
    gross_pay = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    total_deductions = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    net_payable = db.Column(db.Numeric(15, 2), default=0, nullable=False)

    # Workflow
    status = db.Column(db.String(20), default='Draft', nullable=False)  # Draft, Finalized, Paid
    finalized_at = db.Column(db.DateTime, nullable=True)
    finalized_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # Payment tracking
    payment_date = db.Column(db.Date, nullable=True)
    payment_method = db.Column(db.String(30), nullable=True)  # Cash, Bank Transfer, Cheque
    payment_account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    paid_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # Finance link
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entry.id'), nullable=True)

    remarks = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)
    updated_at = db.Column(db.DateTime, default=pk_now, onupdate=pk_now)

    # Relationships
    employee = db.relationship('Employee', backref='payroll_records', lazy='select')
    driver = db.relationship('Driver', backref='payroll_records', lazy='select')
    finalized_by = db.relationship('User', foreign_keys=[finalized_by_user_id], backref='finalized_payrolls', lazy='select')
    paid_by = db.relationship('User', foreign_keys=[paid_by_user_id], backref='paid_payrolls', lazy='select')
    payment_account = db.relationship('Account', foreign_keys=[payment_account_id], backref='payroll_payments', lazy='select')
    journal_entry = db.relationship('JournalEntry', backref='payroll_record', lazy='select')

    @property
    def person_name(self):
        if self.employee:
            return self.employee.name
        if self.driver:
            return self.driver.name
        return '–'

    @property
    def person_code(self):
        if self.employee:
            return self.employee.code
        if self.driver:
            return self.driver.driver_id
        return '–'

    @property
    def person_type(self):
        if self.employee_id:
            return 'Employee'
        if self.driver_id:
            return 'Driver'
        return '–'

    @property
    def salary_config(self):
        if self.employee and self.employee.salary_config:
            return self.employee.salary_config
        if self.driver and self.driver.salary_config:
            return self.driver.salary_config
        return None

    def __repr__(self):
        pid = self.employee_id or self.driver_id
        return f'<MonthlyPayroll {self.person_type}#{pid} {self.month}/{self.year} {self.status} Net={self.net_payable}>'

    def calculate(self):
        """Recalculate all totals from component values."""
        cfg = self.salary_config
        self.calculated_basic = self.basic_salary
        self.extra_working_pay = self.extra_working_days * (cfg.extra_day_rate if cfg else 0)
        self.absent_fine = self.absent_days * (cfg.absent_penalty_rate if cfg else 0)
        self.gross_pay = self.calculated_basic + self.extra_working_pay + self.bonus
        self.total_deductions = self.absent_fine + self.manual_fine + self.mpg_fine + self.loan_deduction + self.other_deduction
        self.net_payable = self.gross_pay - self.total_deductions


# ────────────────────────────────────────────────────
# Physical Book Management
# ────────────────────────────────────────────────────

class PhysicalBook(db.Model):
    """Inventory of physical logbooks and maintenance books."""
    __tablename__ = 'physical_book'

    id = db.Column(db.Integer, primary_key=True)
    serial_no = db.Column(db.String(50), unique=True, nullable=False, index=True)
    book_type = db.Column(db.String(30), nullable=False)  # Logbook, Maintenance Book
    start_page = db.Column(db.Integer, nullable=False, default=1)
    end_page = db.Column(db.Integer, nullable=False, default=100)
    status = db.Column(db.String(20), nullable=False, default='In-Stock')  # In-Stock, Issued, Returned-Full, Lost
    remarks = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)
    updated_at = db.Column(db.DateTime, default=pk_now, onupdate=pk_now)

    assignments = db.relationship('BookAssignment', backref='book', lazy='dynamic', order_by='BookAssignment.issue_date.desc()')

    @property
    def total_pages(self):
        return self.end_page - self.start_page + 1

    @property
    def current_assignment(self):
        return BookAssignment.query.filter_by(book_id=self.id, status='Active').first()

    def __repr__(self):
        return f'<PhysicalBook {self.serial_no} ({self.book_type}) [{self.status}]>'


class BookAssignment(db.Model):
    """Tracks issuance and return of physical books to vehicles/drivers."""
    __tablename__ = 'book_assignment'

    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey('physical_book.id', ondelete='CASCADE'), nullable=False, index=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id', ondelete='SET NULL'), nullable=True, index=True)
    issued_to_driver_id = db.Column(db.Integer, db.ForeignKey('driver.id', ondelete='SET NULL'), nullable=True, index=True)

    issue_date = db.Column(db.Date, nullable=False)
    return_date = db.Column(db.Date, nullable=True)
    returned_by_driver_id = db.Column(db.Integer, db.ForeignKey('driver.id', ondelete='SET NULL'), nullable=True)

    status = db.Column(db.String(20), nullable=False, default='Active')  # Active, Closed
    remarks = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)
    updated_at = db.Column(db.DateTime, default=pk_now, onupdate=pk_now)

    vehicle = db.relationship('Vehicle', backref=db.backref('book_assignments', lazy='dynamic'))
    issued_to_driver = db.relationship('Driver', foreign_keys=[issued_to_driver_id], backref='books_issued', lazy='select')
    returned_by_driver = db.relationship('Driver', foreign_keys=[returned_by_driver_id], backref='books_returned', lazy='select')

    def __repr__(self):
        return f'<BookAssignment Book#{self.book_id} Vehicle#{self.vehicle_id} [{self.status}]>'


# ────────────────────────────────────────────────
# Geofence & Attendance Settings (admin-configurable)
# ────────────────────────────────────────────────
class AttendanceSettings(db.Model):
    __tablename__ = 'attendance_settings'
    id = db.Column(db.Integer, primary_key=True)
    geofence_radius_meters = db.Column(db.Integer, nullable=False, default=150)
    geofence_enabled = db.Column(db.Boolean, nullable=False, default=True)
    checkin_reminder_minutes = db.Column(db.Integer, nullable=False, default=20)
    checkout_reminder_minutes = db.Column(db.Integer, nullable=False, default=30)
    notify_on_attendance_mark = db.Column(db.Boolean, nullable=False, default=True)
    updated_at = db.Column(db.DateTime, default=pk_now, onupdate=pk_now)

    def __repr__(self):
        return f'<AttendanceSettings geofence={self.geofence_radius_meters}m enabled={self.geofence_enabled}>'


# ────────────────────────────────────────────────
# Leave Approval Workflow
# ────────────────────────────────────────────────
class LeaveRequest(db.Model):
    __tablename__ = 'leave_request'
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id', ondelete='CASCADE'), nullable=False, index=True)
    from_date = db.Column(db.Date, nullable=False)
    to_date = db.Column(db.Date, nullable=False)
    leave_type = db.Column(db.String(30), nullable=False, default='Leave')
    reason = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='Pending')
    reviewed_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_remarks = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)
    updated_at = db.Column(db.DateTime, default=pk_now, onupdate=pk_now)

    driver = db.relationship('Driver', backref=db.backref('leave_requests', lazy='dynamic', order_by='LeaveRequest.created_at.desc()'))
    reviewer = db.relationship('User', backref='reviewed_leaves', lazy='select')

    @property
    def total_days(self):
        if self.from_date and self.to_date:
            return (self.to_date - self.from_date).days + 1
        return 1

    def __repr__(self):
        return f'<LeaveRequest Driver#{self.driver_id} {self.from_date} to {self.to_date} [{self.status}]>'


# ────────────────────────────────────────────────
# FCM Device Tokens (for push notifications)
# Bank-app style: tokens persist across logout so critical
# notifications (license expiry, admin alerts) still reach the device.
# ────────────────────────────────────────────────
class DeviceFCMToken(db.Model):
    __tablename__ = 'device_fcm_token'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'device_unique_id', name='uq_user_device'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    fcm_token = db.Column(db.String(500), nullable=False)
    device_unique_id = db.Column(db.String(255), nullable=True, index=True)
    device_info = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=pk_now)
    updated_at = db.Column(db.DateTime, default=pk_now, onupdate=pk_now)

    user = db.relationship('User', backref=db.backref('fcm_tokens', lazy='dynamic'))

    def __repr__(self):
        return f'<DeviceFCMToken User#{self.user_id} dev={self.device_unique_id} active={self.is_active}>'


# ────────────────────────────────────────────────
# Login Attempts (security tracking — failed/success)
# ────────────────────────────────────────────────
class LoginAttempt(db.Model):
    __tablename__ = 'login_attempt'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(200), nullable=False, index=True)
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    success = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=pk_now, nullable=False, index=True)

    def __repr__(self):
        return f'<LoginAttempt {self.username} ok={self.success} at {self.created_at}>'


# ────────────────────────────────────────────────
# System Settings (key-value store for persistent config)
# ────────────────────────────────────────────────
class SystemSetting(db.Model):
    __tablename__ = 'system_setting'
    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=pk_now, onupdate=pk_now)

    def __repr__(self):
        return f'<SystemSetting {self.key}>'

    @staticmethod
    def get(key, default=None):
        row = SystemSetting.query.get(key)
        return row.value if row else default

    @staticmethod
    def set(key, value):
        row = SystemSetting.query.get(key)
        if row:
            row.value = str(value) if value is not None else None
        else:
            row = SystemSetting(key=key, value=str(value) if value is not None else None)
            db.session.add(row)
        db.session.commit()
        return row


# ────────────────────────────────────────────────
# Fund Transfer (bank-like wallet transfers)
# ────────────────────────────────────────────────
class FundTransfer(db.Model):
    __tablename__ = 'fund_transfer'

    id = db.Column(db.Integer, primary_key=True)
    transfer_number = db.Column(db.String(30), unique=True, nullable=False)
    transfer_date = db.Column(db.Date, nullable=False, index=True)
    from_employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=True)
    from_driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=True)
    to_employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=True)
    to_driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=True)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    payment_mode = db.Column(db.String(30), nullable=False, default='Cash')
    reference_no = db.Column(db.String(50), nullable=True)
    description = db.Column(db.Text, nullable=True)
    district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entry.id'), nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)

    from_employee = db.relationship('Employee', foreign_keys=[from_employee_id], backref='sent_transfers', lazy='select')
    from_driver = db.relationship('Driver', foreign_keys=[from_driver_id], backref='sent_transfers', lazy='select')
    to_employee = db.relationship('Employee', foreign_keys=[to_employee_id], backref='received_transfers', lazy='select')
    to_driver = db.relationship('Driver', foreign_keys=[to_driver_id], backref='received_transfers', lazy='select')
    district = db.relationship('District', backref='fund_transfers', lazy='select')
    project = db.relationship('Project', backref='fund_transfers', lazy='select')
    journal_entry = db.relationship('JournalEntry', backref='fund_transfer', lazy='select')
    created_by = db.relationship('User', foreign_keys=[created_by_user_id], backref='created_fund_transfers', lazy='select')

    @property
    def from_name(self):
        if self.from_employee:
            return self.from_employee.name
        if self.from_driver:
            return self.from_driver.name
        return '—'

    @property
    def to_name(self):
        if self.to_employee:
            return self.to_employee.name
        if self.to_driver:
            return self.to_driver.name
        return '—'

    def __repr__(self):
        return f'<FundTransfer {self.transfer_number} {self.amount}>'


# ────────────────────────────────────────────────
# App Releases (for admin-managed in-app updates)
# ────────────────────────────────────────────────
class AppRelease(db.Model):
    __tablename__ = 'app_release'

    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.String(20), nullable=False, unique=True)
    apk_filename = db.Column(db.String(255), nullable=False)
    force_update = db.Column(db.Boolean, default=False, nullable=False)
    is_latest = db.Column(db.Boolean, default=False, nullable=False)
    release_notes = db.Column(db.Text, nullable=True)
    file_size_bytes = db.Column(db.BigInteger, nullable=True)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=pk_now)

    uploader = db.relationship('User', backref='app_releases', lazy='select')

    def __repr__(self):
        return f'<AppRelease v{self.version} latest={self.is_latest}>'

    @property
    def file_size_display(self):
        if not self.file_size_bytes:
            return '—'
        mb = self.file_size_bytes / (1024 * 1024)
        return f'{mb:.1f} MB'
