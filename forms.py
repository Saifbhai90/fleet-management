from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import (
    StringField, TextAreaField, DateField, IntegerField,
    SelectField, SelectMultipleField, SubmitField, HiddenField,
    RadioField, DecimalField, BooleanField, PasswordField
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
    engine_no = StringField('Engine No#', validators=[DataRequired(), Length(max=50)])
    chassis_no = StringField('Chassis No#', validators=[DataRequired(), Length(max=50)])
    vehicle_type = SelectField(
        'Vehicle Type',
        choices=[
            ('', '-- Select Vehicle Type --'),
            ('Ambulance', 'Ambulance'),
            ('Passanger', 'Passanger'),
            ('USG+Passanger', 'USG+Passanger'),
            ('USG', 'USG'),
        ],
        validators=[DataRequired()]
    )
    driver_capacity = IntegerField('Driver Capacity', validators=[DataRequired(), NumberRange(min=1)])

    phone_no = StringField('Vehicle Phone No', validators=[Optional(), Length(max=20)])
    active_date = DateField(
        'Active Date',
        format='%d-%m-%Y',
        render_kw={"class": "form-control datepicker"},
        validators=[DataRequired()]
    )
    remarks = TextAreaField('Remarks', validators=[Optional()])
    document = FileField('Vehicle Documents (PDF)', validators=[Optional(),
        FileAllowed(['pdf'], 'Only PDF files allowed')])
    submit = SubmitField('Save')


class VehicleImportForm(FlaskForm):
    file = FileField('Vehicle Excel/CSV', validators=[
        FileAllowed(['xlsx', 'xls', 'csv'], 'Only Excel or CSV files allowed')
    ])
    submit = SubmitField('Import')


# Driver Form
class DriverForm(FlaskForm):
    driver_id = StringField('Driver ID', validators=[DataRequired()])
    post = SelectField('Post', choices=[], validators=[DataRequired()])
    application_date = DateField('Application Date', format='%d-%m-%Y', validators=[DataRequired()])
    name = StringField('Full Name', validators=[DataRequired()])
    father_name = StringField('Father Name', validators=[DataRequired()])
    dob = DateField('Date of Birth', format='%d-%m-%Y', validators=[DataRequired()])
    phone1 = StringField('Phone No 1', validators=[DataRequired(), Regexp(r'^03[0-9]{2}-[0-9]{7}$', message='Format: 0300-1110810')], render_kw={"placeholder": "0300-1110810"})
    phone2 = StringField('Phone No 2', validators=[Optional(), Regexp(r'^03[0-9]{2}-[0-9]{7}$', message='Format: 0300-1110810')], render_kw={"placeholder": "03xx-xxxxxxx"})
    emergency_no = StringField('Emergency No', validators=[DataRequired(), Regexp(r'^03[0-9]{2}-[0-9]{7}$', message='Format: 03xx-xxxxxxx')], render_kw={"placeholder": "03xx-xxxxxxx"})
    address = TextAreaField('Address', validators=[DataRequired()])
    education = SelectField('Education', choices=[
        ('', '-- Select Education --'),
        ('Illiterate', 'Illiterate (An-Parha)'),
        ('Primary', 'Primary (5th)'),
        ('Middle', 'Middle (8th)'),
        ('Matric', 'Matric (10th)'),
        ('Intermediate', 'Intermediate (12th)'),
        ('Graduate', 'Graduate (14th)'),
        ('Master', 'Master (16th)'),
        ('M.Phil', 'M.Phil (18th)'),
        ('PhD', 'PhD'),
        ('Hafiz-e-Quran', 'Hafiz-e-Quran'),
        ('Other', 'Other'),
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
    shirt_size = SelectField('Shirt Size', choices=[
        ('', '-- Size --'), ('2XS', '2XS'), ('XS', 'XS'), ('S', 'S'), ('M', 'M'),
        ('L', 'L'), ('XL', 'XL'), ('XXL', 'XXL'), ('3XL', '3XL'), ('4XL', '4XL')
    ])
    trouser_size = SelectField('Trouser Size', choices=[
        ('', '-- Size --'), ('26', '26'), ('28', '28'), ('30', '30'), ('32', '32'),
        ('34', '34'), ('36', '36'), ('38', '38'), ('40', '40'), ('42', '42'), ('44', '44')
    ])
    jacket_size = SelectField('Jacket Size', choices=[
        ('', '-- Size --'), ('2XS', '2XS'), ('XS', 'XS'), ('S', 'S'), ('M', 'M'),
        ('L', 'L'), ('XL', 'XL'), ('XXL', 'XXL'), ('3XL', '3XL'), ('4XL', '4XL')
    ])

    photo = FileField('Driver Photo', validators=[Optional(),
        FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'webp'], 'Only image files allowed')])
    cnic_front = FileField('CNIC Front Photo', validators=[Optional(),
        FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'webp'], 'Only image files allowed')])
    cnic_back = FileField('CNIC Back Photo', validators=[Optional(),
        FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'webp'], 'Only image files allowed')])
    license_front = FileField('License Front Photo', validators=[Optional(),
        FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'webp'], 'Only image files allowed')])
    license_back = FileField('License Back Photo', validators=[Optional(),
        FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'webp'], 'Only image files allowed')])
    document = FileField('Complete Driver File (PDF)', validators=[Optional(),
        FileAllowed(['pdf'], 'Only PDF allowed')])

    submit = SubmitField('Save Driver Data')

    def validate_cnic_expiry_date(self, field):
        if field.data and self.cnic_issue_date.data:
            if field.data <= self.cnic_issue_date.data:
                raise ValidationError('CNIC Expiry Date must be after Issue Date.')

    def validate_license_expiry_date(self, field):
        if field.data and self.license_issue_date.data:
            if field.data <= self.license_issue_date.data:
                raise ValidationError('License Expiry Date must be after Issue Date.')

    def validate_dob(self, field):
        if field.data:
            from datetime import date
            today = date.today()
            if field.data >= today:
                raise ValidationError('Date of Birth cannot be today or in the future.')
            age = (today - field.data).days // 365
            if age < 18:
                raise ValidationError('Driver must be at least 18 years old.')


