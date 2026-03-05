from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import (
    StringField, TextAreaField, DateField, IntegerField,
    SelectField, SelectMultipleField, SubmitField, HiddenField,
    RadioField, DecimalField
)
from wtforms.validators import (
    DataRequired, Length, Optional, NumberRange, Email, ValidationError, Regexp
)
from datetime import date


# Company Form
class CompanyForm(FlaskForm):
    name = StringField('Company Name', validators=[DataRequired(), Length(min=2, max=120)])
    office_address = StringField('Office Address', validators=[Optional(), Length(max=200)])
    state = StringField('State', validators=[Optional(), Length(max=100)])
    district = StringField('District', validators=[Optional(), Length(max=100)])
    mobile = StringField('Mobile', validators=[Optional(), Length(max=20), Regexp(r'^03[0-9]{2}-[0-9]{7}$', message='Format: 0300-1110810')], render_kw={"placeholder": "0300-1110810"})
    phone = StringField('Phone', validators=[Optional(), Length(max=20)], render_kw={"placeholder": "03xx-xxxxxxx"})
    email = StringField('Email', validators=[Optional(), Email()])
    remarks = TextAreaField('Remarks', validators=[Optional()])
    submit = SubmitField('Save')


# Project Form
class ProjectForm(FlaskForm):
    name = StringField('Project Name', validators=[DataRequired(), Length(min=2, max=120)])
    start_date = DateField('Start Date', format='%d-%m-%Y',
                           render_kw={"class": "form-control datepicker"},
                           validators=[DataRequired()])
    remarks = TextAreaField('Remarks', validators=[Optional()])
    status = RadioField('Status',
                        choices=[('Active', 'Active'), ('Inactive', 'Inactive')],
                        default='Active',
                        validators=[DataRequired()])
    inactive_date = DateField('Inactive Date (Close Date)', format='%d-%m-%Y',
                              render_kw={"class": "form-control datepicker"},
                              validators=[Optional()])

    submit = SubmitField('Save')

    def validate_inactive_date(self, field):
        if self.status.data == 'Inactive' and not field.data:
            raise ValidationError('Inactive Date is required when status is Inactive.')


# Vehicle Form
class VehicleForm(FlaskForm):
    vehicle_no = StringField('Vehicle No#', validators=[DataRequired(), Length(max=50)])
    model = StringField('Model', validators=[DataRequired(), Length(max=100)])
    engine_no = StringField('Engine No#', validators=[Optional(), Length(max=50)])
    chassis_no = StringField('Chassis No#', validators=[Optional(), Length(max=50)])
    vehicle_type = SelectField('Vehicle Type',
                               choices=[
                                   ('Ambulance', 'Ambulance'),
                                   ('Passanger', 'Passanger'),
                                   ('USG+Passanger', 'USG+Passanger'),
                                   ('USG', 'USG'),
                               ],
                               validators=[DataRequired()])
    driver_capacity = IntegerField('Driver Capacity', validators=[Optional(), NumberRange(min=1)])

    phone_no = StringField('Vehicle Phone No', validators=[Optional(), Length(max=20)])
    active_date = DateField('Active Date', format='%d-%m-%Y',
                            render_kw={"class": "form-control datepicker"},
                            validators=[Optional()])
    remarks = TextAreaField('Remarks', validators=[Optional()])
    document = FileField('Vehicle Documents (PDF)', validators=[Optional(),
        FileAllowed(['pdf'], 'Only PDF files allowed')])
    submit = SubmitField('Save')


