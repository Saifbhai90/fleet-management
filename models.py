from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date


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

# ────────────────────────────────────────────────
# Company Model
# ────────────────────────────────────────────────
class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
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
    name = db.Column(db.String(150), nullable=False)
    start_date = db.Column(db.Date)
    status = db.Column(db.String(20), default='Active')  # 'Active' or 'Inactive'
    inactive_date = db.Column(db.Date)
    
    # Project Assignment Info (Project -> Company)
    assign_date = db.Column(db.Date, nullable=True)
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
    cnic_no = db.Column(db.String(20))
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

    def __repr__(self):
        return f'<Employee {self.name}>'


# ────────────────────────────────────────────────
# Driver Model
# ────────────────────────────────────────────────
class Driver(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.String(20), unique=True, nullable=False)
    post = db.Column(db.String(50))
    application_date = db.Column(db.Date, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    father_name = db.Column(db.String(100))
    phone1 = db.Column(db.String(20))
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
    driver_district = db.Column(db.String(50))
    assign_date = db.Column(db.Date, nullable=True)
    assign_remarks = db.Column(db.Text, nullable=True)
    remarks = db.Column(db.Text)
    status = db.Column(db.String(20), default='Active') # Active / Left
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Photo and documents (one picture, one PDF)
    photo_path = db.Column(db.String(255), nullable=True)
    document_path = db.Column(db.String(255), nullable=True)

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
    vehicle_no = db.Column(db.String(50), unique=True, nullable=False)
    model = db.Column(db.String(100), nullable=False)
    engine_no = db.Column(db.String(50))
    chassis_no = db.Column(db.String(50))
    vehicle_type = db.Column(db.String(50))
    phone_no = db.Column(db.String(20))
    active_date = db.Column(db.Date)
    driver_capacity = db.Column(db.Integer, default=1)
    remarks = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Assignment Links
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=True)
    parking_station_id = db.Column(db.Integer, db.ForeignKey('parking_station.id'), nullable=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=True)

    # Assignment Details (Vehicle -> District)
    assign_to_district_date = db.Column(db.Date)
    assignment_remarks = db.Column(db.Text)

    # NAYE COLUMNS: Ye Parking assignment ke liye hain (Inhein add karein)
    parking_assign_date = db.Column(db.Date)
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
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    district = db.Column(db.String(100))
    tehsil = db.Column(db.String(100))
    mouza = db.Column(db.String(100))
    uc_name = db.Column(db.String(100))
    create_date = db.Column(db.Date, default=date.today)
    address_location = db.Column(db.Text)
    remarks = db.Column(db.Text)
    capacity = db.Column(db.Integer, nullable=False)
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
    name = db.Column(db.String(100), unique=True, nullable=False)
    province = db.Column(db.String(100))
    remarks = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<District {self.name}>'

# Project Transfer History (audit trail)
class ProjectTransfer(db.Model):
    __tablename__ = 'project_transfer'
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    old_company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=True)
    new_company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    transfer_date = db.Column(db.Date, nullable=False, default=date.today)
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
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=False)
    
    # Old Locations
    old_project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    old_district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=True)
    old_parking_id = db.Column(db.Integer, db.ForeignKey('parking_station.id'), nullable=True)
    
    # New Locations
    new_project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    new_district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=False)
    new_parking_id = db.Column(db.Integer, db.ForeignKey('parking_station.id'), nullable=True)
    
    transfer_date = db.Column(db.Date, nullable=False, default=date.today)
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
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=False)
    
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
    
    transfer_date = db.Column(db.Date, nullable=False, default=date.today)
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
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=False)
    attendance_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='Present')
    # Present | Absent | Leave | Late | Half-Day | Off
    check_in = db.Column(db.Time, nullable=True)
    check_out = db.Column(db.Time, nullable=True)
    remarks = db.Column(db.Text, nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    driver = db.relationship('Driver', backref='attendance_records', lazy='select')
    project = db.relationship('Project', backref='attendance_records', lazy='select')

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
    name = db.Column(db.String(150), nullable=False)
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
# Notification (dashboard / in-app alerts)
# ────────────────────────────────────────────────
class Notification(db.Model):
    __tablename__ = 'notification'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text)
    link = db.Column(db.String(500))  # optional URL to open
    link_text = db.Column(db.String(100))
    notification_type = db.Column(db.String(50), default='info')  # info, warning, success, danger
    read_at = db.Column(db.DateTime, nullable=True)  # when marked read
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Notification {self.title}>'
