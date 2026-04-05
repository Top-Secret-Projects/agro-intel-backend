from flask import Flask, request, jsonify, Response
from flask_socketio import SocketIO, join_room, leave_room, emit
from pymongo import MongoClient
from flask_cors import CORS
from datetime import datetime, timedelta
from flask_jwt_extended import JWTManager, jwt_required, create_access_token, get_jwt_identity, get_jwt
import bcrypt
from dotenv import load_dotenv
import os
import atexit
import smtplib
from email.mime.text import MIMEText
from email_validator import validate_email, EmailNotValidError
import random
import string
import logging
import re
import pytz
from io import StringIO
import csv
import base64
import jwt as pyjwt
from functools import wraps
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from bson import ObjectId

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

load_dotenv()

app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY")
app.config["JWT_TOKEN_LOCATION"] = ["headers"]
app.config["JWT_HEADER_NAME"] = "Authorization"
app.config["JWT_HEADER_TYPE"] = "Bearer"

FARMER_ID_PREFIX = os.getenv('FARMER_ID_PREFIX', 'FARM')
AGRICULTURALIST_ID_PREFIX = os.getenv('AGRICULTURALIST_ID_PREFIX', 'AGRI')
SMTP_EMAIL = os.getenv('SMTP_EMAIL')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')

jwt = JWTManager(app)


@jwt.invalid_token_loader
def invalid_token_callback(reason):
    logger.error(f"Invalid JWT: {reason}")
    return jsonify({"error": reason}), 422

@jwt.unauthorized_loader
def missing_token_callback(reason):
    logger.error(f"Missing JWT: {reason}")
    return jsonify({"error": reason}), 401

@jwt.expired_token_loader
def expired_token_callback(jwt_header, jwt_payload):
    logger.error("JWT expired")
    return jsonify({"error": "Token has expired"}), 401

# MongoDB connection
def connect_database():
    try:
        client = MongoClient(os.getenv('MONGO_URI'))
        db = client['agro_intel']
        logger.info("Connected to MongoDB database 'agro_intel'")
        return client, db
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {str(e)}")
        exit(1)

# Initialize database connection
client, db = connect_database()
farmers_collection = db['farmers']
agriculturalists_collection = db['agriculturalists']
sensor_data_collection = db['sensor_data']
availability_slots_collection = db['availability_slots']
appointments_collection = db['appointments']
counters_collection = db['counters']
otps_collection = db['otps']
pending_updates_collection = db['pending_updates']
chat_messages_collection = db['chat_messages']
unread_counts = db.unread_counts
pending_verifications_collection = db['pending_verifications']

# Create 30-day TTL index for chat messages (auto-deletes messages older than 30 days)
chat_messages_collection.create_index(
    "timestamp",
    expireAfterSeconds=30 * 24 * 60 * 60
)

# ================= HELPER FUNCTIONS =================

def generate_farmer_id():
    """Generate unique Farmer ID with prefix FARMxxxxxx"""
    max_retries = 10
    for attempt in range(max_retries):
        random_digits = ''.join(random.choices(string.digits, k=6))
        farmer_id = f"{FARMER_ID_PREFIX}{random_digits}"
        
        if not farmers_collection.find_one({"_id": farmer_id}) and \
           not pending_updates_collection.find_one({"userId": farmer_id}):
            return farmer_id
        
        logger.warning(f"Collision detected for farmer_id {farmer_id} on attempt {attempt + 1}")
    
    raise Exception("Failed to generate unique farmer_id after maximum retries")

def generate_agriculturalist_id():
    """Generate unique Agriculturalist ID with prefix AGRIxxxxxx"""
    max_retries = 10
    for attempt in range(max_retries):
        random_digits = ''.join(random.choices(string.digits, k=6))
        agriculturalist_id = f"{AGRICULTURALIST_ID_PREFIX}{random_digits}"

        if (
            not agriculturalists_collection.find_one({"_id": agriculturalist_id})
            and not pending_updates_collection.find_one({"userId": agriculturalist_id})
            and not pending_verifications_collection.find_one({"_id": agriculturalist_id})
        ):
            return agriculturalist_id

        logger.warning(f"Collision detected for agriculturalist_id {agriculturalist_id} on attempt {attempt + 1}")

    raise Exception("Failed to generate unique agriculturalist_id after maximum retries")

def validate_email_format(email):
    """Validate email format using email_validator library"""
    try:
        validate_email(email, check_deliverability=False)
        return True, None
    except EmailNotValidError as e:
        return False, f"Invalid email format: {str(e)}"

def validate_phone_number(phone):
    """Validate phone number format (10 digits)"""
    pattern = r'^(\+?1[-.]?)?\d{10}$'
    if not re.match(pattern, phone):
        return False, "Invalid mobile number format (must be 10 digits)"
    return True, None

def validate_pincode(pincode):
    """Validate Indian pincode format (6 digits)"""
    pattern = r'^\d{6}$'
    if not re.match(pattern, str(pincode)):
        return False, "Invalid pincode format (must be 6 digits)"
    return True, None

def validate_upi_id(upi_id):
    """Validate UPI ID format (basic validation)"""
    pattern = r'^[\w.-]+@[\w.-]+$'
    if not re.match(pattern, upi_id):
        return False, "Invalid UPI ID format"
    return True, None

def validate_password(password):
    """Validate password strength (minimum 6 characters)"""
    if not isinstance(password, str) or len(password) < 6:
        return False, "Password must be at least 6 characters long"
    return True, None

def validate_farmer_registration_data(data):
    """Validate farmer registration data"""
    mandatory_fields = ['name', 'email', 'mobileNumber', 'password', 'cityVillage', 'district', 'state', 'deviceId', 'upiId']
    
    if not all(field in data for field in mandatory_fields):
        missing = [field for field in mandatory_fields if field not in data]
        return False, f"Missing mandatory fields: {', '.join(missing)}"
    
    is_valid, error_msg = validate_email_format(data['email'])
    if not is_valid:
        return False, error_msg
    
    is_valid, error_msg = validate_phone_number(data['mobileNumber'])
    if not is_valid:
        return False, error_msg
    
    is_valid, error_msg = validate_password(data['password'])
    if not is_valid:
        return False, error_msg
    
    is_valid, error_msg = validate_upi_id(data['upiId'])
    if not is_valid:
        return False, error_msg
    
    string_fields = ['name', 'cityVillage', 'district', 'state', 'deviceId', 'upiId']
    for field in string_fields:
        if not isinstance(data[field], str) or len(data[field].strip()) == 0:
            return False, f"{field} must be a non-empty string"
    
    return True, None

def validate_agriculturalist_registration_data(data):
    """Validate agriculturalist registration data"""
    mandatory_fields = [
        'name', 'email', 'mobileNumber', 'password',
        'address', 'cityVillage', 'district', 'state',
        'pincode', 'upiId', 'professionalRole',
        'licenseNumber', 'documentImage'
    ]

    if not all(field in data and data[field] for field in mandatory_fields):
        missing = [field for field in mandatory_fields if field not in data or not data[field]]
        return False, f"Missing mandatory fields: {', '.join(missing)}"

    is_valid, error_msg = validate_email_format(data['email'])
    if not is_valid:
        return False, error_msg

    is_valid, error_msg = validate_phone_number(data['mobileNumber'])
    if not is_valid:
        return False, error_msg

    is_valid, error_msg = validate_password(data['password'])
    if not is_valid:
        return False, error_msg

    is_valid, error_msg = validate_pincode(data['pincode'])
    if not is_valid:
        return False, error_msg

    is_valid, error_msg = validate_upi_id(data['upiId'])
    if not is_valid:
        return False, error_msg

    valid_roles = [
        "Agronomist",
        "Soil Scientist",
        "Horticulturist",
        "Crop Protection Specialist",
        "Agricultural Engineer",
        "Plant Pathologist",
        "Farm Management Consultant"
    ]
    if data["professionalRole"] not in valid_roles:
        return False, "Invalid professional role selected"

    string_fields = [
        'name', 'address', 'cityVillage', 'district', 'state',
        'upiId', 'professionalRole', 'licenseNumber'
    ]
    for field in string_fields:
        if not isinstance(data[field], str) or len(data[field].strip()) == 0:
            return False, f"{field} must be a non-empty string"

    return True, None

def generate_otp():
    """Generate 6-digit OTP"""
    return ''.join(random.choices(string.digits, k=6))