# Driver Form
class DriverForm(FlaskForm):
    driver_id = StringField('Driver ID', validators=[DataRequired()])
    post = SelectField('Post', choices=[
        ('Driver', 'Driver'),
        ('Senior Driver', 'Senior Driver'),
        ('Supervisor', 'Supervisor'),
        ('Trainer', 'Trainer'),
        ('Other', 'Other')
    ], validators=[DataRequired()])
    application_date = DateField('Application Date', format='%d-%m-%Y', validators=[DataRequired()])
    name = StringField('Full Name', validators=[DataRequired()])
    father_name = StringField('Father Name', validators=[DataRequired()])
    dob = DateField('Date of Birth', format='%d-%m-%Y', validators=[DataRequired()])
    phone1 = StringField('Phone No 1', validators=[DataRequired()], render_kw={"placeholder": "0300-1110810"})
    phone2 = StringField('Phone No 2', render_kw={"placeholder": "03xx-xxxxxxx"})
    emergency_no = StringField('Emergency No', validators=[DataRequired()], render_kw={"placeholder": "03xx-xxxxxxx"})
    address = TextAreaField('Address', validators=[DataRequired()])
    education = SelectField('Education', choices=[
        ('Middle', 'Middle'),
        ('Matric', 'Matric'),
        ('Intermediate', 'Intermediate'),
        ('Graduate', 'Graduate')
    ], validators=[DataRequired()])
    blood_group = SelectField('Blood Group', choices=[
        ('O+', 'O+'), ('A+', 'A+'), ('B+', 'B+'), ('AB+', 'AB+'),
        ('O-', 'O-'), ('A-', 'A-'), ('B-', 'B-'), ('AB-', 'AB-')
    ], validators=[DataRequired()])
    driver_district = StringField('Driver District', validators=[DataRequired()])
    
    # CNIC & License
    cnic_no = StringField('CNIC No', validators=[DataRequired(), Regexp(r'^[0-9]{5}-[0-9]{7}-[0-9]{1}$', message='Format: 32304-1111111-5')], render_kw={"placeholder": "32304-1111111-5"})
    cnic_issue_date = DateField('CNIC Issue Date', format='%d-%m-%Y', validators=[DataRequired()])
    cnic_expiry_date = DateField('CNIC Expiry Date', format='%d-%m-%Y', validators=[DataRequired()])
    cnic_status = StringField('CNIC Status', render_kw={'readonly': True})
    license_no = StringField('License No', validators=[DataRequired()])
    license_type = SelectField('License Type', choices=[
        ('M/Car', 'M/Car'), ('LTV', 'LTV'), ('HTV', 'HTV'), ('PSV', 'PSV'),
        ('M/Car, LTV', 'M/Car, LTV'), ('M/Car, HTV', 'M/Car, HTV'),
        ('M/Car, LTV, HTV', 'M/Car, LTV, HTV'), ('M/Car, LTV, HTV, PSV', 'M/Car, LTV, HTV, PSV')
    ], validators=[DataRequired()])
    issue_district = StringField('Issue District', validators=[DataRequired()])
    license_issue_date = DateField('License Issue Date', format='%d-%m-%Y', validators=[DataRequired()])
    license_expiry_date = DateField('License Expiry Date', format='%d-%m-%Y', validators=[DataRequired()])
    license_status = StringField('License Status', render_kw={'readonly': True})
    
    # Bank & Uniform
    bank_name = StringField('Bank Name')
    account_no = StringField('Account No')
    account_title = StringField('Account Title')
    shirt_size = SelectField('Shirt Size', choices=[('S', 'S'), ('M', 'M'), ('L', 'L'), ('XL', 'XL'), ('XXL', 'XXL')])
    trouser_size = SelectField('Trouser Size', choices=[('30', '30'), ('32', '32'), ('34', '34'), ('36', '36')])
    jacket_size = SelectField('Jacket Size', choices=[('S', 'S'), ('M', 'M'), ('L', 'L'), ('XL', 'XL')])

    photo = FileField('Driver Photo', validators=[Optional(),
        FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'webp'], 'Only image files (jpg, png, gif, webp) allowed')])
    document = FileField('Documents (PDF)', validators=[Optional(),
        FileAllowed(['pdf'], 'Only PDF allowed')])

    submit = SubmitField('Save Driver Data')


# Parking Form
class ParkingForm(FlaskForm):
    name = StringField('Parking Station Name', validators=[DataRequired(), Length(max=100)])
    district = StringField('District Name', validators=[Optional(), Length(max=100)])
    tehsil = StringField('Tehsil Name', validators=[Optional(), Length(max=100)])
    mouza = StringField('Mouza Name', validators=[Optional(), Length(max=100)])
    uc_name = StringField('UC Name', validators=[Optional(), Length(max=100)])
    create_date = DateField('Create Date', format='%d-%m-%Y',
                            render_kw={"class": "form-control datepicker"},
                            validators=[Optional()])
    address_location = TextAreaField('Address/Location Description', validators=[Optional()])
    remarks = TextAreaField('Remarks', validators=[Optional()])
    capacity = IntegerField('Capacity', validators=[DataRequired(), NumberRange(min=1)])
    submit = SubmitField('Save')


# District Form
class DistrictForm(FlaskForm):
    name = StringField('District Name', validators=[DataRequired(), Length(min=2, max=100)])
    province = StringField('Province/Region', validators=[Optional(), Length(max=100)])
    remarks = TextAreaField('Remarks', validators=[Optional()])
    submit = SubmitField('Save')