class DriverImportForm(FlaskForm):
    file = FileField('Driver Excel/CSV', validators=[
        FileAllowed(['xlsx', 'xls', 'csv'], 'Only Excel or CSV files allowed')
    ])
    submit = SubmitField('Import')


class EmployeeImportForm(FlaskForm):
    file = FileField('Employee Excel/CSV', validators=[
        FileAllowed(['xlsx', 'xls', 'csv'], 'Only Excel or CSV files allowed')
    ])
    submit = SubmitField('Import')


# Parking Form
class ParkingForm(FlaskForm):
    name = StringField('Parking Station Name', validators=[DataRequired(), Length(max=100)])
    district = StringField('District Name', validators=[DataRequired(), Length(max=100)])
    tehsil = StringField('Tehsil Name', validators=[DataRequired(), Length(max=100)])
    mouza = StringField('Mouza Name', validators=[Optional(), Length(max=100)])
    uc_name = StringField('UC Name', validators=[Optional(), Length(max=100)])
    create_date = DateField('Create Date', format='%d-%m-%Y',
                            render_kw={"class": "form-control datepicker"},
                            validators=[DataRequired()])
    address_location = TextAreaField('Address/Location Description', validators=[Optional()])
    remarks = TextAreaField('Remarks', validators=[Optional()])
    capacity = IntegerField('Capacity', validators=[DataRequired(), NumberRange(min=1)])
    latitude = DecimalField('Latitude', places=6, validators=[Optional()], render_kw={"placeholder": "e.g. 31.520370"})
    longitude = DecimalField('Longitude', places=6, validators=[Optional()], render_kw={"placeholder": "e.g. 74.358749"})
    submit = SubmitField('Save')


# District Form
class DistrictForm(FlaskForm):
    name = StringField('District Name', validators=[DataRequired(), Length(min=2, max=100)])
    province = StringField('Province/Region', validators=[Optional(), Length(max=100)])
    remarks = TextAreaField('Remarks', validators=[Optional()])
    submit = SubmitField('Save')


# Assignment Forms
class AssignProjectToCompanyForm(FlaskForm):
    company_id = SelectField(
        'Select Company',
        coerce=int,
        validators=[DataRequired(), NumberRange(min=1, message='Please select a company.')],
        choices=[(0, '-- Select Company --')]
    )
    project_id = SelectField(
        'Select Project',
        coerce=int,
        validators=[DataRequired(), NumberRange(min=1, message='Please select a project.')],
        choices=[(0, '-- Select Project --')]
    )
    assign_date = DateField('Assign Date', format='%d-%m-%Y', validators=[DataRequired()])
    assign_remarks = TextAreaField('Remarks (Optional)')
    submit = SubmitField('Assign Project to Company')


class EditProjectAssignmentForm(FlaskForm):
    company_id = SelectField('Select Company', coerce=int, validators=[DataRequired()])
    project_id = SelectField('Project', coerce=int, validators=[DataRequired()])
    assign_date = DateField('Assign Date', format='%Y-%m-%d', validators=[DataRequired()])  # HTML5 date input uses YYYY-MM-DD
    assign_remarks = TextAreaField('Assignment Remarks (Optional)', validators=[Optional()])
    submit = SubmitField('Update Assignment')	


class AssignProjectToDistrictForm(FlaskForm):
    project_id = SelectField(
        'Select Project',
        coerce=int,
        validators=[DataRequired(), NumberRange(min=1, message='Please select a project.')],
        choices=[(0, '-- Select Project --')]
    )
    district_id = SelectField(
        'Select District',
        coerce=int,
        validators=[DataRequired(), NumberRange(min=1, message='Please select a district.')],
        choices=[(0, '-- Select District --')]
    )
    assign_date = DateField('Assign Date', format='%d-%m-%Y', validators=[DataRequired()])
    remarks = TextAreaField('Remarks (Optional)', validators=[Optional()])
    submit = SubmitField('Assign District to Project')