def send_otp_email(email, otp, max_retries=3, retry_delay=5):
    """Send OTP email with retry logic"""
    import time
    
    for attempt in range(max_retries):
        try:
            msg = MIMEText(f"Your OTP for email verification is {otp}. OTP is valid for 10 minutes.")
            msg['Subject'] = 'Agro-Intel Email Verification OTP'
            msg['From'] = SMTP_EMAIL
            msg['To'] = email
            
            with smtplib.SMTP('smtp.gmail.com', 587, timeout=30) as server:
                server.starttls()
                server.login(SMTP_EMAIL, SMTP_PASSWORD)
                server.send_message(msg)
            
            logger.info(f"Sent OTP to {email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send OTP to {email} on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
    
    return False

def send_welcome_email_farmer(email, farmer_name, farmer_id):
    """Send welcome email after successful farmer registration"""
    try:
        msg = MIMEText(f"Welcome to Agro-Intel, {farmer_name}! Your Farmer ID is {farmer_id}.")
        msg['Subject'] = 'Welcome to Agro-Intel'
        msg['From'] = SMTP_EMAIL
        msg['To'] = email
        
        with smtplib.SMTP('smtp.gmail.com', 587, timeout=30) as server:
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.send_message(msg)
        
        logger.info(f"Sent welcome email to {email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send welcome email to {email}: {str(e)}")
        return False

def send_welcome_email_agriculturalist(email, agriculturalist_name, agriculturalist_id):
    """Send welcome email after successful agriculturalist registration"""
    try:
        msg = MIMEText(f"Welcome to Agro-Intel, {agriculturalist_name}! Your Agriculturalist ID is {agriculturalist_id}.")
        msg['Subject'] = 'Welcome to Agro-Intel'
        msg['From'] = SMTP_EMAIL
        msg['To'] = email
        
        with smtplib.SMTP('smtp.gmail.com', 587, timeout=30) as server:
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.send_message(msg)
        
        logger.info(f"Sent welcome email to {email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send welcome email to {email}: {str(e)}")
        return False
    
def admin_jwt_required():
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return jsonify({"error": "Admin token missing"}), 401

            token = auth_header.split(" ")[1]

            try:
                decoded = pyjwt.decode(
                    token,
                    os.getenv("ADMIN_SECRET_KEY"),
                    algorithms=["HS256"]
                )
                if decoded.get("role") != "admin":
                    return jsonify({"error": "Forbidden"}), 403
            except pyjwt.ExpiredSignatureError:
                return jsonify({"error": "Admin token expired"}), 401
            except pyjwt.InvalidTokenError:
                return jsonify({"error": "Invalid admin token"}), 401

            return fn(*args, **kwargs)
        return wrapper
    return decorator   

def send_verification_request_to_admin(application_id, data, document_base64):
    try:
        support_email = os.getenv("SUPPORT_EMAIL")
        smtp_email = os.getenv("SMTP_EMAIL")
        smtp_password = os.getenv("SMTP_PASSWORD")

        msg = MIMEMultipart()
        msg["Subject"] = f"New Agriculturalist Registration Request — {application_id}"
        msg["From"] = smtp_email
        msg["To"] = support_email

        body = f"""
New Agriculturalist Registration Request

Application ID   : {application_id}
Name             : {data.get('name')}
Email            : {data.get('email')}
Mobile Number    : {data.get('mobileNumber')}
Professional Role: {data.get('professionalRole')}
License Number   : {data.get('licenseNumber')}
Address          : {data.get('address')}
City/Village     : {data.get('cityVillage')}
District         : {data.get('district')}
State            : {data.get('state')}
Pincode          : {data.get('pincode')}
Submitted At     : {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC

Please review this application in the Agro-Intel admin panel.
"""
        msg.attach(MIMEText(body, "plain"))

        if document_base64:
            try:
                raw = document_base64.split(",")[1] if "," in document_base64 else document_base64
                attachment_bytes = base64.b64decode(raw)
                attachment = MIMEApplication(attachment_bytes, Name="verification_document")
                attachment["Content-Disposition"] = 'attachment; filename="verification_document"'
                msg.attach(attachment)
            except Exception as e:
                logger.error(f"Failed to attach verification document: {str(e)}")

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(smtp_email, smtp_password)
            server.send_message(msg)

        logger.info(f"Support email sent for agriculturalist application {application_id}")

    except Exception as e:
        logger.error(f"Failed to send support email: {str(e)}")
    
def send_reschedule_email_to_farmer(
    farmer_email,
    farmer_name,
    agriculturalist_name,
    old_date,
    old_slot_time,
    new_date,
    new_slot_time
):
    try:
        body = f"""
Hello {farmer_name},

Your appointment with agriculturalist {agriculturalist_name} has been rescheduled.

Previous schedule:
Date: {old_date}
Time: {old_slot_time}

New schedule:
Date: {new_date}
Time: {new_slot_time}

Please log in to Agro-Intel for more details.

Regards,
Agro-Intel
"""
        msg = MIMEText(body)
        msg["Subject"] = "Agro-Intel Appointment Rescheduled"
        msg["From"] = SMTP_EMAIL
        msg["To"] = farmer_email

        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.send_message(msg)

        logger.info(f"Reschedule email sent to farmer {farmer_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send reschedule email to {farmer_email}: {str(e)}")
        return False
    
def auto_complete_past_appointments():
    """Automatically mark past booked appointments as completed"""
    try:
        ist_timezone = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(ist_timezone)

        booked_appointments = appointments_collection.find({"status": "booked"})

        for appointment in booked_appointments:
            appointment_date = appointment.get("date")
            slot_end_time = appointment.get("slotEndTime")

            if not appointment_date or not slot_end_time:
                continue

            try:
                appointment_end_datetime = datetime.strptime(
                    f"{appointment_date} {slot_end_time}",
                    "%Y-%m-%d %H:%M"
                )
                appointment_end_datetime = ist_timezone.localize(appointment_end_datetime)

                if now_ist > appointment_end_datetime:
                    appointments_collection.update_one(
                        {
                            "_id": appointment["_id"],
                            "status": "booked"
                        },
                        {
                            "$set": {
                                "status": "completed",
                                "completedAt": datetime.now(pytz.UTC)
                            }
                        }
                    )
                    logger.info(f"Appointment {appointment['_id']} marked as completed")

            except Exception as inner_error:
                logger.error(
                    f"Failed to process appointment {appointment.get('_id')}: {str(inner_error)}"
                )

    except Exception as e:
        logger.error(f"Error in auto_complete_past_appointments: {str(e)}")

def generate_time_slots():
    """Generate all 48 time slots for a day (00:00 to 23:30)"""
    slots = []
    for hour in range(24):
        for minute in [0, 30]:
            start_time = f"{hour:02d}:{minute:02d}"
            end_hour = hour if minute == 0 else hour + 1
            end_minute = 30 if minute == 0 else 0
            if end_hour == 24:
                end_hour = 0
            end_time = f"{end_hour:02d}:{end_minute:02d}"
            slots.append({"start": start_time, "end": end_time})
    return slots

# ================= API ENDPOINTS =================

@app.route('/', methods=['GET'])
def home():
    return "Agro-Intel Server is up and Running"

# ================= FARMER ENDPOINTS =================

@app.route('/api/register-farmer', methods=['POST'])
def register_farmer():
    """Endpoint: Initiate farmer registration"""
    data = request.get_json()
    
    is_valid, error_message = validate_farmer_registration_data(data)
    if not is_valid:
        return jsonify({"error": error_message}), 400
    
    if farmers_collection.find_one({"email": data['email']}) or \
       agriculturalists_collection.find_one({"email": data['email']}):
        return jsonify({"error": "Email already exists"}), 409
    
    if farmers_collection.find_one({"mobileNumber": data['mobileNumber']}):
        return jsonify({"error": "Mobile number already exists"}), 409
    
    try:
        farmer_id = generate_farmer_id()
    except Exception as e:
        logger.error(f"Error generating farmer_id: {str(e)}")
        return jsonify({"error": str(e)}), 500
    
    hashed_password = bcrypt.hashpw(data['password'].encode('utf-8'), bcrypt.gensalt())
    otp = generate_otp()
    hashed_otp = bcrypt.hashpw(otp.encode('utf-8'), bcrypt.gensalt())
    
    pending_registration = {
        "userId": farmer_id,
        "type": "register_farmer",
        "farmerData": {
            "name": data['name'],
            "email": data['email'],
            "mobileNumber": data['mobileNumber'],
            "password": hashed_password,
            "cityVillage": data['cityVillage'],
            "district": data['district'],
            "state": data['state'],
            "deviceId": data['deviceId'],
            "upiId": data['upiId']
        },
        "email": data['email'],
        "otp": hashed_otp,
        "createdAt": datetime.now(pytz.UTC)
    }
    
    try:
        pending_updates_collection.replace_one(
            {"userId": farmer_id, "type": "register_farmer"},
            pending_registration,
            upsert=True
        )
        
        if send_otp_email(data['email'], otp):
            return jsonify({
                "message": "OTP sent to email for registration verification",
                "farmerId": farmer_id
            }), 200
        else:
            pending_updates_collection.delete_one({"userId": farmer_id, "type": "register_farmer"})
            logger.error(f"Failed to send OTP email for farmer {farmer_id}")
            return jsonify({"error": "Failed to send OTP email"}), 500
    
    except Exception as e:
        logger.error(f"Error initiating farmer registration for farmer {farmer_id}: {str(e)}")
        return jsonify({"error": str(e)}), 400

@app.route('/api/confirm-register-farmer', methods=['POST'])
def confirm_register_farmer():
    """Endpoint: Confirm farmer registration with OTP"""
    data = request.get_json()
    
    required_fields = ['farmerId', 'otp']
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing farmerId or otp"}), 400
    
    pending_registration = pending_updates_collection.find_one({
        "userId": data['farmerId'],
        "type": "register_farmer"
    })
    
    if not pending_registration:
        return jsonify({"error": "Pending registration not found or expired"}), 404
    
    if not bcrypt.checkpw(data['otp'].encode('utf-8'), pending_registration['otp']):
        logger.warning(f"Invalid OTP for farmer {data['farmerId']}")
        return jsonify({"error": "Invalid OTP"}), 401
    
    farmer_data = pending_registration['farmerData']
    
    farmer = {
        "_id": data['farmerId'],
        "name": farmer_data['name'],
        "email": farmer_data['email'],
        "mobileNumber": farmer_data['mobileNumber'],
        "password": farmer_data['password'],
        "cityVillage": farmer_data['cityVillage'],
        "district": farmer_data['district'],
        "state": farmer_data['state'],
        "deviceId": farmer_data['deviceId'],
        "upiId": farmer_data['upiId'],
        "isEmailVerified": True,
        "createdAt": datetime.now(pytz.UTC),
        "updatedAt": datetime.now(pytz.UTC)
    }
    
    try:
        farmers_collection.insert_one(farmer)
        pending_updates_collection.delete_one({
            "userId": data['farmerId'],
            "type": "register_farmer"
        })
        
        send_welcome_email_farmer(farmer_data['email'], farmer_data['name'], data['farmerId'])
        logger.info(f"Farmer {data['farmerId']} registered successfully")
        return jsonify({
            "message": "Farmer Registration Successful",
            "farmerId": data['farmerId']
        }), 201
    
    except Exception as e:
        logger.error(f"Error registering farmer {data['farmerId']}: {str(e)}")
        return jsonify({"error": str(e)}), 400

@app.route('/api/login-farmer', methods=['POST'])
def login_farmer():
    """Endpoint: Farmer login with email and password"""
    data = request.get_json()
    
    required_fields = ['email', 'password']
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing email or password"}), 400
    
    is_valid, error_msg = validate_email_format(data['email'])
    if not is_valid:
        return jsonify({"error": error_msg}), 400
    
    try:
        farmer = farmers_collection.find_one({"email": data['email']})
        
        if not farmer:
            logger.warning(f"Login attempt with non-existent email: {data['email']}")
            return jsonify({"error": "Invalid email or password"}), 401
        
        if not bcrypt.checkpw(data['password'].encode('utf-8'), farmer['password']):
            logger.warning(f"Invalid password attempt for farmer: {farmer['_id']}")
            return jsonify({"error": "Invalid email or password"}), 401
        
        if not farmer.get('isEmailVerified', False):
            return jsonify({"error": "Email not verified. Please complete registration."}), 403
        
        access_token = create_access_token(
            identity=farmer['_id'],
            additional_claims={
                "email": farmer['email'],
                "name": farmer['name'],
                "userType": "farmer"
            }
        )
        
        logger.info(f"Farmer {farmer['_id']} logged in successfully")
        
        return jsonify({
            "message": "Farmer login successful",
            "farmerId": farmer['_id'],
            "name": farmer['name'],
            "email": farmer['email'],
            "token": access_token
        }), 200
    
    except Exception as e:
        logger.error(f"Error during farmer login: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/profile-farmer/<farmer_id>', methods=['GET'])
@jwt_required()
def get_farmer_profile(farmer_id):
    """Endpoint: Get farmer profile information - RESTRICTED to own profile"""
    try:
        current_user_id = get_jwt_identity()
        
        if current_user_id != farmer_id:
            logger.warning(f"Unauthorized profile access attempt by {current_user_id} for farmer {farmer_id}")
            return jsonify({"error": "Unauthorized access"}), 403
        
        farmer = farmers_collection.find_one({"_id": farmer_id})
        
        if not farmer:
            logger.warning(f"Profile request for non-existent farmer: {farmer_id}")
            return jsonify({"error": "User not found"}), 404
        
        farmer_profile = {
            "farmerId": farmer['_id'],
            "name": farmer['name'],
            "email": farmer['email'],
            "mobileNumber": farmer['mobileNumber'],
            "cityVillage": farmer['cityVillage'],
            "district": farmer['district'],
            "state": farmer['state'],
            "deviceId": farmer['deviceId'],
            "upiId": farmer['upiId'],
            "isEmailVerified": farmer.get('isEmailVerified', False),
            "createdAt": farmer['createdAt'].isoformat() if 'createdAt' in farmer else None,
            "updatedAt": farmer['updatedAt'].isoformat() if 'updatedAt' in farmer else None
        }
        
        logger.info(f"Profile retrieved for farmer {farmer_id}")
        return jsonify({
            "message": "Farmer profile retrieved successfully",
            "profile": farmer_profile
        }), 200
    
    except Exception as e:
        logger.error(f"Error retrieving farmer profile {farmer_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/update-profile-farmer', methods=['PUT'])
@jwt_required()
def update_profile_farmer():
    """Endpoint: Update farmer profile (except password)"""
    data = request.get_json()
    current_user_id = get_jwt_identity()
    
    try:
        # Fields that can be updated (excluding password)
        updateable_fields = ['name', 'mobileNumber', 'cityVillage', 'district', 'state', 'upiId']
        
        # Build update document
        update_doc = {}
        
        for field in updateable_fields:
            if field in data:
                if field == 'mobileNumber':
                    # Validate phone number
                    is_valid, error_msg = validate_phone_number(data[field])
                    if not is_valid:
                        return jsonify({"error": error_msg}), 400
                    
                    # Check if mobile number is already used by another user
                    existing = farmers_collection.find_one({
                        "mobileNumber": data[field],
                        "_id": {"$ne": current_user_id}
                    })
                    if existing:
                        return jsonify({"error": "Mobile number already in use"}), 409
                
                elif field == 'upiId':
                    # Validate UPI ID
                    is_valid, error_msg = validate_upi_id(data[field])
                    if not is_valid:
                        return jsonify({"error": error_msg}), 400
                
                elif field in ['name', 'cityVillage', 'district', 'state']:
                    # Validate non-empty string
                    if not isinstance(data[field], str) or len(data[field].strip()) == 0:
                        return jsonify({"error": f"{field} must be a non-empty string"}), 400
                
                update_doc[field] = data[field]
        
        if not update_doc:
            return jsonify({"error": "No valid fields provided for update"}), 400
        
        # Add updatedAt timestamp
        update_doc['updatedAt'] = datetime.now(pytz.UTC)
        
        # Update farmer
        result = farmers_collection.update_one(
            {"_id": current_user_id},
            {"$set": update_doc}
        )
        
        if result.matched_count == 0:
            return jsonify({"error": "Farmer not found"}), 404
        
        logger.info(f"Farmer {current_user_id} profile updated successfully")
        
        return jsonify({
            "message": "Farmer profile updated successfully",
            "farmerId": current_user_id,
            "updatedFields": list(update_doc.keys())
        }), 200
    
    except Exception as e:
        logger.error(f"Error updating farmer profile: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ================= AGRICULTURALIST ENDPOINTS =================

@app.route('/api/register-agriculturalist', methods=['POST'])
def register_agriculturalist():
    """Endpoint: Submit agriculturalist registration for admin review"""
    data = request.get_json()

    is_valid, error_message = validate_agriculturalist_registration_data(data)
    if not is_valid:
        return jsonify({"error": error_message}), 400

    if farmers_collection.find_one({"email": data["email"]}) or agriculturalists_collection.find_one({"email": data["email"]}):
        return jsonify({"error": "Email already registered"}), 409

    if farmers_collection.find_one({"mobileNumber": data["mobileNumber"]}) or agriculturalists_collection.find_one({"mobileNumber": data["mobileNumber"]}):
        return jsonify({"error": "Mobile number already registered"}), 409

    existing_pending = pending_verifications_collection.find_one({
        "email": data["email"],
        "status": "pending_verification"
    })
    if existing_pending:
        return jsonify({"error": "Your application is already under review"}), 409

    try:
        application_id = generate_agriculturalist_id()
        hashed_password = bcrypt.hashpw(data["password"].encode("utf-8"), bcrypt.gensalt())

        pending_verifications_collection.insert_one({
            "_id": application_id,
            "name": data["name"],
            "email": data["email"],
            "mobileNumber": data["mobileNumber"],
            "password": hashed_password,
            "address": data["address"],
            "cityVillage": data["cityVillage"],
            "district": data["district"],
            "state": data["state"],
            "pincode": data["pincode"],
            "upiId": data["upiId"],
            "professionalRole": data["professionalRole"],
            "licenseNumber": data["licenseNumber"],
            "documentImage": data["documentImage"],
            "status": "pending_verification",
            "submittedAt": datetime.now(pytz.UTC)
        })

        send_verification_request_to_admin(application_id, data, data["documentImage"])

        logger.info(f"Agriculturalist application submitted: {application_id}")
        return jsonify({
            "message": "Registration submitted. Please check your email within 24–48 hours.",
            "applicationId": application_id
        }), 200

    except Exception as e:
        logger.error(f"Error registering agriculturalist application: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/confirm-register-agriculturalist', methods=['POST'])
def confirm_register_agriculturalist():
    """Endpoint: Confirm approved agriculturalist email with OTP"""
    data = request.get_json()

    required_fields = ['agriculturalistId', 'otp']
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing agriculturalistId or otp"}), 400

    try:
        otp_record = otps_collection.find_one({"userId": data["agriculturalistId"]})

        if not otp_record:
            return jsonify({"error": "OTP not found or expired"}), 404

        created_at = otp_record.get("createdAt")
        if created_at:
          if created_at.tzinfo is None:
            created_at = pytz.UTC.localize(created_at)

          if (datetime.now(pytz.UTC) - created_at).total_seconds() > 600:
              otps_collection.delete_one({"_id": otp_record["_id"]})
              return jsonify({"error": "OTP expired"}), 401

        if otp_record["otp"] != data["otp"]:
            logger.warning(f"Invalid OTP for agriculturalist {data['agriculturalistId']}")
            return jsonify({"error": "Invalid OTP"}), 401

        agriculturalist = agriculturalists_collection.find_one({"_id": data["agriculturalistId"]})
        if not agriculturalist:
            return jsonify({"error": "Agriculturalist account not found"}), 404

        agriculturalists_collection.update_one(
            {"_id": data["agriculturalistId"]},
            {
                "$set": {
                    "isEmailVerified": True,
                    "updatedAt": datetime.now(pytz.UTC)
                }
            }
        )

        otps_collection.delete_one({"_id": otp_record["_id"]})

        send_welcome_email_agriculturalist(
            agriculturalist["email"],
            agriculturalist["name"],
            agriculturalist["_id"]
        )

        logger.info(f"Agriculturalist {data['agriculturalistId']} email verified successfully")
        return jsonify({
            "message": "Agriculturalist Registration Successful",
            "agriculturalistId": data["agriculturalistId"]
        }), 200

    except Exception as e:
        logger.error(f"Error confirming agriculturalist OTP verification {data.get('agriculturalistId')}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/login-agriculturalist', methods=['POST'])
def login_agriculturalist():
    """Endpoint: Agriculturalist login with admin-approval-aware flow"""
    data = request.get_json()

    required_fields = ['email', 'password']
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing email or password"}), 400

    is_valid, error_msg = validate_email_format(data['email'])
    if not is_valid:
        return jsonify({"error": error_msg}), 400

    try:
        agriculturalist = agriculturalists_collection.find_one({"email": data["email"]})

        if not agriculturalist:
            pending = pending_verifications_collection.find_one({"email": data["email"]})
            if pending and pending.get("status") == "pending_verification":
                return jsonify({
                    "error": "Your registration is under review. Please check your email within 24–48 hours."
                }), 403
            if pending and pending.get("status") == "rejected":
                return jsonify({
                    "error": "Your registration was not approved. Please contact support@agro-intel.com."
                }), 403
            return jsonify({"error": "Invalid email or password"}), 401

        if not agriculturalist.get("isEmailVerified", False):
            return jsonify({
                "error": "Please verify your email first. Check your inbox for the OTP sent after approval."
            }), 403

        if not bcrypt.checkpw(data["password"].encode("utf-8"), agriculturalist["password"]):
            logger.warning(f"Invalid password attempt for agriculturalist: {agriculturalist['_id']}")
            return jsonify({"error": "Invalid email or password"}), 401

        access_token = create_access_token(
            identity=agriculturalist['_id'],
            additional_claims={
                "email": agriculturalist['email'],
                "name": agriculturalist['name'],
                "userType": "agriculturalist"
            }
        )

        logger.info(f"Agriculturalist {agriculturalist['_id']} logged in successfully")

        return jsonify({
            "message": "Agriculturalist login successful",
            "agriculturalistId": agriculturalist["_id"],
            "name": agriculturalist["name"],
            "email": agriculturalist["email"],
            "token": access_token
        }), 200

    except Exception as e:
        logger.error(f"Error during agriculturalist login: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/profile-agriculturalist/<agriculturalist_id>', methods=['GET'])
@jwt_required()
def get_agriculturalist_profile(agriculturalist_id):
    """Endpoint: Get agriculturalist profile - RESTRICTED to own profile"""
    try:
        current_user_id = get_jwt_identity()
        
        if current_user_id != agriculturalist_id:
            logger.warning(f"Unauthorized profile access attempt by {current_user_id} for agriculturalist {agriculturalist_id}")
            return jsonify({"error": "Unauthorized access"}), 403
        
        agriculturalist = agriculturalists_collection.find_one({"_id": agriculturalist_id})
        
        if not agriculturalist:
            logger.warning(f"Profile request for non-existent agriculturalist: {agriculturalist_id}")
            return jsonify({"error": "User not found"}), 404
        
        agriculturalist_profile = {
            "agriculturalistId": agriculturalist['_id'],
            "name": agriculturalist['name'],
            "email": agriculturalist['email'],
            "mobileNumber": agriculturalist['mobileNumber'],
            "address": agriculturalist['address'],
            "cityVillage": agriculturalist['cityVillage'],
            "district": agriculturalist['district'],
            "state": agriculturalist['state'],
            "pincode": agriculturalist['pincode'],
            "upiId": agriculturalist['upiId'],
            "isAvailable": agriculturalist.get('isAvailable', True),
            "isEmailVerified": agriculturalist.get('isEmailVerified', False),
            "createdAt": agriculturalist['createdAt'].isoformat() if 'createdAt' in agriculturalist else None,
            "updatedAt": agriculturalist['updatedAt'].isoformat() if 'updatedAt' in agriculturalist else None
        }
        
        logger.info(f"Profile retrieved for agriculturalist {agriculturalist_id}")
        return jsonify({
            "message": "Agriculturalist profile retrieved successfully",
            "profile": agriculturalist_profile
        }), 200
    
    except Exception as e:
        logger.error(f"Error retrieving agriculturalist profile {agriculturalist_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/update-profile-agriculturalist', methods=['PUT'])
@jwt_required()
def update_profile_agriculturalist():
    """Endpoint: Update agriculturalist profile (except password)"""
    data = request.get_json()
    current_user_id = get_jwt_identity()
    
    try:
        # Fields that can be updated (excluding password)
        updateable_fields = ['name', 'mobileNumber', 'address', 'cityVillage', 'district', 'state', 'pincode', 'upiId']
        
        # Build update document
        update_doc = {}
        
        for field in updateable_fields:
            if field in data:
                if field == 'mobileNumber':
                    # Validate phone number
                    is_valid, error_msg = validate_phone_number(data[field])
                    if not is_valid:
                        return jsonify({"error": error_msg}), 400
                    
                    # Check if mobile number is already used by another user
                    existing = agriculturalists_collection.find_one({
                        "mobileNumber": data[field],
                        "_id": {"$ne": current_user_id}
                    })
                    if existing:
                        return jsonify({"error": "Mobile number already in use"}), 409
                
                elif field == 'pincode':
                    # Validate pincode
                    is_valid, error_msg = validate_pincode(data[field])
                    if not is_valid:
                        return jsonify({"error": error_msg}), 400
                
                elif field == 'upiId':
                    # Validate UPI ID
                    is_valid, error_msg = validate_upi_id(data[field])
                    if not is_valid:
                        return jsonify({"error": error_msg}), 400
                
                elif field in ['name', 'address', 'cityVillage', 'district', 'state']:
                    # Validate non-empty string
                    if not isinstance(data[field], str) or len(data[field].strip()) == 0:
                        return jsonify({"error": f"{field} must be a non-empty string"}), 400
                
                update_doc[field] = data[field]
        
        if not update_doc:
            return jsonify({"error": "No valid fields provided for update"}), 400
        
        # Add updatedAt timestamp
        update_doc['updatedAt'] = datetime.now(pytz.UTC)
        
        # Update agriculturalist
        result = agriculturalists_collection.update_one(
            {"_id": current_user_id},
            {"$set": update_doc}
        )
        
        if result.matched_count == 0:
            return jsonify({"error": "Agriculturalist not found"}), 404
        
        logger.info(f"Agriculturalist {current_user_id} profile updated successfully")
        
        return jsonify({
            "message": "Agriculturalist profile updated successfully",
            "agriculturalistId": current_user_id,
            "updatedFields": list(update_doc.keys())
        }), 200
    
    except Exception as e:
        logger.error(f"Error updating agriculturalist profile: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/find-agriculturalist', methods=['GET'])
@jwt_required()
def find_agriculturalist():
    """Endpoint: Find agriculturalists with filtering and pagination"""
    try:
        current_user_id = get_jwt_identity()
        
        state = request.args.get('state', None)
        district = request.args.get('district', None)
        is_available = request.args.get('isAvailable', None)
        search = request.args.get('search', None)
        
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 50))
        skip = (page - 1) * limit
        
        query_filter = {"isEmailVerified": True}
        
        if state:
            query_filter["state"] = {"$regex": state, "$options": "i"}
        
        if district:
            query_filter["district"] = {"$regex": district, "$options": "i"}
        
        if is_available is not None:
            query_filter["isAvailable"] = is_available.lower() == 'true'
        
        if search:
            query_filter["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"email": {"$regex": search, "$options": "i"}}
            ]
        
        total_count = agriculturalists_collection.count_documents(query_filter)
        agriculturalists = agriculturalists_collection.find(query_filter).skip(skip).limit(limit)
        
        agriculturalist_list = []
        for agri in agriculturalists:
            agriculturalist_info = {
                "agriculturalistId": agri['_id'],
                "name": agri['name'],
                "email": agri['email'],
                "mobileNumber": agri['mobileNumber'],
                "address": agri['address'],
                "cityVillage": agri['cityVillage'],
                "district": agri['district'],
                "state": agri['state'],
                "pincode": agri['pincode'],
                "upiId": agri['upiId'],
                "isAvailable": agri.get('isAvailable', True),
                "createdAt": agri['createdAt'].isoformat() if 'createdAt' in agri else None
            }
            agriculturalist_list.append(agriculturalist_info)
        
        logger.info(f"Agriculturalist profiles retrieved by user {current_user_id}")
        
        return jsonify({
            "message": "Agriculturalist profiles retrieved successfully",
            "totalCount": total_count,
            "page": page,
            "limit": limit,
            "count": len(agriculturalist_list),
            "filters": {
                "state": state,
                "district": district,
                "isAvailable": is_available,
                "search": search
            },
            "agriculturalists": agriculturalist_list
        }), 200
    
    except Exception as e:
        logger.error(f"Error retrieving agriculturalist profiles: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ================= SENSOR DATA ENDPOINTS =================

@app.route('/api/send-sensor-data', methods=['POST'])
def send_sensor_data():
    """Endpoint: Receive sensor data from IoT device and store in database"""
    data = request.get_json()
    
    required_fields = ['device_id', 'nitrogen', 'phosphorous', 'potassium', 'soil_moisture', 'soil_ph', 'soil_temp']
    if not all(field in data for field in required_fields):
        missing = [field for field in required_fields if field not in data]
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400
    
    try:
        farmer = farmers_collection.find_one({"deviceId": data['device_id']})
        
        if not farmer:
            logger.warning(f"Sensor data received from unknown device: {data['device_id']}")
            return jsonify({"error": "Device ID not found or not registered"}), 404
        
        try:
            nitrogen = float(data['nitrogen'])
            phosphorous = float(data['phosphorous'])
            potassium = float(data['potassium'])
            soil_moisture = float(data['soil_moisture'])
            soil_ph = float(data['soil_ph'])
            soil_temp = float(data['soil_temp'])
        except (ValueError, TypeError):
            return jsonify({"error": "Sensor values must be numeric"}), 400
        
        if not (0 <= nitrogen <= 300):
            return jsonify({"error": "Nitrogen value out of range (0-300)"}), 400
        if not (0 <= phosphorous <= 300):
            return jsonify({"error": "Phosphorous value out of range (0-300)"}), 400
        if not (0 <= potassium <= 300):
            return jsonify({"error": "Potassium value out of range (0-300)"}), 400
        if not (0 <= soil_moisture <= 100):
            return jsonify({"error": "Soil moisture value out of range (0-100)"}), 400
        if not (0 <= soil_ph <= 14):
            return jsonify({"error": "Soil pH value out of range (0-14)"}), 400
        if not (-50 <= soil_temp <= 80):
            return jsonify({"error": "Soil temperature value out of range (-50 to 80)"}), 400
        
        sensor_data = {
            "farmerId": farmer['_id'],
            "deviceId": data['device_id'],
            "nitrogen": nitrogen,
            "phosphorous": phosphorous,
            "potassium": potassium,
            "soil_moisture": soil_moisture,
            "soil_ph": soil_ph,
            "soil_temp": soil_temp,
            "timestamp": datetime.now(pytz.UTC),
            "createdAt": datetime.now(pytz.UTC)
        }
        
        result = sensor_data_collection.insert_one(sensor_data)
        
        logger.info(f"Sensor data received from device {data['device_id']} for farmer {farmer['_id']}")
        
        return jsonify({
            "message": "Sensor data received and stored successfully",
            "sensorDataId": str(result.inserted_id),
            "farmerId": farmer['_id'],
            "deviceId": data['device_id'],
            "timestamp": sensor_data['timestamp'].isoformat()
        }), 201
    
    except Exception as e:
        logger.error(f"Error storing sensor data: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/get-sensor-data/<farmer_id>', methods=['GET'])
@jwt_required()
def get_sensor_data(farmer_id):
    """Endpoint: Get sensor data for a specific farmer"""
    try:
        current_user_id = get_jwt_identity()
        
        if current_user_id != farmer_id:
            logger.warning(f"Unauthorized sensor data access attempt by {current_user_id} for farmer {farmer_id}")
            return jsonify({"error": "Unauthorized access"}), 403
        
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 50))
        skip = (page - 1) * limit
        
        sensor_data = sensor_data_collection.find({"farmerId": farmer_id}).sort("timestamp", -1).skip(skip).limit(limit)
        
        total_count = sensor_data_collection.count_documents({"farmerId": farmer_id})
        
        sensor_list = []
        for data in sensor_data:
            sensor_info = {
                "sensorDataId": str(data['_id']),
                "deviceId": data['deviceId'],
                "nitrogen": data['nitrogen'],
                "phosphorous": data['phosphorous'],
                "potassium": data['potassium'],
                "soil_moisture": data['soil_moisture'],
                "soil_ph": data['soil_ph'],
                "soil_temp": data['soil_temp'],
                "timestamp": data['timestamp'].isoformat()
            }
            sensor_list.append(sensor_info)
        
        logger.info(f"Sensor data retrieved for farmer {farmer_id}")
        
        return jsonify({
            "message": "Sensor data retrieved successfully",
            "totalCount": total_count,
            "page": page,
            "limit": limit,
            "count": len(sensor_list),
            "sensorData": sensor_list
        }), 200
    
    except Exception as e:
        logger.error(f"Error retrieving sensor data for farmer {farmer_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/get-latest-sensor-data/<farmer_id>', methods=['GET'])
@jwt_required()
def get_latest_sensor_data(farmer_id):
    """Endpoint: Get latest sensor data for a specific farmer"""
    try:
        current_user_id = get_jwt_identity()
        
        if current_user_id != farmer_id:
            logger.warning(f"Unauthorized sensor data access attempt by {current_user_id} for farmer {farmer_id}")
            return jsonify({"error": "Unauthorized access"}), 403
        
        latest_data = sensor_data_collection.find_one(
            {"farmerId": farmer_id},
            sort=[("timestamp", -1)]
        )
        
        if not latest_data:
            return jsonify({"error": "No sensor data found"}), 404
        
        sensor_info = {
            "sensorDataId": str(latest_data['_id']),
            "deviceId": latest_data['deviceId'],
            "nitrogen": latest_data['nitrogen'],
            "phosphorous": latest_data['phosphorous'],
            "potassium": latest_data['potassium'],
            "soil_moisture": latest_data['soil_moisture'],
            "soil_ph": latest_data['soil_ph'],
            "soil_temp": latest_data['soil_temp'],
            "timestamp": latest_data['timestamp'].isoformat()
        }
        
        logger.info(f"Latest sensor data retrieved for farmer {farmer_id}")
        
        return jsonify({
            "message": "Latest sensor data retrieved successfully",
            "sensorData": sensor_info
        }), 200
    
    except Exception as e:
        logger.error(f"Error retrieving latest sensor data for farmer {farmer_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    if email != os.getenv("ADMIN_EMAIL") or password != os.getenv("ADMIN_PASSWORD"):
        return jsonify({"error": "Invalid admin credentials"}), 401

    token = pyjwt.encode(
        {
            "identity": "admin",
            "role": "admin",
            "exp": datetime.utcnow() + timedelta(hours=8)
        },
        os.getenv("ADMIN_SECRET_KEY"),
        algorithm="HS256"
    )

    return jsonify({
        "message": "Admin login successful",
        "token": token
    }), 200

@app.route('/api/admin/pending-registrations', methods=['GET'])
@admin_jwt_required()
def get_pending_registrations():
    try:
        applications = list(
            pending_verifications_collection.find(
                {"status": "pending_verification"},
                {"documentImage": 0}
            ).sort("submittedAt", -1)
        )

        formatted = []
        for app_data in applications:
            formatted.append({
                "applicationId": app_data["_id"],
                "name": app_data.get("name", ""),
                "email": app_data.get("email", ""),
                "mobileNumber": app_data.get("mobileNumber", ""),
                "professionalRole": app_data.get("professionalRole", ""),
                "licenseNumber": app_data.get("licenseNumber", ""),
                "district": app_data.get("district", ""),
                "state": app_data.get("state", ""),
                "submittedAt": app_data["submittedAt"].strftime("%Y-%m-%dT%H:%M:%S.000Z") if app_data.get("submittedAt") else None,
            })

        return jsonify({"applications": formatted, "total": len(formatted)}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/admin/application/<application_id>', methods=['GET'])
@admin_jwt_required()
def get_application_detail(application_id):
    try:
        app_data = pending_verifications_collection.find_one({"_id": application_id})
        if not app_data:
            return jsonify({"error": "Application not found"}), 404

        application = {
            "applicationId": app_data["_id"],
            "name": app_data.get("name", ""),
            "email": app_data.get("email", ""),
            "mobileNumber": app_data.get("mobileNumber", ""),
            "professionalRole": app_data.get("professionalRole", ""),
            "licenseNumber": app_data.get("licenseNumber", ""),
            "address": app_data.get("address", ""),
            "cityVillage": app_data.get("cityVillage", ""),
            "district": app_data.get("district", ""),
            "state": app_data.get("state", ""),
            "pincode": app_data.get("pincode", ""),
            "documentImage": app_data.get("documentImage", ""),
            "status": app_data.get("status", ""),
            "submittedAt": app_data["submittedAt"].strftime("%Y-%m-%dT%H:%M:%S.000Z") if app_data.get("submittedAt") else None,

        }

        return jsonify({"application": application}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/admin/approve/<application_id>', methods=['POST'])
@admin_jwt_required()
def approve_registration(application_id):
    try:
        application = pending_verifications_collection.find_one({"_id": application_id})
        if not application:
            return jsonify({"error": "Application not found"}), 404

        if application.get("status") != "pending_verification":
            return jsonify({"error": "Application already processed"}), 400

        agriculturalists_collection.insert_one({
            "_id": application["_id"],
            "name": application["name"],
            "email": application["email"],
            "mobileNumber": application["mobileNumber"],
            "password": application["password"],
            "address": application["address"],
            "cityVillage": application["cityVillage"],
            "district": application["district"],
            "state": application["state"],
            "pincode": application["pincode"],
            "upiId": application.get("upiId", ""),
            "professionalRole": application["professionalRole"],
            "licenseNumber": application["licenseNumber"],
            "isAvailable": True,
            "isEmailVerified": False,
            "status": "approved",
            "createdAt": datetime.now(pytz.UTC),
            "updatedAt": datetime.now(pytz.UTC)
        })

        otp = ''.join(random.choices(string.digits, k=6))
        otps_collection.replace_one(
            {"userId": application_id},
            {
                "userId": application_id,
                "otp": otp,
                "createdAt": datetime.now(pytz.UTC)
            },
            upsert=True
        )

        smtp_email = os.getenv("SMTP_EMAIL")
        smtp_password = os.getenv("SMTP_PASSWORD")

        msg = MIMEMultipart()
        msg["Subject"] = "Welcome to Agro-Intel — Application Approved"
        msg["From"] = smtp_email
        msg["To"] = application["email"]

        body = f"""
Dear {application['name']},

Congratulations! Your agriculturalist registration has been approved.

Your Agriculturalist ID: {application_id}

Please use the OTP below to verify your email and activate your account:

OTP: {otp}

This OTP expires in 10 minutes.

After verification, you can log in to the Agro-Intel portal.

Regards,
Agro-Intel Team
"""
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(smtp_email, smtp_password)
            server.send_message(msg)

        pending_verifications_collection.update_one(
            {"_id": application_id},
            {"$set": {"status": "approved", "approvedAt": datetime.now(pytz.UTC)}}
        )

        return jsonify({
            "message": "Application approved. OTP email sent.",
            "agriculturalistId": application_id
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/admin/reject/<application_id>', methods=['POST'])
@admin_jwt_required()
def reject_registration(application_id):
    try:
        data = request.get_json() or {}
        reason = data.get("reason", "Your application could not be approved at this time.")

        application = pending_verifications_collection.find_one({"_id": application_id})
        if not application:
            return jsonify({"error": "Application not found"}), 404

        if application.get("status") != "pending_verification":
            return jsonify({"error": "Application already processed"}), 400

        smtp_email = os.getenv("SMTP_EMAIL")
        smtp_password = os.getenv("SMTP_PASSWORD")

        msg = MIMEMultipart()
        msg["Subject"] = "Agro-Intel Registration Update"
        msg["From"] = smtp_email
        msg["To"] = application["email"]

        body = f"""
Dear {application['name']},

Thank you for applying to join Agro-Intel as an agricultural expert.

After reviewing your submitted details and documents, your registration request was not approved.

Reason: {reason}

You will not receive an Agriculturalist ID and you cannot log in to the Agro-Intel portal with this request.

If needed, please contact support@agrointel.com.

Regards,
Agro-Intel Team
"""
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(smtp_email, smtp_password)
            server.send_message(msg)

        pending_verifications_collection.update_one(
            {"_id": application_id},
            {"$set": {
                "status": "rejected",
                "rejectedAt": datetime.now(pytz.UTC),
                "rejectionReason": reason
            }}
        )

        return jsonify({"message": "Application rejected and applicant notified."}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ================= SLOT BOOKING ENDPOINTS =================

@app.route('/api/agriculturalist-set-availability-slots', methods=['POST'])
@jwt_required()
def agriculturalist_set_availability_slots():
    """Endpoint: Agriculturalist sets their availability slots"""
    data = request.get_json()
    
    current_user_id = get_jwt_identity()
    
    claims = get_jwt()
    user_type = claims.get('userType', None)
    
    if user_type != "agriculturalist":
        return jsonify({"error": "Only agriculturalists can set availability slots"}), 403
    
    # agriculturalistId is COMPULSORY
    required_fields = ['agriculturalistId', 'date', 'slots']
    if not all(field in data for field in required_fields):
        missing = [field for field in required_fields if field not in data]
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400
    
    # Validate agriculturalistId matches JWT (Security Check)
    if data['agriculturalistId'] != current_user_id:
        logger.warning(f"Security Alert: User {current_user_id} attempted to modify slots for {data['agriculturalistId']}")
        return jsonify({"error": "You can only set slots for your own profile"}), 403
    
    try:
        slot_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        today = datetime.now(pytz.timezone('Asia/Kolkata')).date()
        max_date = today + timedelta(days=7)
        
        if slot_date < today:
            return jsonify({"error": "Cannot set availability for past dates"}), 400
        
        if slot_date > max_date:
            return jsonify({"error": "Cannot set availability more than 7 days in advance"}), 400
        
        if not isinstance(data['slots'], list):
            return jsonify({"error": "Slots must be an array of time strings"}), 400
        
        if len(data['slots']) == 0:
            return jsonify({"error": "Slots array cannot be empty"}), 400
        
        all_time_slots = generate_time_slots()
        valid_slot_times = [slot['start'] for slot in all_time_slots]
        
        for slot_time in data['slots']:
            if slot_time not in valid_slot_times:
                return jsonify({"error": f"Invalid slot time: {slot_time}. Must be in HH:MM format (00:00 to 23:30 in 30-min intervals)"}), 400
        
        day_of_week = slot_date.strftime('%A')
        
        inserted_count = 0
        for slot_time in data['slots']:
            slot_info = next(s for s in all_time_slots if s['start'] == slot_time)
            
            slot_document = {
                "agriculturalistId": current_user_id,
                "date": data['date'],
                "slotTime": slot_time,
                "slotEndTime": slot_info['end'],
                "dayOfWeek": day_of_week,
                "isBooked": False,
                "bookedBy": None,
                "createdAt": datetime.now(pytz.UTC)
            }
            
            result = availability_slots_collection.update_one(
                {
                    "agriculturalistId": current_user_id,
                    "date": data['date'],
                    "slotTime": slot_time
                },
                {"$setOnInsert": slot_document},
                upsert=True
            )
            
            if result.upserted_id:
                inserted_count += 1
        
        logger.info(f"Agriculturalist {current_user_id} set {inserted_count} new slots for {data['date']}")
        
        return jsonify({
            "message": "Availability slots set successfully",
            "agriculturalistId": current_user_id,
            "date": data['date'],
            "slotsAdded": inserted_count,
            "totalSlots": len(data['slots'])
        }), 201
    
    except ValueError:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400
    except Exception as e:
        logger.error(f"Error setting availability slots: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/farmer-get-available-slots/<agriculturalist_id>', methods=['GET'])
@jwt_required()
def farmer_get_available_slots(agriculturalist_id):
    """Endpoint: Farmer gets available slots for an agriculturalist"""
    try:
        current_user_id = get_jwt_identity()
        
        date = request.args.get('date', None)
        
        if not date:
            return jsonify({"error": "Date parameter is required"}), 400
        
        agriculturalist = agriculturalists_collection.find_one({"_id": agriculturalist_id})
        if not agriculturalist:
            return jsonify({"error": "Agriculturalist not found"}), 404
        
        available_slots = availability_slots_collection.find({
            "agriculturalistId": agriculturalist_id,
            "date": date,
            "isBooked": False
        }).sort("slotTime", 1)
        
        slots_list = []
        for slot in available_slots:
            slot_info = {
                "slotId": str(slot['_id']),
                "slotTime": slot['slotTime'],
                "slotEndTime": slot['slotEndTime'],
                "dayOfWeek": slot['dayOfWeek']
            }
            slots_list.append(slot_info)
        
        logger.info(f"Farmer {current_user_id} retrieved {len(slots_list)} available slots for agriculturalist {agriculturalist_id} on {date}")
        
        return jsonify({
            "message": "Available slots retrieved successfully",
            "agriculturalistId": agriculturalist_id,
            "agriculturalistName": agriculturalist['name'],
            "date": date,
            "availableSlots": slots_list,
            "count": len(slots_list)
        }), 200
    
    except Exception as e:
        logger.error(f"Error retrieving available slots: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/farmer-book-slot', methods=['POST'])
@jwt_required()
def farmer_book_slot():
    """Endpoint: Farmer books a slot with an agriculturalist"""
    data = request.get_json()
    
    current_user_id = get_jwt_identity()
    
    claims = get_jwt()
    user_type = claims.get('userType', None)
    
    if user_type != "farmer":
        return jsonify({"error": "Only farmers can book slots"}), 403
    
    required_fields = ['agriculturalistId', 'date', 'slotTime']
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing required fields: agriculturalistId, date, slotTime"}), 400
    
    try:
        agriculturalist = agriculturalists_collection.find_one({"_id": data['agriculturalistId']})
        if not agriculturalist:
            return jsonify({"error": "Agriculturalist not found"}), 404
        
        existing_booking = appointments_collection.find_one({
        "farmerId": current_user_id,
        "agriculturalistId": data["agriculturalistId"],
        "status": "booked"
        })

        if existing_booking:
             return jsonify({
            "error": "You already have an active booking with this agriculturalist. Please cancel the existing appointment before booking again."
             }), 409
        
        slot = availability_slots_collection.find_one({
            "agriculturalistId": data['agriculturalistId'],
            "date": data['date'],
            "slotTime": data['slotTime']
        })
        
        if not slot:
            return jsonify({"error": "Slot not found or not available"}), 404
        
        if slot['isBooked']:
            return jsonify({"error": "This slot is already booked"}), 409
        
        update_result = availability_slots_collection.update_one(
            {
                "_id": slot['_id'],
                "isBooked": False
            },
            {
                "$set": {
                    "isBooked": True,
                    "bookedBy": current_user_id,
                    "bookedAt": datetime.now(pytz.UTC)
                }
            }
        )
        
        if update_result.modified_count == 0:
            return jsonify({"error": "Slot was just booked by someone else"}), 409
        
        appointment = {
            "farmerId": current_user_id,
            "agriculturalistId": data['agriculturalistId'],
            "slotId": slot['_id'],
            "date": data['date'],
            "slotTime": slot['slotTime'],
            "slotEndTime": slot['slotEndTime'],
            "dayOfWeek": slot['dayOfWeek'],
            "status": "booked",
            "createdAt": datetime.now(pytz.UTC)
        }
        
        result = appointments_collection.insert_one(appointment)
        
        logger.info(f"Farmer {current_user_id} booked slot with agriculturalist {data['agriculturalistId']} on {data['date']} at {data['slotTime']}")
        
        return jsonify({
            "message": "Slot booked successfully",
            "appointmentId": str(result.inserted_id),
            "agriculturalistId": data['agriculturalistId'],
            "agriculturalistName": agriculturalist['name'],
            "date": data['date'],
            "slotTime": slot['slotTime'],
            "slotEndTime": slot['slotEndTime']
        }), 201
    
    except Exception as e:
        logger.error(f"Error booking slot: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/farmer-appointments/<farmer_id>', methods=['GET'])
@jwt_required()
def get_farmer_appointments(farmer_id):
    """Endpoint: Get all appointments for a farmer"""
    try:
        auto_complete_past_appointments()
        current_user_id = get_jwt_identity()
        
        if current_user_id != farmer_id:
            return jsonify({"error": "Unauthorized access"}), 403
        
        status = request.args.get('status', None)
        
        query = {"farmerId": farmer_id}
        if status:
            query["status"] = status
        
        appointments = appointments_collection.find(query).sort("createdAt", -1)
        
        appointments_list = []
        for appointment in appointments:
            agriculturalist = agriculturalists_collection.find_one({"_id": appointment['agriculturalistId']})
            
            appointment_info = {
                "appointmentId": str(appointment['_id']),
                "agriculturalistId": appointment['agriculturalistId'],
                "agriculturalistName": agriculturalist['name'] if agriculturalist else "Unknown",
                "date": appointment['date'],
                "slotTime": appointment['slotTime'],
                "slotEndTime": appointment['slotEndTime'],
                "dayOfWeek": appointment['dayOfWeek'],
                "status": appointment['status'],
                "createdAt": appointment['createdAt'].isoformat() if 'createdAt' in appointment else None
            }
            appointments_list.append(appointment_info)
        
        logger.info(f"Retrieved {len(appointments_list)} appointments for farmer {farmer_id}")
        
        return jsonify({
            "message": "Appointments retrieved successfully",
            "count": len(appointments_list),
            "appointments": appointments_list
        }), 200
    
    except Exception as e:
        logger.error(f"Error retrieving farmer appointments: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/agriculturalist-appointments/<agriculturalist_id>', methods=['GET'])
@jwt_required()
def get_agriculturalist_appointments(agriculturalist_id):
    """Endpoint: Get all appointments for an agriculturalist"""
    try:
        auto_complete_past_appointments()
        current_user_id = get_jwt_identity()
        
        if current_user_id != agriculturalist_id:
            return jsonify({"error": "Unauthorized access"}), 403
        
        status = request.args.get('status', None)
        
        query = {"agriculturalistId": agriculturalist_id}
        if status:
            query["status"] = status
        
        appointments = appointments_collection.find(query).sort("createdAt", -1)
        
        appointments_list = []
        for appointment in appointments:
            farmer = farmers_collection.find_one({"_id": appointment['farmerId']})
            
            appointment_info = {
                "appointmentId": str(appointment['_id']),
                "farmerId": appointment['farmerId'],
                "farmerName": farmer['name'] if farmer else "Unknown",
                "farmerMobile": farmer['mobileNumber'] if farmer else "Unknown",
                "date": appointment['date'],
                "slotTime": appointment['slotTime'],
                "slotEndTime": appointment['slotEndTime'],
                "dayOfWeek": appointment['dayOfWeek'],
                "status": appointment['status'],
                "createdAt": appointment['createdAt'].isoformat() if 'createdAt' in appointment else None
            }
            appointments_list.append(appointment_info)
        
        logger.info(f"Retrieved {len(appointments_list)} appointments for agriculturalist {agriculturalist_id}")
        
        return jsonify({
            "message": "Appointments retrieved successfully",
            "count": len(appointments_list),
            "appointments": appointments_list
        }), 200
    
    except Exception as e:
        logger.error(f"Error retrieving agriculturalist appointments: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/cancel-appointment/<appointment_id>', methods=['POST'])
@jwt_required()
def cancel_appointment(appointment_id):
    """Endpoint: Cancel an appointment (both farmer and agriculturalist can cancel)"""
    try:
        current_user_id = get_jwt_identity()
        
        appointment = appointments_collection.find_one({"_id": ObjectId(appointment_id)})
        
        if not appointment:
            return jsonify({"error": "Appointment not found"}), 404
        
        if current_user_id != appointment['farmerId'] and current_user_id != appointment['agriculturalistId']:
            return jsonify({"error": "Unauthorized access"}), 403
        
        if appointment['status'] in ['cancelled', 'completed']:
            return jsonify({"error": f"Appointment is already {appointment['status']}"}), 400
        
        appointments_collection.update_one(
            {"_id": ObjectId(appointment_id)},
            {
                "$set": {
                    "status": "cancelled",
                    "cancelledBy": current_user_id,
                    "cancelledAt": datetime.now(pytz.UTC)
                }
            }
        )
        
        availability_slots_collection.update_one(
            {"_id": appointment['slotId']},
            {
                "$set": {
                    "isBooked": False,
                    "bookedBy": None
                },
                "$unset": {
                    "bookedAt": ""
                }
            }
        )
        
        logger.info(f"Appointment {appointment_id} cancelled by {current_user_id}")
        
        return jsonify({
            "message": "Appointment cancelled successfully",
            "appointmentId": appointment_id
        }), 200
    
    except Exception as e:
        logger.error(f"Error cancelling appointment: {str(e)}")
        return jsonify({"error": str(e)}), 500
    
@app.route("/api/reschedule-appointment/<appointment_id>", methods=["POST"])
@jwt_required()
def reschedule_appointment(appointment_id):
    try:
        current_user_id = get_jwt_identity()
        claims = get_jwt()
        user_type = claims.get("userType", None)

        if user_type != "agriculturalist":
            return jsonify({"error": "Only agriculturalists can reschedule appointments"}), 403

        data = request.get_json()

        if not data:
            return jsonify({"error": "Request body is required"}), 400

        required_fields = ["newDate", "newSlotTime"]
        if not all(field in data for field in required_fields):
            return jsonify({"error": "Missing required fields newDate and newSlotTime"}), 400

        appointment = appointments_collection.find_one({"_id": ObjectId(appointment_id)})
        if not appointment:
            return jsonify({"error": "Appointment not found"}), 404

        if appointment["agriculturalistId"] != current_user_id:
            return jsonify({"error": "You can only reschedule your own appointments"}), 403

        if appointment["status"] != "booked":
            return jsonify({
                "error": f"Only booked appointments can be rescheduled. Current status: {appointment['status']}"
            }), 400

        old_date = appointment["date"]
        old_slot_time = appointment["slotTime"]
        farmer_id = appointment["farmerId"]
        agriculturalist_id = appointment["agriculturalistId"]

        new_date = data["newDate"]
        new_slot_time = data["newSlotTime"]

        try:
            slot_date = datetime.strptime(new_date, "%Y-%m-%d").date()
            today = datetime.now(pytz.timezone("Asia/Kolkata")).date()
            max_date = today + timedelta(days=7)

            if slot_date < today:
                return jsonify({"error": "Cannot reschedule to a past date"}), 400

            if slot_date > max_date:
                return jsonify({"error": "Cannot reschedule more than 7 days in advance"}), 400
        except ValueError:
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

        new_slot = availability_slots_collection.find_one({
            "agriculturalistId": current_user_id,
            "date": new_date,
            "slotTime": new_slot_time
        })

        if not new_slot:
            return jsonify({"error": "Selected slot not found"}), 404

        if new_slot.get("isBooked", False):
            return jsonify({"error": "Selected slot is already booked"}), 409

        old_slot_id = appointment.get("slotId")

        book_new_slot = availability_slots_collection.update_one(
            {
                "_id": new_slot["_id"],
                "isBooked": False
            },
            {
                "$set": {
                    "isBooked": True,
                    "bookedBy": farmer_id,
                    "bookedAt": datetime.now(pytz.UTC)
                }
            }
        )

        if book_new_slot.modified_count == 0:
            return jsonify({"error": "Slot was just booked by someone else"}), 409

        if old_slot_id:
            availability_slots_collection.update_one(
                {"_id": old_slot_id},
                {
                    "$set": {
                        "isBooked": False,
                        "bookedBy": None
                    },
                    "$unset": {
                        "bookedAt": ""
                    }
                }
            )

        appointments_collection.update_one(
            {"_id": ObjectId(appointment_id)},
            {
                "$set": {
                    "slotId": new_slot["_id"],
                    "date": new_date,
                    "slotTime": new_slot["slotTime"],
                    "slotEndTime": new_slot["slotEndTime"],
                    "dayOfWeek": new_slot["dayOfWeek"],
                    "updatedAt": datetime.now(pytz.UTC),
                    "rescheduledBy": current_user_id,
                    "rescheduledAt": datetime.now(pytz.UTC)
                }
            }
        )

        farmer = farmers_collection.find_one({"_id": farmer_id})
        agriculturalist = agriculturalists_collection.find_one({"_id": agriculturalist_id})

        if farmer and agriculturalist and farmer.get("email"):
            send_reschedule_email_to_farmer(
                farmer_email=farmer["email"],
                farmer_name=farmer.get("name", "Farmer"),
                agriculturalist_name=agriculturalist.get("name", "Agriculturalist"),
                old_date=old_date,
                old_slot_time=old_slot_time,
                new_date=new_date,
                new_slot_time=new_slot["slotTime"]
            )

        logger.info(f"Appointment {appointment_id} rescheduled by agriculturalist {current_user_id}")

        return jsonify({
            "message": "Appointment rescheduled successfully",
            "appointmentId": appointment_id,
            "newDate": new_date,
            "newSlotTime": new_slot["slotTime"],
            "newSlotEndTime": new_slot["slotEndTime"]
        }), 200

    except Exception as e:
        logger.error(f"Error rescheduling appointment: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/agriculturalist-availability-slots', methods=['POST'])
@jwt_required()
def agriculturalist_availability_slots():
    """Endpoint: Agriculturalist views their own availability slots"""
    data = request.get_json()
    
    current_user_id = get_jwt_identity()
    
    # agriculturalistId is COMPULSORY
    if 'agriculturalistId' not in data:
        return jsonify({"error": "Missing required field: agriculturalistId"}), 400
    
    if data['agriculturalistId'] != current_user_id:
        return jsonify({"error": "You can only view slots for your own profile"}), 403
    
    try:
        agriculturalist_id = data['agriculturalistId']
        date = data.get('date', None)
        
        query = {"agriculturalistId": agriculturalist_id}
        if date:
            query["date"] = date
        
        slots = availability_slots_collection.find(query).sort([("date", 1), ("slotTime", 1)])
        
        slots_by_date = {}
        for slot in slots:
            slot_date = slot['date']
            if slot_date not in slots_by_date:
                slots_by_date[slot_date] = []
            
            slot_info = {
                "slotId": str(slot['_id']),
                "slotTime": slot['slotTime'],
                "slotEndTime": slot['slotEndTime'],
                "isBooked": slot['isBooked'],
                "bookedBy": slot.get('bookedBy', None)
            }
            slots_by_date[slot_date].append(slot_info)
        
        logger.info(f"Retrieved availability slots for agriculturalist {agriculturalist_id}")
        
        return jsonify({
            "message": "Availability slots retrieved successfully",
            "agriculturalistId": agriculturalist_id,
            "slotsByDate": slots_by_date
        }), 200
    
    except Exception as e:
        logger.error(f"Error retrieving availability slots: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ================= PASSWORD UPDATE ENDPOINTS =================

@app.route('/api/update-password-farmer', methods=['POST'])
@jwt_required()
def update_password_farmer():
    """Endpoint: Initiate farmer password change (sends OTP)"""
    data = request.get_json()
    current_user_id = get_jwt_identity()
    
    try:
        # Check required fields
        required_fields = ['oldPassword', 'newPassword']
        if not all(field in data for field in required_fields):
            return jsonify({"error": "Missing oldPassword or newPassword"}), 400
        
        # Find farmer
        farmer = farmers_collection.find_one({"_id": current_user_id})
        if not farmer:
            return jsonify({"error": "Farmer not found"}), 404
        
        # Verify old password
        if not bcrypt.checkpw(data['oldPassword'].encode('utf-8'), farmer['password']):
            logger.warning(f"Invalid old password attempt for farmer {current_user_id}")
            return jsonify({"error": "Old password is incorrect"}), 401
        
        # Validate new password format
        is_valid, error_msg = validate_password(data['newPassword'])
        if not is_valid:
            return jsonify({"error": error_msg}), 400
        
        # Check if old and new password are the same
        if data['oldPassword'] == data['newPassword']:
            return jsonify({"error": "New password must be different from old password"}), 400
        
        # Generate OTP
        otp = generate_otp()
        hashed_otp = bcrypt.hashpw(otp.encode('utf-8'), bcrypt.gensalt())
        hashed_new_password = bcrypt.hashpw(data['newPassword'].encode('utf-8'), bcrypt.gensalt())
        
        # Store pending password change
        pending_password_update = {
            "userId": current_user_id,
            "type": "update_password_farmer",
            "userType": "farmer",
            "email": farmer['email'],
            "newPassword": hashed_new_password,
            "otp": hashed_otp,
            "createdAt": datetime.now(pytz.UTC)
        }
        
        pending_updates_collection.replace_one(
            {"userId": current_user_id, "type": "update_password_farmer"},
            pending_password_update,
            upsert=True
        )
        
        # Send OTP email
        if send_otp_email(farmer['email'], otp):
            logger.info(f"Password update OTP sent to {farmer['email']} for farmer {current_user_id}")
            return jsonify({
                "message": "OTP sent to your email for password verification",
                "farmerId": current_user_id,
                "email": farmer['email']
            }), 200
        else:
            pending_updates_collection.delete_one({"userId": current_user_id, "type": "update_password_farmer"})
            logger.error(f"Failed to send OTP email for farmer {current_user_id}")
            return jsonify({"error": "Failed to send OTP email"}), 500
    
    except Exception as e:
        logger.error(f"Error updating farmer password: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/confirm/update-password-farmer', methods=['POST'])
@jwt_required()
def confirm_update_password_farmer():
    """Endpoint: Confirm farmer password change with OTP"""
    data = request.get_json()
    current_user_id = get_jwt_identity()
    
    try:
        # Check required fields
        required_fields = ['otp']
        if not all(field in data for field in required_fields):
            return jsonify({"error": "Missing otp"}), 400
        
        # Find pending password update
        pending_update = pending_updates_collection.find_one({
            "userId": current_user_id,
            "type": "update_password_farmer"
        })
        
        if not pending_update:
            return jsonify({"error": "No pending password update found or expired"}), 404
        
        # Verify OTP
        if not bcrypt.checkpw(data['otp'].encode('utf-8'), pending_update['otp']):
            logger.warning(f"Invalid OTP for farmer password update {current_user_id}")
            return jsonify({"error": "Invalid OTP"}), 401
        
        # Update password
        result = farmers_collection.update_one(
            {"_id": current_user_id},
            {
                "$set": {
                    "password": pending_update['newPassword'],
                    "updatedAt": datetime.now(pytz.UTC)
                }
            }
        )
        
        if result.modified_count == 0:
            logger.error(f"Failed to update password for farmer {current_user_id}")
            return jsonify({"error": "Failed to update password"}), 500
        
        # Delete pending update
        pending_updates_collection.delete_one({
            "userId": current_user_id,
            "type": "update_password_farmer"
        })
        
        logger.info(f"Password updated successfully for farmer {current_user_id}")
        
        return jsonify({
            "message": "Password changed successfully",
            "farmerId": current_user_id
        }), 200
    
    except Exception as e:
        logger.error(f"Error confirming farmer password update: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/update-password-agriculturalist', methods=['POST'])
@jwt_required()
def update_password_agriculturalist():
    """Endpoint: Initiate agriculturalist password change (sends OTP)"""
    data = request.get_json()
    current_user_id = get_jwt_identity()
    
    try:
        # Check required fields
        required_fields = ['oldPassword', 'newPassword']
        if not all(field in data for field in required_fields):
            return jsonify({"error": "Missing oldPassword or newPassword"}), 400
        
        # Find agriculturalist
        agriculturalist = agriculturalists_collection.find_one({"_id": current_user_id})
        if not agriculturalist:
            return jsonify({"error": "Agriculturalist not found"}), 404
        
        # Verify old password
        if not bcrypt.checkpw(data['oldPassword'].encode('utf-8'), agriculturalist['password']):
            logger.warning(f"Invalid old password attempt for agriculturalist {current_user_id}")
            return jsonify({"error": "Old password is incorrect"}), 401
        
        # Validate new password format
        is_valid, error_msg = validate_password(data['newPassword'])
        if not is_valid:
            return jsonify({"error": error_msg}), 400
        
        # Check if old and new password are the same
        if data['oldPassword'] == data['newPassword']:
            return jsonify({"error": "New password must be different from old password"}), 400
        
        # Generate OTP
        otp = generate_otp()
        hashed_otp = bcrypt.hashpw(otp.encode('utf-8'), bcrypt.gensalt())
        hashed_new_password = bcrypt.hashpw(data['newPassword'].encode('utf-8'), bcrypt.gensalt())
        
        # Store pending password change
        pending_password_update = {
            "userId": current_user_id,
            "type": "update_password_agriculturalist",
            "userType": "agriculturalist",
            "email": agriculturalist['email'],
            "newPassword": hashed_new_password,
            "otp": hashed_otp,
            "createdAt": datetime.now(pytz.UTC)
        }
        
        pending_updates_collection.replace_one(
            {"userId": current_user_id, "type": "update_password_agriculturalist"},
            pending_password_update,
            upsert=True
        )
        
        # Send OTP email
        if send_otp_email(agriculturalist['email'], otp):
            logger.info(f"Password update OTP sent to {agriculturalist['email']} for agriculturalist {current_user_id}")
            return jsonify({
                "message": "OTP sent to your email for password verification",
                "agriculturalistId": current_user_id,
                "email": agriculturalist['email']
            }), 200
        else:
            pending_updates_collection.delete_one({"userId": current_user_id, "type": "update_password_agriculturalist"})
            logger.error(f"Failed to send OTP email for agriculturalist {current_user_id}")
            return jsonify({"error": "Failed to send OTP email"}), 500
    
    except Exception as e:
        logger.error(f"Error updating agriculturalist password: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/confirm/update-password-agriculturalist', methods=['POST'])
@jwt_required()
def confirm_update_password_agriculturalist():
    """Endpoint: Confirm agriculturalist password change with OTP"""
    data = request.get_json()
    current_user_id = get_jwt_identity()
    
    try:
        # Check required fields
        required_fields = ['otp']
        if not all(field in data for field in required_fields):
            return jsonify({"error": "Missing otp"}), 400
        
        # Find pending password update
        pending_update = pending_updates_collection.find_one({
            "userId": current_user_id,
            "type": "update_password_agriculturalist"
        })
        
        if not pending_update:
            return jsonify({"error": "No pending password update found or expired"}), 404
        
        # Verify OTP
        if not bcrypt.checkpw(data['otp'].encode('utf-8'), pending_update['otp']):
            logger.warning(f"Invalid OTP for agriculturalist password update {current_user_id}")
            return jsonify({"error": "Invalid OTP"}), 401
        
        # Update password
        result = agriculturalists_collection.update_one(
            {"_id": current_user_id},
            {
                "$set": {
                    "password": pending_update['newPassword'],
                    "updatedAt": datetime.now(pytz.UTC)
                }
            }
        )
        
        if result.modified_count == 0:
            logger.error(f"Failed to update password for agriculturalist {current_user_id}")
            return jsonify({"error": "Failed to update password"}), 500
        
        # Delete pending update
        pending_updates_collection.delete_one({
            "userId": current_user_id,
            "type": "update_password_agriculturalist"
        })
        
        logger.info(f"Password updated successfully for agriculturalist {current_user_id}")
        
        return jsonify({
            "message": "Password changed successfully",
            "agriculturalistId": current_user_id
        }), 200
    
    except Exception as e:
        logger.error(f"Error confirming agriculturalist password update: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ================= FORGOT PASSWORD ENDPOINTS =================

@app.route('/api/forgot-password', methods=['POST'])
def forgot_password():
    """Endpoint: Initiate forgot password for both farmer and agriculturalist"""
    data = request.get_json()
    
    required_fields = ['email', 'newPassword']
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing email or newPassword"}), 400
    
    is_valid, error_msg = validate_email_format(data['email'])
    if not is_valid:
        return jsonify({"error": error_msg}), 400
    
    is_valid, error_msg = validate_password(data['newPassword'])
    if not is_valid:
        return jsonify({"error": error_msg}), 400
    
    try:
        user = farmers_collection.find_one({"email": data['email']})
        user_type = "farmer"
        
        if not user:
            user = agriculturalists_collection.find_one({"email": data['email']})
            user_type = "agriculturalist"
        
        if not user:
            logger.warning(f"Forgot password attempt with non-existent email: {data['email']}")
            return jsonify({"error": "User not found"}), 404
        
        if not user.get('isEmailVerified', False):
            return jsonify({"error": "Email not verified. Please complete registration first."}), 403
        
        user_id = user['_id']
        
        hashed_password = bcrypt.hashpw(data['newPassword'].encode('utf-8'), bcrypt.gensalt())
        otp = generate_otp()
        hashed_otp = bcrypt.hashpw(otp.encode('utf-8'), bcrypt.gensalt())
        
        pending_password_change = {
            "userId": user_id,
            "type": "forgot_password",
            "userType": user_type,
            "email": data['email'],
            "newPassword": hashed_password,
            "otp": hashed_otp,
            "createdAt": datetime.now(pytz.UTC)
        }
        
        pending_updates_collection.replace_one(
            {"userId": user_id, "type": "forgot_password"},
            pending_password_change,
            upsert=True
        )
        
        if send_otp_email(data['email'], otp):
            logger.info(f"Forgot password OTP sent to {data['email']} for user {user_id}")
            return jsonify({
                "message": "OTP sent successfully",
                "userId": user_id,
                "userType": user_type
            }), 200
        else:
            pending_updates_collection.delete_one({"userId": user_id, "type": "forgot_password"})
            logger.error(f"Failed to send OTP email for forgot password: {user_id}")
            return jsonify({"error": "Failed to send OTP email"}), 500
    
    except Exception as e:
        logger.error(f"Error during forgot password: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/confirm-forgot-password', methods=['POST'])
def confirm_forgot_password():
    """Endpoint: Confirm forgot password with OTP and update password"""
    data = request.get_json()
    
    required_fields = ['userId', 'otp']
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing userId or otp"}), 400
    
    try:
        pending_password_change = pending_updates_collection.find_one({
            "userId": data['userId'],
            "type": "forgot_password"
        })
        
        if not pending_password_change:
            return jsonify({"error": "Pending password change not found or expired"}), 404
        
        if not bcrypt.checkpw(data['otp'].encode('utf-8'), pending_password_change['otp']):
            logger.warning(f"Invalid OTP for forgot password: {data['userId']}")
            return jsonify({"error": "Invalid OTP"}), 401
        
        user_id = pending_password_change['userId']
        user_type = pending_password_change['userType']
        new_password = pending_password_change['newPassword']
        
        if user_type == "farmer":
            result = farmers_collection.update_one(
                {"_id": user_id},
                {
                    "$set": {
                        "password": new_password,
                        "updatedAt": datetime.now(pytz.UTC)
                    }
                }
            )
        else:
            result = agriculturalists_collection.update_one(
                {"_id": user_id},
                {
                    "$set": {
                        "password": new_password,
                        "updatedAt": datetime.now(pytz.UTC)
                    }
                }
            )
        
        if result.modified_count == 0:
            logger.error(f"Failed to update password for user {user_id}")
            return jsonify({"error": "Failed to update password"}), 500
        
        pending_updates_collection.delete_one({
            "userId": user_id,
            "type": "forgot_password"
        })
        
        logger.info(f"Password changed successfully for {user_type} {user_id}")
        return jsonify({
            "message": "Password changed successfully",
            "userId": user_id,
            "userType": user_type
        }), 200
    
    except Exception as e:
        logger.error(f"Error confirming forgot password: {str(e)}")
        return jsonify({"error": str(e)}), 500
    

@app.route('/api/farmer-download-sensor-data/<farmer_id>', methods=['GET'])
@jwt_required()
def farmer_download_sensor_data(farmer_id):
    current_user_id = get_jwt_identity()

    if current_user_id != farmer_id:
        return jsonify({"error": "Unauthorized"}), 403

    data = sensor_data_collection.find({"farmerId": farmer_id}).sort("timestamp", -1)

    si = StringIO()
    writer = csv.writer(si)

    writer.writerow([
        "Timestamp", "Nitrogen", "Phosphorous", "Potassium",
        "Soil Moisture", "Soil pH", "Soil Temp"
    ])

    for d in data:
        writer.writerow([
            d['timestamp'],
            d['nitrogen'],
            d['phosphorous'],
            d['potassium'],
            d.get('soil_moisture') or d.get('soilMoisture'),
            d.get('soil_ph') or d.get('soilPH'),
            d.get('soil_temp') or d.get('soilTemp')
        ])

    return Response(
        si.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={farmer_id}.csv"}
    )


@app.route('/api/farmer-send-sensor-data/<farmer_id>', methods=['POST'])
@jwt_required()
def farmer_send_sensor_data(farmer_id):
    current_user_id = get_jwt_identity()

    if current_user_id != farmer_id:
        return jsonify({"error": "Unauthorized"}), 403

    # Check appointment exists
    data = request.get_json() or {}
    agriculturalist_id = data.get("agriculturalistId")

    if not agriculturalist_id:
        return jsonify({"error": "Missing required field agriculturalistId"}), 400

    appointment = appointments_collection.find_one(
    {
        "farmerId": farmer_id,
        "agriculturalistId": agriculturalist_id,
        "status": {"$in": ["booked", "completed"]}
    },
    sort=[("createdAt", -1)]
    )

    if not appointment:
       return jsonify(
        {"error": "No eligible appointment found with this agriculturalist"}
    ), 404

    agriculturalist = agriculturalists_collection.find_one(
    {"_id": agriculturalist_id}
    )

    if not agriculturalist:
       return jsonify({"error": "Agriculturalist not found"}), 404

    # Get sensor data
    data = sensor_data_collection.find({"farmerId": farmer_id}).sort("timestamp", -1)

    if sensor_data_collection.count_documents({"farmerId": farmer_id}) == 0:
        return jsonify({"error": "No sensor data"}), 404

    # Create CSV
    si = StringIO()
    writer = csv.writer(si)

    writer.writerow([
        "Timestamp", "Nitrogen", "Phosphorous", "Potassium",
        "Soil Moisture", "Soil pH", "Soil Temp"
    ])

    for d in data:
        writer.writerow([
            d['timestamp'],
            d['nitrogen'],
            d['phosphorous'],
            d['potassium'],
            d.get('soil_moisture') or d.get('soilMoisture'),
           d.get('soil_ph') or d.get('soilPH'),
            d.get('soil_temp') or d.get('soilTemp')
        ])

    # Email
    msg = MIMEMultipart()
    msg['Subject'] = 'Farmer Sensor Data'
    msg['From'] = SMTP_EMAIL
    msg['To'] = agriculturalist['email']

    # Get farmer details
    farmer = farmers_collection.find_one({"_id": farmer_id})

    # --------- FIX LOCATION ----------
    location_parts = list(filter(None, [
    farmer.get('village') or farmer.get('city'),
    farmer.get('district'),
    farmer.get('state')
    ]))

    location = ", ".join(location_parts)
    pincode = farmer.get('pincode')

    full_location = f"{location} - {pincode}" if pincode else (location if location else "N/A")
    # --------------------------------

    # Email body (clean formatting → no Gmail collapse)
    body = (
    f"Dear {agriculturalist.get('name', 'Agriculturalist')},\n\n"
    f"Farmer {farmer.get('name', farmer_id)} (ID: {farmer_id}) has shared their latest sensor data with you via the Agro-Intel platform.\n\n"
    f"Appointment ID: {str(appointment['_id'])}\n"
    f"Farmer Location: {full_location}\n"
    f"Device ID: {farmer.get('deviceId', 'N/A')}\n"
    f"Total Records: {sensor_data_collection.count_documents({'farmerId': farmer_id})}\n\n"
    f"Please find the sensor data CSV attached.\n\n"
    f"Regards,\n"
    f"Agro-Intel Platform"
    )

    # Create email
    msg = MIMEMultipart()
    msg['Subject'] = f"Agro-Intel: Sensor Data from Farmer {farmer.get('name', farmer_id)} ({farmer_id})"
    msg['From'] = SMTP_EMAIL
    msg['To'] = agriculturalist['email']

    # Attach body
    html_body = f"""
<html>
  <body style="font-family: Arial, sans-serif; line-height: 1.6;">
    <p>Dear {agriculturalist.get('name', 'Agriculturalist')},</p>

    <p>
      Farmer <b>{farmer.get('name', farmer_id)}</b> (ID: {farmer_id}) has shared their latest sensor data with you via the Agro-Intel platform.
    </p>

    <p>
      <b>Appointment ID:</b> {str(appointment['_id'])}<br>
      <b>Farmer Location:</b> {full_location}<br>
      <b>Device ID:</b> {farmer.get('deviceId', 'N/A')}<br>
      <b>Total Records:</b> {sensor_data_collection.count_documents({'farmerId': farmer_id})}
    </p>

    <p>Please find the sensor data CSV attached.</p>

    <p>
      Regards,<br>
      Agro-Intel Platform
    </p>
  </body>
</html>
"""

    msg.attach(MIMEText(html_body, 'html'))

    # Attach CSV
    attachment = MIMEApplication(si.getvalue(), Name="sensor_data.csv")
    attachment['Content-Disposition'] = 'attachment; filename="sensor_data.csv"'
    msg.attach(attachment)
    # Send email
    with smtplib.SMTP('smtp.gmail.com', 587) as server:
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)

    return jsonify({"message": "Sensor data sent successfully"}), 200

@app.route("/api/resend-otp-agriculturalist", methods=["POST"])
def resend_otp_agriculturalist():
    """Resend verification OTP for approved agriculturalist accounts"""
    data = request.get_json()
    agriculturalist_id = data.get("agriculturalistId")
    
    if not agriculturalist_id:
        return jsonify({"error": "Missing agriculturalistId"}), 400
    
    # Find approved but unverified agriculturalist
    agriculturalist = agriculturalists_collection.find_one({
        "_id": agriculturalist_id,
        "isEmailVerified": False
    })
    
    if not agriculturalist:
        return jsonify({"error": "Account not found or already verified"}), 404
    
    # Generate and store fresh OTP
    otp = generate_otp()
    otps_collection.replace_one(
        {"userId": agriculturalist_id},
        {"userId": agriculturalist_id, "otp": otp, "createdAt": datetime.now(pytz.UTC)},
        upsert=True
    )
    
    # Send OTP email
    if send_otp_email(agriculturalist["email"], otp):
        logger.info(f"Resent OTP to {agriculturalist['email']} for agriculturalist {agriculturalist_id}")
        return jsonify({"message": "OTP resent successfully"}), 200
    else:
        logger.error(f"Failed to resend OTP to {agriculturalist['email']} for {agriculturalist_id}")
        return jsonify({"error": "Failed to send OTP"}), 500


# ================= CHAT ENDPOINTS =================

@app.route('/api/chat/verify-access', methods=['POST'])
@jwt_required()
def verify_chat_access():
    data = request.get_json(silent=True) or {}
    current_user_id = get_jwt_identity()
    claims = get_jwt()
    user_type = claims.get('userType')

    if 'otherUserId' not in data:
        return jsonify({"error": "Missing otherUserId"}), 400

    other_user_id = data['otherUserId']

    try:
        if user_type == "farmer":
            farmer_id = current_user_id
            agriculturalist_id = other_user_id
        elif user_type == "agriculturalist":
            farmer_id = other_user_id
            agriculturalist_id = current_user_id
        else:
            logger.error(f"Invalid userType in JWT: {user_type}")
            return jsonify({"error": "Invalid user type"}), 403

        query = {
            "farmerId": farmer_id,
            "agriculturalistId": agriculturalist_id,
            "status": "completed"
        }

        logger.info(
            f"verify_chat_access: current_user_id={current_user_id}, "
            f"user_type={user_type}, other_user_id={other_user_id}, query={query}"
        )

        completed = appointments_collection.find_one(query)

        if not completed:
            logger.warning(f"No completed appointment found for query: {query}")
            return jsonify({
                "canChat": False,
                "error": "No completed appointment found between these users"
            }), 403

        room_id = f"CHAT_{farmer_id}_{agriculturalist_id}"
        logger.info(f"Chat access verified for {current_user_id} -> room {room_id}")
        return jsonify({"canChat": True, "roomId": room_id}), 200

    except Exception as e:
        logger.error(f"Error verifying chat access: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/chat/messages/<room_id>', methods=['GET'])
@jwt_required()
def get_chat_messages(room_id):
    """Endpoint: Get last 50 messages for a chat room (user must belong to the room)"""
    current_user_id = get_jwt_identity()

    parts = room_id.split("_")
    if len(parts) != 3 or parts[0] != "CHAT":
        return jsonify({"error": "Invalid room ID format"}), 400

    farmer_id = parts[1]
    agriculturalist_id = parts[2]

    if current_user_id not in [farmer_id, agriculturalist_id]:
        return jsonify({"error": "Unauthorized access to this chat room"}), 403

    try:
        raw_messages = list(
            chat_messages_collection.find(
                {"roomId": room_id}
            ).sort("timestamp", 1).limit(50)
        )
        messages = []
        for msg in raw_messages:
            messages.append({
                "messageId": str(msg["_id"]),
                "senderId": msg.get("senderId", ""),
                "senderRole": msg.get("senderRole", ""),
                "message": msg.get("message", ""),
                "edited": msg.get("edited", False),
                "timestamp": msg["timestamp"].isoformat() if hasattr(msg.get("timestamp"), "isoformat") else str(msg.get("timestamp", "")),
            })

        logger.info(f"Loaded {len(messages)} messages for room {room_id}")
        return jsonify({"messages": messages, "roomId": room_id}), 200

    except Exception as e:
        logger.error(f"Error loading chat messages for room {room_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/unread-counts/<user_id>', methods=['GET'])
@jwt_required()
def get_unread_counts(user_id):
    current_user_id = get_jwt_identity()
    if current_user_id != user_id:
        return jsonify({'error': 'Unauthorized'}), 403
    counts = list(unread_counts.find({'userId': user_id}, {'_id': 0}))
    return jsonify(counts), 200

@app.route('/api/unread-counts/<user_id>/<room_id>', methods=['DELETE'])
@jwt_required()
def clear_unread_count(user_id, room_id):
    current_user_id = get_jwt_identity()
    if current_user_id != user_id:
        return jsonify({'error': 'Unauthorized'}), 403
    unread_counts.delete_one({'userId': user_id, 'roomId': room_id})
    logger.info(f"Cleared unread count for {user_id} in room {room_id}")
    return jsonify({'success': True}), 200

# ================= SOCKET.IO EVENTS =================

@socketio.on("join_room")
def handle_join_room(data):
    """Socket.IO: User joins a chat room"""
    room_id = data.get("roomId")
    user_id = data.get("userId")

    if not room_id or not user_id:
        emit("error", {"message": "Missing roomId or userId"})
        return

    parts = room_id.split("_")
    if len(parts) != 3 or user_id not in [parts[1], parts[2]]:
        emit("error", {"message": "Unauthorized room access"})
        return

    join_room(room_id)
    emit("joined", {"roomId": room_id, "userId": user_id}, to=room_id)
    logger.info(f"User {user_id} joined room {room_id}")


@socketio.on("join_personal_room")
def handle_join_personal_room(data):
    """Socket.IO: User joins their personal notification room"""
    user_id = data.get("userId")

    if not user_id:
        emit("error", {"message": "Missing userId"})
        return

    join_room(str(user_id))
    emit("personal_room_joined", {"userId": str(user_id)}, to=str(user_id))
    logger.info(f"User {user_id} joined personal room {user_id}")


@socketio.on('send_message')
def handle_send_message(data):
    room_id = data.get('roomId')
    sender_id = data.get('senderId')
    sender_role = data.get('senderRole')
    receiver_id = data.get('receiverId')
    message = data.get('message', '').strip()

    if not all([room_id, sender_id, sender_role, receiver_id, message]):
        emit('error', {'message': 'Missing required fields'})
        return

    parts = room_id.split('_')
    if len(parts) != 3 or sender_id not in [parts[1], parts[2]]:
        emit('error', {'message': 'Unauthorized'})
        return

    try:
        msg_doc = {
            'roomId': room_id,
            'senderId': sender_id,
            'senderRole': sender_role,
            'message': message,
            'timestamp': datetime.now(pytz.UTC)
        }
        result = chat_messages_collection.insert_one(msg_doc)

        # Broadcast to chat room
        emit('receive_message', {
            'messageId': str(result.inserted_id),
            'senderId': sender_id,
            'senderRole': sender_role,
            'message': message,
            'timestamp': msg_doc['timestamp'].isoformat()
        }, to=room_id)

        # Save unread count to DB (persists after logout)
        unread_counts.update_one(
            {'userId': receiver_id, 'roomId': room_id},
            {'$inc': {'count': 1}},
            upsert=True
        )

        # Real-time notification if receiver is online
        emit('new_message_notification', {
            'roomId': room_id
        }, room=str(receiver_id))

        logger.info(f"Message saved in room {room_id} by {sender_id}. Unread updated for {receiver_id}")

    except Exception as e:
        emit('error', {'message': str(e)})
        logger.error(f"Error saving message in room {room_id}: {str(e)}")

@socketio.on("leave_room")
def handle_leave_room(data):
    """Socket.IO: User leaves a chat room"""
    room_id = data.get("roomId")
    user_id = data.get("userId")
    leave_room(room_id)
    logger.info(f"User {user_id} left room {room_id}")


@socketio.on("edit_message")
def handle_edit_message(data):
    """Socket.IO: Edit an existing message (only sender can edit)"""
    room_id = data.get("roomId")
    message_id = data.get("messageId")
    sender_id = data.get("senderId")
    new_message = data.get("newMessage", "").strip()

    if not all([room_id, message_id, sender_id, new_message]):
        emit("error", {"message": "Missing required fields"})
        return

    try:
        from bson import ObjectId
        msg = chat_messages_collection.find_one({"_id": ObjectId(message_id)})
        if not msg:
            emit("error", {"message": "Message not found"})
            return
        if msg["senderId"] != sender_id:
            emit("error", {"message": "Unauthorized: cannot edit another user's message"})
            return

        chat_messages_collection.update_one(
            {"_id": ObjectId(message_id)},
            {"$set": {"message": new_message, "edited": True, "editedAt": datetime.now(pytz.UTC)}}
        )

        emit("message_edited", {
            "messageId": message_id,
            "newMessage": new_message,
            "editedAt": datetime.now(pytz.UTC).isoformat()
        }, to=room_id)

        logger.info(f"Message {message_id} edited by {sender_id} in room {room_id}")

    except Exception as e:
        emit("error", {"message": str(e)})
        logger.error(f"Error editing message {message_id}: {str(e)}")


@socketio.on("delete_message")
def handle_delete_message(data):
    """Socket.IO: Delete a message (only sender can delete)"""
    room_id = data.get("roomId")
    message_id = data.get("messageId")
    sender_id = data.get("senderId")

    if not all([room_id, message_id, sender_id]):
        emit("error", {"message": "Missing required fields"})
        return

    try:
        from bson import ObjectId
        msg = chat_messages_collection.find_one({"_id": ObjectId(message_id)})
        if not msg:
            emit("error", {"message": "Message not found"})
            return
        if msg["senderId"] != sender_id:
            emit("error", {"message": "Unauthorized: cannot delete another user's message"})
            return

        chat_messages_collection.delete_one({"_id": ObjectId(message_id)})

        emit("message_deleted", {"messageId": message_id}, to=room_id)

        logger.info(f"Message {message_id} deleted by {sender_id} in room {room_id}")

    except Exception as e:
        emit("error", {"message": str(e)})
        logger.error(f"Error deleting message {message_id}: {str(e)}")


# Cleanup on exit
@atexit.register
def cleanup():
    logger.info("Closing MongoDB connection")
    client.close()

# Run the application
if __name__ == '__main__':
    host = os.getenv('SERVER_HOST', '0.0.0.0')
    port = int(os.getenv('SERVER_PORT', 5000))
    socketio.run(app, host=host, port=port, debug=True)