# Assignment Forms
class AssignProjectToCompanyForm(FlaskForm):
    company_id = SelectField('Select Company', coerce=int, validators=[DataRequired()])
    project_id = SelectField('Select Project', coerce=int, validators=[DataRequired()])
    assign_date = DateField('Assign Date', format='%d-%m-%Y', validators=[DataRequired()])
    assign_remarks = TextAreaField('Remarks (Optional)')
    submit = SubmitField('Assign Project to Company')


class EditProjectAssignmentForm(FlaskForm):
    company_id = SelectField('Select Company', coerce=int, validators=[DataRequired()])
    project_id = SelectField('Project', coerce=int, validators=[DataRequired()])
    assign_date = DateField('Assign Date', format='%d-%m-%Y', validators=[DataRequired()])
    assign_remarks = TextAreaField('Assignment Remarks (Optional)', validators=[Optional()])
    submit = SubmitField('Update Assignment')	


class AssignProjectToDistrictForm(FlaskForm):
    project_id = SelectField('Select Project', coerce=int, validators=[DataRequired()])
    district_id = SelectField('Select District', coerce=int, validators=[DataRequired()])
    assign_date = DateField('Assign Date', format='%d-%m-%Y', validators=[DataRequired()])
    remarks = TextAreaField('Remarks (Optional)', validators=[Optional()])
    submit = SubmitField('Assign District to Project')


class AssignVehicleToDistrictForm(FlaskForm):
    project_id = SelectField('Select Project', coerce=int, validators=[DataRequired()])
    district_id = SelectField('Select District', coerce=int, validators=[DataRequired()])
    vehicle_id = SelectField('Select Vehicle', coerce=int, validators=[DataRequired()])
    assign_date = DateField('Assignment Date', format='%d-%m-%Y', validators=[DataRequired()])
    remarks = TextAreaField('Remarks (Optional)', validators=[Optional()])
    submit = SubmitField('Assign Vehicle to District')

class AssignVehicleToParkingForm(FlaskForm):
    project_id = SelectField('Select Project', coerce=int, validators=[DataRequired()])
    district_id = SelectField('Select District', coerce=int, validators=[DataRequired()])
    vehicle_id = SelectField('Select Vehicle', coerce=int, validators=[DataRequired()])
    parking_station_id = SelectField('Select Parking Station', coerce=int, validators=[DataRequired()])
    assign_date = DateField('Assign Date', format='%d-%m-%Y', validators=[DataRequired()])
    remarks = TextAreaField('Remarks (Optional)')
    submit = SubmitField('Finalize Parking Assignment')


class AssignDriverToVehicleForm(FlaskForm):
    project_id = SelectField(
        'Select Project',
        coerce=int,
        validators=[DataRequired()],
        choices=[(0, '-- Select Project --')]
    )
    
    district_id = SelectField(
        'Select District',
        coerce=int,
        validators=[DataRequired()],
        choices=[(0, '-- Select District --')]
    )
    
    vehicle_id = SelectField(
        'Select Vehicle',
        coerce=int,
        validators=[DataRequired()],
        choices=[(0, '-- Select Vehicle --')]
    )
    
    driver_id = SelectField(
        'Select Driver (Unassigned)',
        coerce=int,
        validators=[DataRequired()],
        choices=[(0, '-- Select Driver --')]
    )
    
    shift = SelectField(
        'Select Shift',
        choices=[('', '-- Select Shift --'), ('Morning', 'Morning'), ('Night', 'Night')],
        validators=[DataRequired(message="Shift is required")]
    )
    
    assign_date = DateField(
        'Assignment Date',
        format='%d-%m-%Y',
        validators=[DataRequired()],
        default=date.today
    )
    
    remarks = TextAreaField(
        'Remarks (Optional)',
        validators=[Optional()],
        render_kw={"rows": 2, "placeholder": "Any special notes about this assignment..."}
    )
    
    submit = SubmitField('Finalize Driver Assignment')


class ProjectTransferForm(FlaskForm):
    project_id = SelectField('Select Project to Transfer', coerce=int, validators=[DataRequired()])
    new_company_id = SelectField('Transfer to New Company', coerce=int, validators=[DataRequired()])
    transfer_date = DateField('Transfer Date', format='%d-%m-%Y', validators=[DataRequired()])
    remarks = TextAreaField('Transfer Remarks (Optional)', validators=[Optional()])
    submit = SubmitField('Confirm Transfer')