class AssignVehicleToDistrictForm(FlaskForm):
    project_id = SelectField('Select Project', coerce=int, validators=[DataRequired(), NumberRange(min=1, message='Please select a project.')])
    district_id = SelectField('Select District', coerce=int, validators=[DataRequired(), NumberRange(min=1, message='Please select a district.')])
    vehicle_id = SelectField('Select Vehicle', coerce=int, validators=[DataRequired(), NumberRange(min=1, message='Please select a vehicle.')])
    assign_date = DateField('Assignment Date', format='%d-%m-%Y', validators=[DataRequired()])
    remarks = TextAreaField('Remarks (Optional)', validators=[Optional()])
    submit = SubmitField('Assign Vehicle to District')

class AssignVehicleToParkingForm(FlaskForm):
    project_id = SelectField('Select Project', coerce=int, validators=[DataRequired()])
    district_id = SelectField('Select District', coerce=int, validators=[DataRequired()])
    vehicle_id = SelectField('Select Vehicle', coerce=int, validators=[DataRequired()])
    parking_station_id = SelectField('Select Parking Station', coerce=int, validators=[DataRequired(), NumberRange(min=1, message='Please select a parking station.')])
    assign_date = DateField('Assign Date', format='%d-%m-%Y', validators=[DataRequired()])
    remarks = TextAreaField('Remarks (Optional)')
    submit = SubmitField('Finalize Parking Assignment')


class AssignDriverToVehicleForm(FlaskForm):
    project_id = SelectField(
        'Select Project',
        coerce=int,
        validators=[DataRequired(), NumberRange(min=1, message='Please select a project.')],
        choices=[(0, '-- Select Project --')]
    )
    
    district_id = SelectField(
        'Select District',
        coerce=int,
        validators=[DataRequired(), NumberRange(min=1, message='Please select a district.')],
        choices=[(0, '-- Select District --')]
    )
    
    vehicle_id = SelectField(
        'Select Vehicle',
        coerce=int,
        validators=[DataRequired(), NumberRange(min=1, message='Please select a vehicle.')],
        choices=[(0, '-- Select Vehicle --')]
    )
    
    driver_id = SelectField(
        'Select Driver (Unassigned)',
        coerce=int,
        validators=[DataRequired(), NumberRange(min=1, message='Please select a driver.')],
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
        validators=[DataRequired(message='Assign date is required.')]
    )
    
    remarks = TextAreaField(
        'Remarks (Optional)',
        validators=[Optional()],
        render_kw={"rows": 2, "placeholder": "Any special notes about this assignment..."}
    )
    
    submit = SubmitField('Finalize Driver Assignment')

    def validate_assign_date(self, field):
        """Future date par driver assignment allow na karein."""
        if field.data and field.data > date.today():
            raise ValidationError('Assignment date cannot be in the future.')


class ProjectTransferForm(FlaskForm):
    project_id = SelectField('Select Project to Transfer', coerce=int, validators=[DataRequired(message='Please select a project.')], choices=[])
    new_company_id = SelectField('Transfer to New Company', coerce=int, validators=[DataRequired(message='Please select a company.')], choices=[])
    transfer_date = DateField('Transfer Date', format='%d-%m-%Y', validators=[DataRequired(message='Please select transfer date.')], render_kw={'placeholder': 'Select date'})
    remarks = TextAreaField('Transfer Remarks (Optional)', validators=[Optional()])
    submit = SubmitField('Confirm Transfer')

class VehicleTransferForm(FlaskForm):
    from_project_id = SelectField(
        'From Project',
        coerce=int,
        validators=[
            DataRequired(message='Please select project.'),
            NumberRange(min=1, message='Please select project.')
        ],
        choices=[(0, '-- Select Project --')]
    )
    from_district_id = SelectField(
        'From District',
        coerce=int,
        validators=[
            DataRequired(message='Please select district.'),
            NumberRange(min=1, message='Please select district.')
        ],
        choices=[(0, '-- Select District --')]
    )
    vehicle_id = SelectField('Select Vehicle', coerce=int, validators=[DataRequired(message='Please select vehicle.'), NumberRange(min=1, message='Please select a vehicle.')], choices=[(0, '-- Select Vehicle --')])
    
    new_project_id = SelectField('Transfer to Project', coerce=int, validators=[DataRequired(message='Please select new project.'), NumberRange(min=1, message='Please select new project.')], choices=[(0, '-- Select Project --')])
    new_district_id = SelectField('Transfer to District', coerce=int, validators=[DataRequired(message='Please select new district.'), NumberRange(min=1, message='Please select new district.')], choices=[(0, '-- Select District --')])
    new_parking_id = SelectField(
        'Transfer to Parking',
        coerce=int,
        validators=[
            DataRequired(message='Please select parking.'),
            NumberRange(min=1, message='Please select parking.')
        ],
        choices=[(0, '-- Select Parking --')]
    )
    
    transfer_date = DateField('Transfer Date', format='%d-%m-%Y', validators=[DataRequired(message='Please select transfer date.')], render_kw={'placeholder': 'Select date'})
    remarks = TextAreaField('Transfer Remarks (Optional)', validators=[Optional()])
    submit = SubmitField('Confirm Transfer')

    def validate_transfer_date(self, field):
        """Future date par vehicle transfer allow na karein."""
        if field.data and field.data > date.today():
            raise ValidationError('Transfer date cannot be in the future.')

