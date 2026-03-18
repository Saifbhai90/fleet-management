from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date, time
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    districts = db.relationship('District', secondary=project_district,
                               backref=db.backref('projects', lazy='dynamic'),
                               lazy='dynamic')

    vehicles = db.relationship('Vehicle', backref='project', lazy=True)
    drivers = db.relationship('Driver', backref='project', lazy=True)
    parking_stations = db.relationship('ParkingStation', backref='project', lazy=True)

    @property
    def vehicle_count(self):
        return len(self.vehicles)

    @property
    def driver_count(self):
        return len(self.drivers)

    @property
    def parking_count(self):
        return len(self.parking_stations)

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

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    post = db.relationship('EmployeePost', backref='employees')
    # Multiple projects and districts (assignment from this form)
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Photo and documents (stored as R2 public URL or local relative path)
    photo_path = db.Column(db.String(500), nullable=True)
    cnic_front_path = db.Column(db.String(500), nullable=True)
    cnic_back_path = db.Column(db.String(500), nullable=True)
    license_front_path = db.Column(db.String(500), nullable=True)
    license_back_path = db.Column(db.String(500), nullable=True)
    document_path = db.Column(db.String(500), nullable=True)

    # Links
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=True)
    district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=True)
    district = db.relationship('District', backref='drivers', lazy=True)
    vehicle = db.relationship('Vehicle', backref=db.backref('drivers', lazy=True), foreign_keys=[vehicle_id], lazy=True)
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Assignment Links
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=True)
    parking_station_id = db.Column(db.Integer, db.ForeignKey('parking_station.id'), nullable=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=True)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    remarks = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
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
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=False)
    attendance_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='Present')
    # Present | Absent | Leave | Late | Half-Day | Off
    check_in = db.Column(db.Time, nullable=True)
    check_out = db.Column(db.Time, nullable=True)
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    close_reading = db.Column(db.Numeric(12, 2), nullable=False)
    tasks_count = db.Column(db.Integer, default=1)
    remarks = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    vehicle = db.relationship('Vehicle', backref='daily_tasks', lazy='select')
    project = db.relationship('Project', backref='daily_tasks', lazy='select')
    district = db.relationship('District', backref='daily_tasks', lazy='select')

    def __repr__(self):
        return f'<VehicleDailyTask {self.vehicle_id} {self.task_date}>'


class EmergencyTaskRecord(db.Model):
    __tablename__ = 'emergency_task_record'
    id = db.Column(db.Integer, primary_key=True)
    task_date = db.Column(db.Date, nullable=False)
    vehicle_no = db.Column(db.String(50), nullable=False)
    emg_tasks_count = db.Column(db.Integer, default=0)
    upload_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<EmergencyTaskRecord {self.vehicle_no} {self.task_date}>'


class VehicleMileageRecord(db.Model):
    __tablename__ = 'vehicle_mileage_record'
    id = db.Column(db.Integer, primary_key=True)
    task_date = db.Column(db.Date, nullable=False)
    vehicle_no = db.Column(db.String(50), nullable=False)
    tracker_km = db.Column(db.Numeric(12, 2), default=0)
    upload_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<VehicleMileageRecord {self.vehicle_no} {self.task_date}>'


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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    district = db.relationship('District', backref='red_tasks', lazy='select')
    project = db.relationship('Project', backref='red_tasks', lazy='select')
    vehicle = db.relationship('Vehicle', backref='red_tasks', lazy='select')

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    district = db.relationship('District', backref='move_without_tasks', lazy='select')
    project = db.relationship('Project', backref='move_without_tasks', lazy='select')
    vehicle = db.relationship('Vehicle', backref='move_without_tasks', lazy='select')

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    link = db.Column(db.String(500))  # optional URL to open
    link_text = db.Column(db.String(100))
    notification_type = db.Column(db.String(50), default='info')  # info, warning, success, danger
    read_at = db.Column(db.DateTime, nullable=True)  # legacy: when single user marked read (deprecated; use NotificationRead)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)

    created_by = db.relationship('User', backref='created_notifications', foreign_keys=[created_by_user_id], lazy=True)

    def __repr__(self):
        return f'<Notification {self.title}>'


class NotificationRead(db.Model):
    """Per-user read state for notifications (so each user marks read independently)."""
    __tablename__ = 'notification_read'
    notification_id = db.Column(db.Integer, db.ForeignKey('notification.id', ondelete='CASCADE'), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True)
    read_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    login_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

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
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<AttendanceTimeControl Morning {self.morning_start}-{self.morning_end} Night {self.night_start}-{self.night_end}>'


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
    
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
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