class VehicleTransferForm(FlaskForm):
    from_project_id = SelectField('From Project', coerce=int, validators=[Optional()])
    from_district_id = SelectField('From District', coerce=int, validators=[Optional()])
    vehicle_id = SelectField('Select Vehicle', coerce=int, validators=[DataRequired()])
    
    new_project_id = SelectField('Transfer to Project', coerce=int, validators=[DataRequired()])
    new_district_id = SelectField('Transfer to District', coerce=int, validators=[DataRequired()])
    new_parking_id = SelectField('Transfer to Parking (Optional)', coerce=int, validators=[Optional()])
    
    transfer_date = DateField('Transfer Date', format='%d-%m-%Y', validators=[DataRequired()])
    remarks = TextAreaField('Transfer Remarks (Optional)', validators=[Optional()])
    submit = SubmitField('Confirm Transfer')

class EditVehicleTransferForm(FlaskForm):
    new_project_id = SelectField('Transfer to Project', coerce=int, validators=[DataRequired()])
    new_district_id = SelectField('Transfer to District', coerce=int, validators=[DataRequired()])
    new_parking_id = SelectField('Transfer to Parking (Optional)', coerce=int, validators=[Optional()])
    transfer_date = DateField('Transfer Date', format='%d-%m-%Y', validators=[DataRequired()])
    remarks = TextAreaField('Transfer Remarks (Optional)', validators=[Optional()])
    submit = SubmitField('Update Transfer')


class DriverTransferForm(FlaskForm):
    from_project_id = SelectField('From Project', coerce=int, validators=[DataRequired()])
    from_district_id = SelectField('From District', coerce=int, validators=[DataRequired()])
    from_vehicle_id = SelectField('From Vehicle', coerce=int, validators=[DataRequired()])
    driver_id = SelectField('Select Driver', coerce=int, validators=[DataRequired()])
    
    new_project_id = SelectField('Transfer to Project', coerce=int, validators=[DataRequired()])
    new_district_id = SelectField('Transfer to District', coerce=int, validators=[DataRequired()])
    new_vehicle_id = SelectField('Transfer to Vehicle', coerce=int, validators=[DataRequired()])
    new_shift = SelectField('Select Shift', choices=[('', '-- Select Shift --')], validators=[DataRequired()])
    
    transfer_date = DateField('Transfer Date', format='%d-%m-%Y', validators=[DataRequired()])
    remarks = TextAreaField('Transfer Remarks (Optional)', validators=[Optional()])
    submit = SubmitField('Confirm Transfer')

class DriverJobLeftForm(FlaskForm):
    project_id = SelectField('Select Project', coerce=int, validators=[DataRequired()])
    district_id = SelectField('Select District', coerce=int, validators=[DataRequired()])
    vehicle_id = SelectField('Select Vehicle', coerce=int, validators=[DataRequired()])
    driver_id = SelectField('Select Driver (currently assigned)', coerce=int, validators=[DataRequired()])
    
    reason = SelectField('Leave Reason', 
        choices=[
            ('', '-- Select Reason --'),
            ('Resigned', 'Resigned'),
            ('Terminated', 'Terminated'),
            ('Retired', 'Retired'),
            ('Medical Grounds', 'Medical Grounds'),
            ('End of Contract', 'End of Contract'),
            ('Other', 'Other')
        ],
        validators=[DataRequired(message="Reason is required")]
    )
    
    other_reason = StringField('Other Reason (if selected)', 
                               validators=[Optional(), Length(max=200)])
    
    leave_date = DateField('Leave Date', 
                           format='%d-%m-%Y', 
                           default=date.today,
                           validators=[DataRequired()])
    
    remarks = TextAreaField('Remarks (Optional)', 
                            validators=[Optional(), Length(max=500)])
    
    submit = SubmitField('Confirm Job Left')

class DriverRejoinForm(FlaskForm):
    driver_id = SelectField('Select Driver to Rejoin', coerce=int, validators=[DataRequired()])
    
    project_id = SelectField('Project', coerce=int, validators=[DataRequired()])
    district_id = SelectField('District', coerce=int, validators=[DataRequired()])
    vehicle_id = SelectField('Vehicle', coerce=int, validators=[DataRequired()])
    shift = SelectField('Shift', choices=[], validators=[DataRequired()])  # dynamic
    
    rejoin_date = DateField('Rejoin Date', format='%d-%m-%Y', default=date.today, validators=[DataRequired()])
    remarks = TextAreaField('Rejoin Remarks', validators=[Optional()])
    
    submit = SubmitField('Confirm Rejoin')