class EditVehicleTransferForm(FlaskForm):
    new_project_id = SelectField('Transfer to Project', coerce=int, validators=[DataRequired(message='Please select new project.'), NumberRange(min=1, message='Please select new project.')], choices=[(0, '-- Select Project --')])
    new_district_id = SelectField('Transfer to District', coerce=int, validators=[DataRequired(message='Please select new district.'), NumberRange(min=1, message='Please select new district.')], choices=[(0, '-- Select District --')])
    new_parking_id = SelectField('Transfer to Parking (Optional)', coerce=int, validators=[Optional()], choices=[(0, '-- No Parking --')])
    transfer_date = DateField('Transfer Date', format='%d-%m-%Y', validators=[DataRequired(message='Please select transfer date.')], render_kw={'placeholder': 'Select date'})
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
    
    transfer_date = DateField('Transfer Date', format='%d-%m-%Y', validators=[DataRequired(message='Please select transfer date.')], render_kw={'placeholder': 'Select date'})
    remarks = TextAreaField('Transfer Remarks (Optional)', validators=[Optional()])
    submit = SubmitField('Confirm Transfer')

    def validate_transfer_date(self, field):
        """Future date par transfer allow na karein."""
        if field.data and field.data > date.today():
            raise ValidationError('Transfer date cannot be in the future.')

class DriverJobLeftForm(FlaskForm):
    project_id = SelectField('Select Project', coerce=int, validators=[DataRequired(message='Please select project.')])
    district_id = SelectField('Select District', coerce=int, validators=[DataRequired(message='Please select district.')])
    vehicle_id = SelectField('Select Vehicle', coerce=int, validators=[DataRequired(message='Please select vehicle.')])
    driver_id = SelectField('Select Driver (currently assigned)', coerce=int, validators=[DataRequired(message='Please select driver.')])
    
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
        validators=[DataRequired(message="Please select reason.")]
    )
    
    other_reason = StringField('Other Reason (if selected)', 
                               validators=[Optional(), Length(max=200)])
    
    leave_date = DateField(
        'Leave Date',
        format='%d-%m-%Y',
        validators=[DataRequired(message='Please select leave date.')],
        render_kw={'placeholder': 'Select date', 'class': 'form-control datepicker'}
    )
    
    remarks = TextAreaField('Remarks (Optional)', 
                            validators=[Optional(), Length(max=500)])
    
    submit = SubmitField('Confirm Job Left')

    def validate_leave_date(self, field):
        """Future date par driver job left allow na karein."""
        if field.data and field.data > date.today():
            raise ValidationError('Leave date cannot be in the future.')

class DriverRejoinForm(FlaskForm):
    driver_id = SelectField('Select Driver to Rejoin', coerce=int, validators=[DataRequired(message='Please select driver.')])
    
    project_id = SelectField('Project', coerce=int, validators=[DataRequired(message='Please select project.')])
    district_id = SelectField('District', coerce=int, validators=[DataRequired(message='Please select district.')])
    vehicle_id = SelectField('Vehicle', coerce=int, validators=[DataRequired(message='Please select vehicle.')])
    shift = SelectField('Shift', choices=[], validators=[DataRequired(message='Please select shift.')])  # dynamic
    
    rejoin_date = DateField(
        'Rejoin Date',
        format='%d-%m-%Y',
        validators=[DataRequired(message='Please select rejoin date.')],
        render_kw={'placeholder': 'Select date', 'class': 'form-control datepicker'}
    )
    remarks = TextAreaField('Rejoin Remarks', validators=[Optional()])
    
    submit = SubmitField('Confirm Rejoin')

    def validate_rejoin_date(self, field):
        """Future date par driver rejoin allow na karein."""
        if field.data and field.data > date.today():
            raise ValidationError('Rejoin date cannot be in the future.')


# Driver Attendance (Leave / Late / Half Day / Off form — Present & Absent removed)
ATTENDANCE_STATUS_CHOICES = [
    ('Leave', 'Leave'),
    ('Late', 'Late'),
    ('Half-Day', 'Half-Day'),
    ('Off', 'Off'),
]


class DriverAttendanceFilterForm(FlaskForm):
    attendance_date = DateField('Date', format='%d-%m-%Y', default=date.today, validators=[DataRequired()])
    project_id = SelectField('Project (optional)', coerce=int, validators=[Optional()])
    district_id = SelectField('District (optional)', coerce=int, validators=[Optional()])
    vehicle_id = SelectField('Vehicle (optional)', coerce=int, validators=[Optional()])
    shift = SelectField('Shift (optional)', validators=[Optional()])
    submit = SubmitField('Load')


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