# Driver Attendance
ATTENDANCE_STATUS_CHOICES = [
    ('Present', 'Present'),
    ('Absent', 'Absent'),
    ('Leave', 'Leave'),
    ('Late', 'Late'),
    ('Half-Day', 'Half-Day'),
    ('Off', 'Off'),
]


class DriverAttendanceFilterForm(FlaskForm):
    attendance_date = DateField('Date', format='%d-%m-%Y', default=date.today, validators=[DataRequired()])
    project_id = SelectField('Project (optional)', coerce=int, validators=[Optional()])
    district_id = SelectField('District (optional)', coerce=int, validators=[Optional()])
    submit = SubmitField('View / Mark Attendance')


class DriverAttendanceReportForm(FlaskForm):
    month = IntegerField('Month', validators=[DataRequired(), NumberRange(min=1, max=12)])
    year = IntegerField('Year', validators=[DataRequired(), NumberRange(min=2020, max=2030)])
    project_id = SelectField('Project (optional)', coerce=int, validators=[Optional()])
    district_id = SelectField('District (optional)', coerce=int, validators=[Optional()])
    search = StringField('Search', validators=[Optional(), Length(max=100)])
    submit = SubmitField('Show Report')


# Task Report (Daily Vehicle Task)
class TaskReportForm(FlaskForm):
    district_id = SelectField('District', coerce=int, validators=[DataRequired()], choices=[(0, '-- Select District --')])
    project_id = SelectField('Project', coerce=int, validators=[DataRequired()], choices=[(0, '-- Select Project --')])
    vehicle_id = SelectField('Vehicle No', coerce=int, validators=[DataRequired()], choices=[(0, '-- Select Vehicle --')])
    task_date = DateField('Date', format='%d-%m-%Y', validators=[DataRequired()],
                          render_kw={"class": "form-control datepicker"})
    close_reading = DecimalField('Close Reading', places=2, validators=[DataRequired(), NumberRange(min=0)])
    tasks_count = IntegerField("Task's", validators=[Optional(), NumberRange(min=0)], default=1)
    remarks = TextAreaField('Remarks', validators=[Optional()])
    submit = SubmitField('Save Task Entry')


class TaskReportFilterForm(FlaskForm):
    from_date = DateField('From Date', format='%d-%m-%Y', validators=[Optional()],
                          render_kw={"class": "form-control datepicker"})
    to_date = DateField('To Date', format='%d-%m-%Y', validators=[Optional()],
                        render_kw={"class": "form-control datepicker"})
    district_id = SelectField('District', coerce=int, validators=[Optional()], choices=[(0, '-- All Districts --')])
    project_id = SelectField('Project', coerce=int, validators=[Optional()], choices=[(0, '-- All Projects --')])
    submit = SubmitField('View Report')


class EmergencyTaskUploadForm(FlaskForm):
    task_date = DateField('Report Date', format='%d-%m-%Y', validators=[DataRequired()],
                          render_kw={"class": "form-control datepicker"})
    file = FileField('EmergencyTaskReport Excel', validators=[
        FileAllowed(['xlsx', 'xls'], 'Only Excel files (.xlsx, .xls) allowed')
    ])
    submit = SubmitField('Upload')


class VehicleMileageUploadForm(FlaskForm):
    task_date = DateField('Report Date', format='%d-%m-%Y', validators=[DataRequired()],
                          render_kw={"class": "form-control datepicker"})
    file = FileField('Vehicle Mileage Report Excel', validators=[
        FileAllowed(['xlsx', 'xls'], 'Only Excel files (.xlsx, .xls) allowed')
    ])
    submit = SubmitField('Upload')


class ParkingImportForm(FlaskForm):
    file = FileField('Parking Location Excel/CSV', validators=[
        FileAllowed(['xlsx', 'xls', 'csv'], 'Only Excel or CSV files allowed')
    ])
    submit = SubmitField('Import')


class TaskReportUploadBothForm(FlaskForm):
    task_date = DateField('Report Date', format='%d-%m-%Y', validators=[DataRequired()],
                          render_kw={"class": "form-control datepicker"})
    file_emergency = FileField('EmergencyTaskReport Excel', validators=[Optional(),
        FileAllowed(['xlsx', 'xls'], 'Only Excel allowed')])
    file_mileage = FileField('Vehicle Mileage Report Excel', validators=[Optional(),
        FileAllowed(['xlsx', 'xls'], 'Only Excel allowed')])
    submit = SubmitField('Upload Both')


class RedTaskFilterForm(FlaskForm):
    from_date = DateField('From Date', format='%d-%m-%Y', validators=[Optional()],
                          render_kw={"class": "form-control datepicker"})
    to_date = DateField('To Date', format='%d-%m-%Y', validators=[Optional()],
                        render_kw={"class": "form-control datepicker"})
    district_id = SelectField('District', coerce=int, validators=[Optional()], choices=[(0, '-- All Districts --')])
    project_id = SelectField('Project', coerce=int, validators=[Optional()], choices=[(0, '-- All Projects --')])
    submit = SubmitField('View Report')


class RedTaskForm(FlaskForm):
    task_date = DateField('Date', format='%d-%m-%Y', validators=[DataRequired()],
                         render_kw={"class": "form-control datepicker"})
    task_id = StringField('Task ID', validators=[Optional(), Length(max=50)], render_kw={"placeholder": "e.g. PHF-4642638"})
    district_id = SelectField('District', coerce=int, validators=[Optional()], choices=[])
    project_id = SelectField('Project', coerce=int, validators=[Optional()], choices=[])
    vehicle_id = SelectField('Vehicle', coerce=int, validators=[Optional()], choices=[])
    reason = TextAreaField('Reason of Red Task', validators=[Optional()], render_kw={"rows": 2})
    driver_name = StringField('Driver Name', validators=[Optional(), Length(max=100)])
    call_to_dto = RadioField('Call to DTO / according to CRC', choices=[('Yes', 'Yes'), ('No', 'No')], validators=[Optional()])
    dto_investigation = TextAreaField('According to DTO Investigation', validators=[Optional()], render_kw={"rows": 3})
    action = SelectField('Action Against Red Task', choices=[
        ('', '-- Select --'),
        ('No', 'No'),
        ('Fine', 'Fine'),
        ('Warning', 'Warning'),
        ('Other', 'Other'),
    ], validators=[Optional()])
    submit = SubmitField('Save')


class VehicleMoveWithoutTaskFilterForm(FlaskForm):
    from_date = DateField('From Date', format='%d-%m-%Y', validators=[Optional()],
                          render_kw={"class": "form-control datepicker"})
    to_date = DateField('To Date', format='%d-%m-%Y', validators=[Optional()],
                        render_kw={"class": "form-control datepicker"})
    district_id = SelectField('District', coerce=int, validators=[Optional()], choices=[(0, '-- All Districts --')])
    project_id = SelectField('Project', coerce=int, validators=[Optional()], choices=[(0, '-- All Projects --')])
    submit = SubmitField('View Report')


class VehicleMoveWithoutTaskForm(FlaskForm):
    move_date = DateField('Date', format='%d-%m-%Y', validators=[DataRequired()],
                          render_kw={"class": "form-control datepicker"})
    district_id = SelectField('District', coerce=int, validators=[Optional()], choices=[])
    project_id = SelectField('Project', coerce=int, validators=[Optional()], choices=[])
    vehicle_id = SelectField('Vehicle', coerce=int, validators=[Optional()], choices=[])
    km_in = DecimalField('KM IN', validators=[Optional()], render_kw={"class": "form-control", "step": "0.01"})
    km_out = DecimalField('KM Out', validators=[Optional()], render_kw={"class": "form-control", "step": "0.01"})
    d_km = DecimalField('D.Km', validators=[Optional()], render_kw={"class": "form-control", "step": "0.01"})
    logbook_task = IntegerField('Logbook Task', validators=[Optional()], default=0)
    emg_task = IntegerField('EMG-Task', validators=[Optional()], default=0)
    t_km = DecimalField('T.KM', validators=[Optional()], render_kw={"class": "form-control", "step": "0.01"})
    remarks = TextAreaField('Remarks', validators=[Optional()], render_kw={"rows": 2})
    fine = StringField('Fine', validators=[Optional(), Length(max=50)], render_kw={"placeholder": "No or amount e.g. 500"})
    submit = SubmitField('Save')


class PenaltyRecordFilterForm(FlaskForm):
    from_date = DateField('From Date', format='%d-%m-%Y', validators=[Optional()],
                          render_kw={"class": "form-control datepicker"})
    to_date = DateField('To Date', format='%d-%m-%Y', validators=[Optional()],
                        render_kw={"class": "form-control datepicker"})
    district_id = SelectField('District', coerce=int, validators=[Optional()], choices=[(0, '-- All Districts --')])
    project_id = SelectField('Project', coerce=int, validators=[Optional()], choices=[(0, '-- All Projects --')])
    submit = SubmitField('View Report')