class PartyImportForm(FlaskForm):
    file = FileField('Party Excel/CSV', validators=[
        FileAllowed(['xlsx', 'xls', 'csv'], 'Only Excel or CSV files allowed')
    ])
    submit = SubmitField('Import')


class ProductImportForm(FlaskForm):
    file = FileField('Product Excel/CSV', validators=[
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
    district_id = SelectField('District', coerce=int, validators=[Optional()], choices=[], default=None)
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


class EmployeePostForm(FlaskForm):
    short_name = StringField('Post Short Name', validators=[DataRequired(), Length(min=1, max=50)])
    full_name = StringField('Post Full Name', validators=[DataRequired(), Length(min=2, max=150)])
    role_id = SelectField('Access Role (for User Management)', coerce=int, validators=[Optional()], choices=[])
    remarks = TextAreaField('Remarks', validators=[Optional()], render_kw={"rows": 2})
    submit = SubmitField('Save')


class EmployeeForm(FlaskForm):
    code = StringField('Employee Code', validators=[Length(max=20)])
    name = StringField('Employee Name', validators=[DataRequired(), Length(max=100)])
    post_id = SelectField('Employee Post', coerce=int, validators=[DataRequired()], choices=[])
    department = StringField('Department', validators=[DataRequired(), Length(max=100)])

    father_name = StringField('Father Name', validators=[DataRequired(), Length(max=100)])
    place_of_birth = StringField('Place of Birth', validators=[DataRequired(), Length(max=100)])
    dob = DateField('Date of Birth', format='%d-%m-%Y', validators=[DataRequired()],
                    render_kw={"class": "form-control datepicker"})
    education = SelectField('Education', choices=[
        ('', '-- Select Education --'),
        ('Middle', 'Middle'),
        ('Matric', 'Matric'),
        ('Intermediate', 'Intermediate'),
        ('Graduate', 'Graduate'),
        ('Masters', 'Masters'),
        ('Other', 'Other'),
    ], validators=[DataRequired()])
    marital_status = SelectField('Marital Status', choices=[
        ('Single', 'Single'),
        ('Married', 'Married'),
        ('Divorced', 'Divorced'),
        ('Widowed', 'Widowed'),
    ], validators=[DataRequired()])
    cnic_no = StringField('CNIC No', validators=[
        DataRequired(),
        Regexp(r'^[0-9]{5}-[0-9]{7}-[0-9]{1}$', message='Format: 32304-1111111-5')
    ], render_kw={"placeholder": "32304-1111111-5"})
    district = StringField('District', validators=[DataRequired(), Length(max=100)],
                           render_kw={"list": "districtOptions"})
    address = TextAreaField('Address', validators=[DataRequired()], render_kw={"rows": 2})

    phone1 = StringField('Phone No 1', validators=[DataRequired(), Length(max=20)], render_kw={"placeholder": "03xx-xxxxxxx"})
    phone2 = StringField('Phone No 2', validators=[DataRequired(), Length(max=20)], render_kw={"placeholder": "03xx-xxxxxxx"})
    email = StringField('Email', validators=[Optional(), Email(), Length(max=120)])

    joining_date = DateField('Joining Date', format='%d-%m-%Y',
                             validators=[DataRequired()],
                             render_kw={"class": "form-control datepicker"})
    status = SelectField('Status', choices=[
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
        ('Left', 'Left'),
    ], default='Active', validators=[DataRequired()])

    bank_name = StringField('Bank Name', validators=[Optional(), Length(max=100)])
    account_no = StringField('Account No', validators=[Optional(), Length(max=50)])
    account_title = StringField('Account Title', validators=[Optional(), Length(max=100)])

    remarks = TextAreaField('Remarks', validators=[Optional()],
                            render_kw={"rows": 3, "placeholder": "Previous job experience / other notes"})

    project_ids = SelectMultipleField('Assign Projects', coerce=int, validators=[Optional()], choices=[], render_kw={"class": "form-select form-select-sm", "size": "5"})
    district_ids = SelectMultipleField('Assign Districts', coerce=int, validators=[Optional()], choices=[], render_kw={"class": "form-select form-select-sm", "size": "5"})

    submit = SubmitField('Save Employee')


# Step-wise forms for Module Tabs (save step → then next tab)
class EmployeeFormStep1(FlaskForm):
    """Tab 1: Basic & Personal Info only."""
    code = StringField('Employee Code', validators=[Length(max=20)])
    name = StringField('Employee Name', validators=[DataRequired(), Length(max=100)])
    post_id = SelectField('Employee Post', coerce=int, validators=[DataRequired()], choices=[])
    department = StringField('Department', validators=[DataRequired(), Length(max=100)])
    father_name = StringField('Father Name', validators=[DataRequired(), Length(max=100)])
    place_of_birth = StringField('Place of Birth', validators=[DataRequired(), Length(max=100)])
    dob = DateField('Date of Birth', format='%d-%m-%Y', validators=[DataRequired()],
                    render_kw={"class": "form-control datepicker"})
    education = SelectField('Education', choices=[
        ('', '-- Select Education --'),
        ('Middle', 'Middle'), ('Matric', 'Matric'), ('Intermediate', 'Intermediate'),
        ('Graduate', 'Graduate'), ('Masters', 'Masters'), ('Other', 'Other'),
    ], validators=[DataRequired()])
    marital_status = SelectField('Marital Status', choices=[
        ('Single', 'Single'), ('Married', 'Married'), ('Divorced', 'Divorced'), ('Widowed', 'Widowed'),
    ], validators=[DataRequired()])
    cnic_no = StringField('CNIC No', validators=[
        DataRequired(),
        Regexp(r'^[0-9]{5}-[0-9]{7}-[0-9]{1}$', message='Format: 32304-1111111-5')
    ], render_kw={"placeholder": "32304-1111111-5"})
    district = StringField('District', validators=[DataRequired(), Length(max=100)], render_kw={"list": "districtOptions"})
    address = TextAreaField('Address', validators=[DataRequired()], render_kw={"rows": 2})
    joining_date = DateField('Joining Date', format='%d-%m-%Y', validators=[DataRequired()],
                             render_kw={"class": "form-control datepicker"})


class EmployeeFormStep2(FlaskForm):
    """Tab 2: Contact, Job & Bank only."""
    phone1 = StringField('Phone No 1', validators=[DataRequired(), Length(max=20)], render_kw={"placeholder": "03xx-xxxxxxx"})
    phone2 = StringField('Phone No 2', validators=[DataRequired(), Length(max=20)], render_kw={"placeholder": "03xx-xxxxxxx"})
    email = StringField('Email', validators=[Optional(), Email(), Length(max=120)])
    status = SelectField('Status', choices=[
        ('Active', 'Active'), ('Inactive', 'Inactive'), ('Left', 'Left'),
    ], default='Active', validators=[DataRequired()])
    bank_name = StringField('Bank Name', validators=[Optional(), Length(max=100)])
    account_no = StringField('Account No', validators=[Optional(), Length(max=50)])
    account_title = StringField('Account Title', validators=[Optional(), Length(max=100)])
    remarks = TextAreaField('Remarks', validators=[Optional()], render_kw={"rows": 3, "placeholder": "Previous job experience / other notes"})


class EmployeeFormStep3(FlaskForm):
    """Tab 3: Project & District Assignment only."""
    project_ids = SelectMultipleField('Assign Projects', coerce=int, validators=[Optional()], choices=[],
                                     render_kw={"class": "form-select form-select-sm", "size": "5"})
    district_ids = SelectMultipleField('Assign Districts', coerce=int, validators=[Optional()], choices=[],
                                      render_kw={"class": "form-select form-select-sm", "size": "5"})


class EmployeeAssignmentForm(FlaskForm):
    """Only Project & District assignment (for separate assignment page)."""
    project_ids = SelectMultipleField('Assign Projects', coerce=int, validators=[Optional()], choices=[], render_kw={"class": "form-select", "size": "6"})
    district_ids = SelectMultipleField('Assign Districts', coerce=int, validators=[Optional()], choices=[], render_kw={"class": "form-select", "size": "6"})
    submit = SubmitField('Save Employee & Assignment')


class EmployeeDocumentForm(FlaskForm):
    """Tab 4: Optional document upload (title + file)."""
    title = StringField('Document title (optional)', validators=[Optional(), Length(max=120)],
                        render_kw={"placeholder": "e.g. CNIC Copy, Contract"})
    document = FileField('File', validators=[Optional(),
        FileAllowed(['pdf', 'jpg', 'jpeg', 'png', 'gif', 'webp', 'doc', 'docx'], 'PDF, images, or Word only')])


class LoginForm(FlaskForm):
    username = StringField('User ID', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')


class UserForm(FlaskForm):
    """Add/Edit user. Post from Employee Posts; role is set from post's linked role."""
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=80)],
                          render_kw={"placeholder": "Login name"})
    password = PasswordField('Password', validators=[Optional(), Length(min=4)],
                             render_kw={"placeholder": "Leave blank to keep current (edit)"})
    reset_password = BooleanField('Reset password to default (123)', default=False, validators=[Optional()])
    full_name = StringField('Full Name', validators=[Optional(), Length(max=120)],
                            render_kw={"placeholder": "Display name"})
    employee_post_id = SelectField('Post', coerce=int, validators=[Optional()], choices=[])
    is_active = BooleanField('Active', default=True, validators=[Optional()])
    submit = SubmitField('Save User')