class PenaltyRecordForm(FlaskForm):
    record_date = DateField('Date', format='%d-%m-%Y', validators=[DataRequired()],
                           render_kw={"class": "form-control datepicker"})
    district_id = SelectField('District', coerce=int, validators=[Optional()], choices=[])
    project_id = SelectField('Project', coerce=int, validators=[Optional()], choices=[])
    vehicle_id = SelectField('Vehicle', coerce=int, validators=[Optional()], choices=[])
    driver_id = SelectField('Driver', coerce=int, validators=[Optional()], choices=[])
    fine = StringField('Fine', validators=[Optional(), Length(max=100)], render_kw={"placeholder": "Amount or description"})
    remarks = TextAreaField('Remarks', validators=[Optional()], render_kw={"rows": 3})
    submit = SubmitField('Save')


# ────────────────────────────────────────────────
# Fuel Expense
# ────────────────────────────────────────────────
PAYMENT_TYPE_CHOICES = [
    ('', '-- Select --'),
    ('Cash', 'Cash'),
    ('Credit', 'Credit'),
    ('Tp/Card', 'Tp/Card'),
    ('Shl/Card', 'Shl/Card'),
]

FUEL_TYPE_CHOICES = [
    ('', '-- Select --'),
    ('Diesel', 'Diesel'),
    ('Super', 'Super (Petrol)'),
]

OIL_PAYMENT_TYPE_CHOICES = [
    ('', '-- Select --'),
    ('Card', 'Card'),
    ('Credit', 'Credit'),
    ('Cash', 'Cash'),
    ('In Hand Stock', 'In Hand Stock'),
]

PARTY_TYPE_CHOICES = [
    ('Pump', 'Pump (Fuel Pump Name)'),
    ('Workshop', 'Workshop'),
    ('Spare parts shop', 'Spare parts shop'),
]


class PartyForm(FlaskForm):
    name = StringField('Party Name', validators=[DataRequired(), Length(max=150)], render_kw={"placeholder": "Pump / Workshop / Shop name"})
    party_type = SelectField('Type', choices=PARTY_TYPE_CHOICES, validators=[DataRequired()])
    contact = StringField('Contact', validators=[Optional(), Length(max=100)])
    address = StringField('Address', validators=[Optional(), Length(max=255)])
    remarks = TextAreaField('Remarks', validators=[Optional()], render_kw={"rows": 2})
    submit = SubmitField('Save')


class ProductForm(FlaskForm):
    name = StringField('Product Name', validators=[DataRequired(), Length(max=150)], render_kw={"placeholder": "e.g. Diesel, Engine Oil, Filter"})
    used_in_forms = SelectMultipleField('Used in Form', choices=[
        ('Fueling', 'Fueling Form'),
        ('Oil', 'Oil Form'),
        ('Maintenance', 'Maintenance Form'),
    ], validators=[Optional()])
    remarks = TextAreaField('Remarks', validators=[Optional()], render_kw={"rows": 2})
    submit = SubmitField('Save')


class FuelExpenseFilterForm(FlaskForm):
    from_date = DateField('From Date', format='%d-%m-%Y', validators=[Optional()],
                          render_kw={"class": "form-control datepicker"})
    to_date = DateField('To Date', format='%d-%m-%Y', validators=[Optional()],
                        render_kw={"class": "form-control datepicker"})
    district_id = SelectField('District', coerce=int, validators=[Optional()], choices=[(0, '-- Select District --')])
    project_id = SelectField('Project', coerce=int, validators=[Optional()], choices=[(0, '-- Select Project --')])
    vehicle_id = SelectField('Vehicle', coerce=int, validators=[Optional()], choices=[(0, '-- All Vehicles --')])
    submit = SubmitField('Apply Filter')