class RoleForm(FlaskForm):
    """Add/Edit role. Add: Post from Employee Posts (searchable). Edit: Role Name."""
    post_id = SelectField('Post', coerce=int, validators=[Optional()], choices=[],
                         render_kw={"placeholder": "Search post..."})
    name = StringField('Role Name', validators=[Optional(), Length(min=2, max=80)],
                      render_kw={"placeholder": "e.g. Accountant"})
    description = StringField('Description', validators=[Optional(), Length(max=255)],
                             render_kw={"placeholder": "Short description"})
    submit = SubmitField('Save Role')


class NotificationForm(FlaskForm):
    """Create a notification (broadcast to all users)."""
    title = StringField('Title', validators=[DataRequired(), Length(max=200)], render_kw={"placeholder": "e.g. Meeting tomorrow"})
    message = TextAreaField('Message', validators=[Optional()], render_kw={"rows": 3, "placeholder": "Details (optional)"})
    link = StringField('Link URL', validators=[Optional(), Length(max=500)], render_kw={"placeholder": "/reports/ (optional)"})
    link_text = StringField('Link Text', validators=[Optional(), Length(max=100)], render_kw={"placeholder": "View (optional)"})
    notification_type = SelectField('Type', choices=[('info', 'Info'), ('warning', 'Warning'), ('success', 'Success'), ('danger', 'Urgent')], validators=[DataRequired()])
    submit = SubmitField('Send to All Users')