class FuelExpenseForm(FlaskForm):
    district_id = SelectField('District', coerce=int, validators=[Optional()], choices=[(0, '-- Select District --')])
    project_id = SelectField('Project', coerce=int, validators=[Optional()], choices=[(0, '-- Select Project --')])
    vehicle_id = SelectField('Vehicle No', coerce=int, validators=[DataRequired()], choices=[])
    fueling_date = DateField('Fueling Date', format='%d-%m-%Y', validators=[DataRequired()],
                             render_kw={"class": "form-control datepicker"})
    card_swipe_date = DateField('Card Swipe Date', format='%d-%m-%Y', validators=[Optional()],
                                 render_kw={"class": "form-control datepicker"})
    payment_type = SelectField('Payment Type', choices=PAYMENT_TYPE_CHOICES, validators=[Optional()])
    slip_no = StringField('Slip No', validators=[Optional(), Length(max=50)], render_kw={"placeholder": "e.g. 4270"})
    fuel_type = SelectField('Fuel Type', choices=FUEL_TYPE_CHOICES, validators=[Optional()])
    fuel_pump_id = SelectField('Fuel Pump Name', coerce=int, validators=[Optional()], choices=[(0, '-- Select Pump --')])
    previous_reading = DecimalField('Previous Reading', validators=[Optional()], render_kw={"class": "form-control", "step": "0.01", "readonly": True})
    current_reading = DecimalField('Current Reading', validators=[DataRequired()], render_kw={"class": "form-control", "step": "0.01"})
    amount = DecimalField('Amount', validators=[Optional()], render_kw={"class": "form-control", "step": "0.01"})
    fuel_price = DecimalField('Fuel Price', validators=[Optional()], render_kw={"class": "form-control", "step": "0.01"})
    submit = SubmitField('Save')


class OilExpenseFilterForm(FlaskForm):
    from_date = DateField('From Date', format='%d-%m-%Y', validators=[Optional()],
                          render_kw={"class": "form-control datepicker"})
    to_date = DateField('To Date', format='%d-%m-%Y', validators=[Optional()],
                        render_kw={"class": "form-control datepicker"})
    district_id = SelectField('District', coerce=int, validators=[Optional()], choices=[(0, '-- Select District --')])
    project_id = SelectField('Project', coerce=int, validators=[Optional()], choices=[(0, '-- Select Project --')])
    vehicle_id = SelectField('Vehicle', coerce=int, validators=[Optional()], choices=[(0, '-- All Vehicles --')])
    submit = SubmitField('Apply Filter')


class OilExpenseForm(FlaskForm):
    district_id = SelectField('District', coerce=int, validators=[Optional()], choices=[(0, '-- Select District --')])
    project_id = SelectField('Project', coerce=int, validators=[Optional()], choices=[(0, '-- Select Project --')])
    vehicle_id = SelectField('Vehicle No', coerce=int, validators=[DataRequired()], choices=[])
    expense_date = DateField('Oil Change Date', format='%d-%m-%Y', validators=[DataRequired()],
                             render_kw={"class": "form-control datepicker"})
    card_swipe_date = DateField('Card Swipe Date', format='%d-%m-%Y', validators=[Optional()],
                                render_kw={"class": "form-control datepicker"})
    previous_reading = DecimalField('Previous Reading', validators=[Optional()],
                                    render_kw={"class": "form-control", "step": "0.01", "readonly": True})
    current_reading = DecimalField('Current Reading', validators=[Optional()],
                                   render_kw={"class": "form-control", "step": "0.01"})
    remarks = TextAreaField('Remarks', validators=[Optional()], render_kw={"rows": 2})
    submit = SubmitField('Save')


class MaintenanceExpenseFilterForm(FlaskForm):
    from_date = DateField('From Date', format='%d-%m-%Y', validators=[Optional()],
                          render_kw={"class": "form-control datepicker"})
    to_date = DateField('To Date', format='%d-%m-%Y', validators=[Optional()],
                        render_kw={"class": "form-control datepicker"})
    district_id = SelectField('District', coerce=int, validators=[Optional()], choices=[(0, '-- Select District --')])
    project_id = SelectField('Project', coerce=int, validators=[Optional()], choices=[(0, '-- Select Project --')])
    vehicle_id = SelectField('Vehicle', coerce=int, validators=[Optional()], choices=[(0, '-- All Vehicles --')])
    submit = SubmitField('Apply Filter')


class MaintenanceExpenseForm(FlaskForm):
    district_id = SelectField('District', coerce=int, validators=[Optional()], choices=[(0, '-- Select District --')])
    project_id = SelectField('Project', coerce=int, validators=[Optional()], choices=[(0, '-- Select Project --')])
    vehicle_id = SelectField('Vehicle No', coerce=int, validators=[DataRequired()], choices=[])
    expense_date = DateField('Date', format='%d-%m-%Y', validators=[DataRequired()],
                             render_kw={"class": "form-control datepicker"})
    previous_reading = DecimalField('Previous Reading', validators=[Optional()],
                                    render_kw={"class": "form-control", "step": "0.01", "readonly": True})
    current_reading = DecimalField('Current Reading', validators=[Optional()],
                                   render_kw={"class": "form-control", "step": "0.01"})
    remarks = TextAreaField('Remarks', validators=[Optional()], render_kw={"rows": 2})
    submit = SubmitField('Save')