class ReminderForm(FlaskForm):
    """Personal reminder."""
    title = StringField('Title', validators=[DataRequired(), Length(max=200)], render_kw={"placeholder": "e.g. Submit report"})
    message = TextAreaField('Note', validators=[Optional()], render_kw={"rows": 2})
    reminder_date = DateField('Date', format='%d-%m-%Y', validators=[DataRequired()],
                             render_kw={"class": "form-control datepicker"})
    reminder_time = StringField('Time (optional)', validators=[Optional(), Length(max=5)], render_kw={"placeholder": "HH:MM"})
    submit = SubmitField('Save Reminder')


class ChangePasswordForm(FlaskForm):
    """Change current user password."""
    current_password = PasswordField('Current Password', validators=[DataRequired()])
    new_password = PasswordField('New Password', validators=[DataRequired(), Length(min=4)])
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired()])
    submit = SubmitField('Change Password')

    def validate_confirm_password(self, field):
        if self.new_password.data and field.data != self.new_password.data:
            raise ValidationError('New password and confirm must match.')


class SetNewPasswordForm(FlaskForm):
    """First-time set password (after login with 123)."""
    new_password = PasswordField('New Password', validators=[DataRequired(), Length(min=4)])
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired()])
    submit = SubmitField('Save & Login')

    def validate_confirm_password(self, field):
        if self.new_password.data and field.data != self.new_password.data:
            raise ValidationError('Passwords must match.')


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


class AttendanceTimeControlForm(FlaskForm):
    morning_start = StringField('Morning shift: Start time', validators=[Optional()], render_kw={"type": "time", "class": "form-control"})
    morning_end   = StringField('Morning shift: End time',   validators=[Optional()], render_kw={"type": "time", "class": "form-control"})
    night_start   = StringField('Night shift: Start time',   validators=[Optional()], render_kw={"type": "time", "class": "form-control"})
    night_end     = StringField('Night shift: End time',     validators=[Optional()], render_kw={"type": "time", "class": "form-control"})
    submit        = SubmitField('Save')


# ════════════════════════════════════════════════════════════════════════════════
# FINANCE & ACCOUNTING FORMS
# ════════════════════════════════════════════════════════════════════════════════

class PaymentVoucherForm(FlaskForm):
    """Payment Voucher: Money going out (Accounts → DTO, DTO → Party)"""
    payment_date = DateField('Payment Date', format='%d-%m-%Y', validators=[DataRequired()], 
                             render_kw={"class": "form-control datepicker", "placeholder": "Select date"})
    from_account_id = SelectField('From Account (Source)', coerce=int, validators=[DataRequired()], choices=[])
    to_account_id = SelectField('To Account (Destination)', coerce=int, validators=[DataRequired()], choices=[])
    amount = DecimalField('Amount', validators=[DataRequired(), NumberRange(min=0.01)], 
                         render_kw={"class": "form-control", "placeholder": "0.00", "step": "0.01"})
    payment_mode = SelectField('Payment Mode', choices=[
        ('Cash', 'Cash'),
        ('Cheque', 'Cheque'),
        ('Bank Transfer', 'Bank Transfer'),
        ('Online', 'Online Payment')
    ], validators=[DataRequired()])
    cheque_number = StringField('Cheque Number', validators=[Optional(), Length(max=50)],
                               render_kw={"class": "form-control", "placeholder": "If payment mode is Cheque"})
    description = TextAreaField('Description', validators=[Optional()], 
                               render_kw={"class": "form-control", "rows": 3, "placeholder": "Payment details..."})
    district_id = SelectField('District', coerce=int, validators=[Optional()], choices=[])
    project_id = SelectField('Project', coerce=int, validators=[Optional()], choices=[])
    submit = SubmitField('Save Payment Voucher')


class ReceiptVoucherForm(FlaskForm):
    """Receipt Voucher: Money coming in (refunds, income)"""
    receipt_date = DateField('Receipt Date', format='%d-%m-%Y', validators=[DataRequired()],
                            render_kw={"class": "form-control datepicker", "placeholder": "Select date"})
    from_account_id = SelectField('From Account (Source)', coerce=int, validators=[DataRequired()], choices=[])
    to_account_id = SelectField('To Account (Our Account)', coerce=int, validators=[DataRequired()], choices=[])
    amount = DecimalField('Amount', validators=[DataRequired(), NumberRange(min=0.01)],
                         render_kw={"class": "form-control", "placeholder": "0.00", "step": "0.01"})
    receipt_mode = SelectField('Receipt Mode', choices=[
        ('Cash', 'Cash'),
        ('Cheque', 'Cheque'),
        ('Bank Transfer', 'Bank Transfer'),
        ('Online', 'Online Payment')
    ], validators=[DataRequired()])
    description = TextAreaField('Description', validators=[Optional()],
                               render_kw={"class": "form-control", "rows": 3, "placeholder": "Receipt details..."})
    submit = SubmitField('Save Receipt Voucher')


class BankEntryForm(FlaskForm):
    """Bank Entry: Transfer between bank accounts or cash"""
    entry_date = DateField('Entry Date', format='%d-%m-%Y', validators=[DataRequired()],
                          render_kw={"class": "form-control datepicker", "placeholder": "Select date"})
    from_account_id = SelectField('From Account', coerce=int, validators=[DataRequired()], choices=[])
    to_account_id = SelectField('To Account', coerce=int, validators=[DataRequired()], choices=[])
    amount = DecimalField('Amount', validators=[DataRequired(), NumberRange(min=0.01)],
                         render_kw={"class": "form-control", "placeholder": "0.00", "step": "0.01"})
    description = TextAreaField('Description', validators=[Optional()],
                               render_kw={"class": "form-control", "rows": 3, "placeholder": "Transfer details..."})
    submit = SubmitField('Save Bank Entry')


class JournalVoucherForm(FlaskForm):
    """Manual Journal Voucher: For manual accounting entries"""
    entry_date = DateField('Entry Date', format='%d-%m-%Y', validators=[DataRequired()],
                          render_kw={"class": "form-control datepicker", "placeholder": "Select date"})
    description = TextAreaField('Description', validators=[DataRequired()],
                               render_kw={"class": "form-control", "rows": 3, "placeholder": "Journal entry description..."})
    district_id = SelectField('District (Optional)', coerce=int, validators=[Optional()], choices=[])
    project_id = SelectField('Project (Optional)', coerce=int, validators=[Optional()], choices=[])
    submit = SubmitField('Save Journal Voucher')
    # Note: Journal lines will be added dynamically via JavaScript


class EmployeeExpenseForm(FlaskForm):
    """Employee Expense: Non-vehicle expenses (Travel, Office, Communication, etc.)"""
    expense_date = DateField('Expense Date', format='%d-%m-%Y', validators=[DataRequired()],
                            render_kw={"class": "form-control datepicker", "placeholder": "Select date"})
    employee_id = SelectField('Employee (Optional)', coerce=int, validators=[Optional()], choices=[])
    district_id = SelectField('District', coerce=int, validators=[Optional()], choices=[])
    project_id = SelectField('Project', coerce=int, validators=[Optional()], choices=[])
    expense_category = SelectField('Expense Category', choices=[
        ('Travel', 'Travel Expense'),
        ('Office', 'Office Expense'),
        ('Communication', 'Communication Expense'),
        ('Other', 'Other Expense')
    ], validators=[DataRequired()])
    description = TextAreaField('Description', validators=[DataRequired()],
                               render_kw={"class": "form-control", "rows": 3, "placeholder": "Expense details..."})
    amount = DecimalField('Amount', validators=[DataRequired(), NumberRange(min=0.01)],
                         render_kw={"class": "form-control", "placeholder": "0.00", "step": "0.01"})
    payment_mode = SelectField('Payment Mode', choices=[
        ('Cash', 'Cash'),
        ('Reimbursement', 'Reimbursement'),
        ('Advance', 'Advance')
    ], validators=[DataRequired()])
    receipt = FileField('Receipt/Bill (Optional)', validators=[Optional(),
        FileAllowed(['pdf', 'jpg', 'jpeg', 'png'], 'PDF or images only')])
    submit = SubmitField('Save Employee Expense')


class AccountLedgerFilterForm(FlaskForm):
    """Filter form for Account Ledger view"""
    account_id = SelectField('Select Account', coerce=int, validators=[Optional()], choices=[])
    from_date = DateField('From Date', format='%d-%m-%Y', validators=[Optional()],
                         render_kw={"class": "form-control datepicker", "placeholder": "Start date"})
    to_date = DateField('To Date', format='%d-%m-%Y', validators=[Optional()],
                       render_kw={"class": "form-control datepicker", "placeholder": "End date"})
    district_id = SelectField('District (Optional)', coerce=int, validators=[Optional()], choices=[])
    project_id = SelectField('Project (Optional)', coerce=int, validators=[Optional()], choices=[])
    submit = SubmitField('View Ledger')


class BalanceSheetFilterForm(FlaskForm):
    """Filter form for Balance Sheet report"""
    as_of_date = DateField('As of Date', format='%d-%m-%Y', validators=[Optional()],
                          render_kw={"class": "form-control datepicker", "placeholder": "Select date"})
    submit = SubmitField('Generate Balance Sheet')